"""Source manager for person-DOA association and audio buffering."""

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

from .vad import EnergyVAD


@dataclass
class SpeechSource:
    """Tracked speech source associated with a person."""
    person_id: int
    azimuth: float
    distance: float
    vad: EnergyVAD
    audio_buffer: list[np.ndarray] = field(default_factory=list)
    speech_start_ns: int = 0
    is_speaking: bool = False
    last_update_time: float = 0.0
    last_audio_timestamp_ns: int = 0
    total_buffered_samples: int = 0


@dataclass
class CompletedSegment:
    """A completed speech segment ready to publish."""
    person_id: int
    azimuth: float
    distance: float
    sample_rate: int
    audio_data: np.ndarray
    speech_start_ns: int
    speech_end_ns: int


class SourceManager:
    """Manages person-to-DOA associations and audio buffering.

    Associates tracked persons with DOA estimates by comparing azimuth
    angles. Buffers beamformed audio for active speakers and emits
    completed speech segments when VAD detects speech offset.
    """

    def __init__(
        self,
        association_angle_threshold: float = 0.35,
        stale_timeout: float = 3.0,
        min_speech_duration: float = 0.3,
        max_speech_duration: float = 10.0,
        vad_threshold_db: float = -40.0,
        vad_hangover_frames: int = 10,
        vad_min_speech_frames: int = 3,
        sample_rate: int = 16000,
        time_func: Callable[[], float] | None = None,
    ):
        """Initialize the source manager.

        Args:
            association_angle_threshold: Max angle difference (rad) to
                associate a person with a DOA estimate.
            stale_timeout: Seconds before dropping a stale association.
            min_speech_duration: Minimum speech segment duration (seconds).
            max_speech_duration: Maximum speech segment duration (seconds).
            vad_threshold_db: VAD energy threshold in dB.
            vad_hangover_frames: VAD hangover frames.
            vad_min_speech_frames: VAD minimum speech frames for onset.
            sample_rate: Audio sample rate.
            time_func: Callable returning current time in seconds. Defaults to
                time.monotonic. Inject node.get_clock().now().nanoseconds * 1e-9
                for ROS-time-aware operation (rosbag / simulation support).
        """
        self.association_angle_threshold = association_angle_threshold
        self.stale_timeout = stale_timeout
        self.min_speech_duration = min_speech_duration
        self.max_speech_duration = max_speech_duration
        self.vad_threshold_db = vad_threshold_db
        self.vad_hangover_frames = vad_hangover_frames
        self.vad_min_speech_frames = vad_min_speech_frames
        self.sample_rate = sample_rate
        self._time_func: Callable[[], float] = (
            time_func if time_func is not None else time.monotonic
        )

        # person_id -> SpeechSource
        self.sources: dict[int, SpeechSource] = {}

    def _angle_distance(self, a1: float, a2: float) -> float:
        """Compute the shortest angular distance between two angles (rad)."""
        diff = a1 - a2
        # Normalize to [-pi, pi]
        diff = (diff + np.pi) % (2 * np.pi) - np.pi
        return abs(diff)

    def associate_persons_with_doa(
        self,
        person_ids: list[int],
        person_azimuths: list[float],
        person_distances: list[float],
        doa_azimuths: list[float],
        doa_powers: list[float],
    ) -> dict[int, float]:
        """Associate tracked persons with DOA estimates (one-to-one).

        Uses the Hungarian algorithm for globally optimal one-to-one matching,
        preventing multiple persons from being assigned to the same DOA source.
        The angular cost matrix is computed via numpy broadcasting (no Python
        loop over persons × DOAs).

        Args:
            person_ids: List of person IDs.
            person_azimuths: List of person azimuth angles (rad).
            person_distances: List of person distances (m).
            doa_azimuths: List of DOA estimate azimuths (rad).
            doa_powers: List of DOA estimate powers.

        Returns:
            Dict mapping person_id to matched DOA azimuth.
        """
        now = self._time_func()
        associations: dict[int, float] = {}

        if not doa_azimuths or not person_ids:
            return associations

        # Vectorised angular cost matrix: (n_persons, n_doas)
        p_az = np.array(person_azimuths)[:, np.newaxis]  # (n_persons, 1)
        d_az = np.array(doa_azimuths)[np.newaxis, :]     # (1, n_doas)
        diff = p_az - d_az
        cost_matrix = np.abs((diff + np.pi) % (2 * np.pi) - np.pi)  # (n_persons, n_doas)

        # Hungarian algorithm: globally optimal one-to-one assignment
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        for i, j in zip(row_ind, col_ind):
            if cost_matrix[i, j] > self.association_angle_threshold:
                continue

            pid = person_ids[i]
            p_dist = person_distances[i]
            matched_az = doa_azimuths[j]
            associations[pid] = matched_az

            # Create or update source
            if pid not in self.sources:
                self.sources[pid] = SpeechSource(
                    person_id=pid,
                    azimuth=matched_az,
                    distance=p_dist,
                    vad=EnergyVAD(
                        threshold_db=self.vad_threshold_db,
                        hangover_frames=self.vad_hangover_frames,
                        min_speech_frames=self.vad_min_speech_frames,
                    ),
                    last_update_time=now,
                )
            else:
                self.sources[pid].azimuth = matched_az
                self.sources[pid].distance = p_dist
                self.sources[pid].last_update_time = now

        return associations

    def process_audio(
        self,
        person_id: int,
        beamformed_audio: np.ndarray,
        timestamp_ns: int,
    ) -> list[CompletedSegment]:
        """Process beamformed audio for a person and detect speech segments.

        Args:
            person_id: The person ID.
            beamformed_audio: Beamformed single-channel audio (float).
            timestamp_ns: Timestamp in nanoseconds for this audio block.

        Returns:
            List of CompletedSegment (0, 1, or 2 elements). Two segments can
            be returned when a new onset immediately follows a previous speech
            utterance.
        """
        if person_id not in self.sources:
            return []

        source = self.sources[person_id]
        source.last_update_time = self._time_func()
        source.last_audio_timestamp_ns = timestamp_ns

        onset, offset = source.vad.detect_onset(beamformed_audio)

        results: list[CompletedSegment] = []

        if onset:
            # Finalize any previous speech before starting a new segment
            if source.is_speaking and source.audio_buffer:
                seg = self._finalize_segment(source, timestamp_ns)
                if seg is not None:
                    results.append(seg)
            source.is_speaking = True
            source.speech_start_ns = timestamp_ns
            source.audio_buffer = [beamformed_audio.copy()]
            source.total_buffered_samples = len(beamformed_audio)

        elif source.is_speaking:
            source.audio_buffer.append(beamformed_audio.copy())
            source.total_buffered_samples += len(beamformed_audio)

            # Check max duration
            duration = source.total_buffered_samples / self.sample_rate
            if duration >= self.max_speech_duration:
                seg = self._finalize_segment(source, timestamp_ns)
                if seg is not None:
                    results.append(seg)
                return results

        if offset and source.is_speaking:
            seg = self._finalize_segment(source, timestamp_ns)
            if seg is not None:
                results.append(seg)

        return results

    def _finalize_segment(
        self,
        source: SpeechSource,
        end_timestamp_ns: int,
    ) -> CompletedSegment | None:
        """Finalize a speech segment from a source's buffer.

        Returns:
            CompletedSegment if duration meets minimum, else None.
        """
        if not source.audio_buffer:
            source.is_speaking = False
            return None

        audio = np.concatenate(source.audio_buffer)
        duration = len(audio) / self.sample_rate

        # Reset source state
        source.is_speaking = False
        source.audio_buffer = []
        source.total_buffered_samples = 0
        source.vad.reset()

        if duration < self.min_speech_duration:
            return None

        return CompletedSegment(
            person_id=source.person_id,
            azimuth=source.azimuth,
            distance=source.distance,
            sample_rate=self.sample_rate,
            audio_data=audio,
            speech_start_ns=source.speech_start_ns,
            speech_end_ns=end_timestamp_ns,
        )

    def cleanup_stale(self) -> list[CompletedSegment]:
        """Remove stale associations and emit any buffered speech.

        Returns:
            List of completed segments from stale sources that had
            active speech buffers.
        """
        now = self._time_func()
        segments = []
        stale_ids = []

        for pid, source in self.sources.items():
            if now - source.last_update_time > self.stale_timeout:
                # If there's buffered speech, try to finalize it
                if source.is_speaking and source.audio_buffer:
                    seg = self._finalize_segment(
                        source,
                        source.last_audio_timestamp_ns,
                    )
                    if seg is not None:
                        segments.append(seg)
                stale_ids.append(pid)

        for pid in stale_ids:
            del self.sources[pid]

        return segments
