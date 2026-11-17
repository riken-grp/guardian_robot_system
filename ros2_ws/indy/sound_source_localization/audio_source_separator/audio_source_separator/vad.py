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
        adaptive: bool = False,
        margin_db: float = 6.0,
        noise_init_db: float = -60.0,
        noise_rise_db: float = 0.05,
        noise_fall_alpha: float = 0.5,
    ):
        """Initialize the VAD.

        Args:
            threshold_db: Energy threshold in dB for speech detection.
            hangover_frames: Number of frames to keep speech active after
                energy drops below threshold (prevents choppy detection).
            min_speech_frames: Minimum consecutive above-threshold frames
                required to trigger speech onset.
            adaptive: When True the effective threshold is
                ``max(threshold_db, noise_floor_db + margin_db)``, where the
                noise floor is tracked from every frame (fast fall, slow
                rise).  ``threshold_db`` then acts as the
                absolute minimum.
            margin_db: Margin above the noise floor (adaptive mode).
            noise_init_db: Initial noise floor estimate (adaptive mode).
            noise_rise_db: Max increase of the noise floor per frame (dB).
            noise_fall_alpha: EMA weight when the energy is below the floor.
        """
        self.threshold_db = threshold_db
        self.hangover_frames = hangover_frames
        self.min_speech_frames = min_speech_frames
        self.adaptive = adaptive
        self.margin_db = margin_db
        self.noise_rise_db = noise_rise_db
        self.noise_fall_alpha = noise_fall_alpha
        self.noise_floor_db = noise_init_db
        self.last_energy_db = -100.0

        # State
        self._is_speech = False
        self._hangover_counter = 0
        self._onset_counter = 0

    @property
    def current_threshold_db(self) -> float:
        """Threshold (dB) applied to the next frame."""
        if not self.adaptive:
            return self.threshold_db
        return max(self.threshold_db, self.noise_floor_db + self.margin_db)

    def _update_noise_floor(self, energy_db: float) -> None:
        if energy_db < self.noise_floor_db:
            self.noise_floor_db += self.noise_fall_alpha * (energy_db - self.noise_floor_db)
        else:
            self.noise_floor_db = min(energy_db, self.noise_floor_db + self.noise_rise_db)

    def reset(self):
        """Reset the VAD state (the learned noise floor is kept)."""
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
        self.last_energy_db = energy_db
        above_threshold = energy_db >= self.current_threshold_db
        # Track the noise floor on every frame: fast fall, slow rise (at most
        # noise_rise_db per frame), so a speech onset barely moves it, while
        # a lasting increase of the background noise (which would otherwise
        # keep the VAD in "speech") is followed within a few seconds.
        if self.adaptive:
            self._update_noise_floor(energy_db)

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
