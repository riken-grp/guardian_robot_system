"""Energy-based Voice Activity Detection (VAD)."""

import numpy as np


class EnergyVAD:
    """Energy-based voice activity detector with hangover mechanism.

    Computes frame energy in dB, applies a threshold, and uses minimum
    duration filtering and hangover to track speech onset/offset.
    """

    def __init__(
        self,
        threshold_db: float = -40.0,
        hangover_frames: int = 10,
        min_speech_frames: int = 3,
    ):
        """Initialize the VAD.

        Args:
            threshold_db: Energy threshold in dB for speech detection.
            hangover_frames: Number of frames to keep speech active after
                energy drops below threshold (prevents choppy detection).
            min_speech_frames: Minimum consecutive above-threshold frames
                required to trigger speech onset.
        """
        self.threshold_db = threshold_db
        self.hangover_frames = hangover_frames
        self.min_speech_frames = min_speech_frames

        # State
        self._is_speech = False
        self._hangover_counter = 0
        self._onset_counter = 0

    def reset(self):
        """Reset the VAD state."""
        self._is_speech = False
        self._hangover_counter = 0
        self._onset_counter = 0

    @property
    def is_speech(self) -> bool:
        """Whether speech is currently detected."""
        return self._is_speech

    @staticmethod
    def compute_energy_db(audio: np.ndarray) -> float:
        """Compute the energy of an audio frame in dB.

        Args:
            audio: 1D audio samples (float).

        Returns:
            Energy in dB (relative to full-scale float [-1, 1]).
        """
        if len(audio) == 0:
            return -np.inf
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-10:
            return -100.0
        return 20.0 * np.log10(rms)

    def process_frame(self, audio_frame: np.ndarray) -> bool:
        """Process a single audio frame and update VAD state.

        Args:
            audio_frame: 1D audio samples (float) for this frame.

        Returns:
            True if speech is detected (including hangover), False otherwise.
        """
        energy_db = self.compute_energy_db(audio_frame)
        above_threshold = energy_db >= self.threshold_db

        prev_speech = self._is_speech

        if above_threshold:
            self._hangover_counter = self.hangover_frames
            if not self._is_speech:
                self._onset_counter += 1
                if self._onset_counter >= self.min_speech_frames:
                    self._is_speech = True
            # else: already in speech, stay in speech
        else:
            self._onset_counter = 0
            if self._is_speech:
                self._hangover_counter -= 1
                if self._hangover_counter <= 0:
                    self._is_speech = False
                    self._hangover_counter = 0

        return self._is_speech

    def detect_onset(self, audio_frame: np.ndarray) -> tuple[bool, bool]:
        """Process a frame and detect speech onset/offset transitions.

        Args:
            audio_frame: 1D audio samples (float) for this frame.

        Returns:
            Tuple of (onset, offset) booleans indicating transitions.
            onset: True on the frame where speech starts.
            offset: True on the frame where speech ends.
        """
        was_speech = self._is_speech
        is_speech = self.process_frame(audio_frame)

        onset = is_speech and not was_speech
        offset = not is_speech and was_speech

        return onset, offset
