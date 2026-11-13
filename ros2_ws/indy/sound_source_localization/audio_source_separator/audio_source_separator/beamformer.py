"""MVDR / delay-and-sum beamformers for multi-channel microphone array audio.

Sign convention (shared with sound_source_localizer.array_geometry):
for a far-field source in unit direction d, microphone m at position p_m
(relative to the array centroid) receives the wavefront with arrival delay

    tau_m = -(p_m . d) / c       (mics closer to the source hear it earlier)

so x_m(t) = s(t - tau_m)  <=>  X_m(f) = S(f) exp(-j 2 pi f tau_m)
                                      = S(f) exp(+j 2 pi f (p_m . d) / c).

The steering vector is therefore a_m(f) = exp(+j 2 pi f (p_m . d) / c), and
the time alignment X_m(f) exp(+j 2 pi f tau_m) = X_m(f) conj(a_m(f)).
"""

from typing import Sequence

import numpy as np
from scipy.fft import rfft, irfft


class MVDRBeamformer:
    """Minimum Variance Distortionless Response (MVDR) beamformer.

    Computes beamforming weights from the spatial covariance matrix and
    a steering vector derived from the array geometry and target direction.
    """

    def __init__(
        self,
        mic_positions: np.ndarray,
        sample_rate: int,
        fft_size: int = 512,
        speed_of_sound: float = 343.0,
        diagonal_loading: float = 1e-4,
        forget_factor: float = 0.9,
    ):
        """Initialize the MVDR beamformer.

        Args:
            mic_positions: (N_mics, 3) array of microphone positions in meters.
            sample_rate: Audio sample rate in Hz.
            fft_size: FFT size for frequency-domain processing.
            speed_of_sound: Speed of sound in m/s.
            diagonal_loading: Regularization factor for covariance inversion.
            forget_factor: EMA weight for covariance update (0 < alpha <= 1).
                Higher values track changes faster but are noisier.
                Typical range: 0.7 (fast adaptation) to 0.95 (smooth estimate).
        """
        self.mic_positions = np.asarray(mic_positions, dtype=np.float64)
        self.n_mics = self.mic_positions.shape[0]
        # Positions relative to the array centroid (phase reference)
        self._rel_positions = self.mic_positions - self.mic_positions.mean(axis=0)
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.speed_of_sound = speed_of_sound
        self.diagonal_loading = diagonal_loading
        self.forget_factor = forget_factor

        self.n_freqs = fft_size // 2 + 1
        self.freqs = np.arange(self.n_freqs) * sample_rate / fft_size

        # Running spatial covariance matrix: (n_freqs, n_mics, n_mics)
        self._cov: np.ndarray | None = None

    def compute_steering_vector(self, azimuth: float, elevation: float = 0.0) -> np.ndarray:
        """Compute the frequency-domain steering vector for a given direction.

        Args:
            azimuth: Target azimuth angle in radians.
            elevation: Target elevation angle in radians.

        Returns:
            Steering vector of shape (n_freqs, n_mics) as complex values.
        """
        # Arrival-time *advance* of each mic relative to the array centroid:
        # (p_m . d) / c = -tau_m  (see module docstring)
        advance = self._rel_positions @ _unit_vector(azimuth, elevation) \
            / self.speed_of_sound  # (n_mics,)

        # Steering vector a_m(f) = exp(+j 2 pi f (p_m . d) / c),
        # i.e. X_m = S * a_m for a plane wave from the target direction.
        # Shape: (n_freqs, n_mics)
        phase = 2.0 * np.pi * self.freqs[:, np.newaxis] * advance[np.newaxis, :]
        return np.exp(1j * phase)

    def _update_covariance(self, X: np.ndarray) -> np.ndarray:
        """Update the running spatial covariance matrix using EMA.

        R_new = (1 - alpha) * R_prev + alpha * x * x^H

        Accumulating across frames gives a full-rank covariance estimate,
        enabling proper MVDR interference suppression (unlike the single-frame
        rank-1 estimate used in the original implementation).

        Args:
            X: (n_freqs, n_mics) complex frequency-domain signals.

        Returns:
            Updated (n_freqs, n_mics, n_mics) covariance matrix.
        """
        x = X[:, :, np.newaxis]         # (n_freqs, n_mics, 1)
        x_h = X[:, np.newaxis, :].conj()  # (n_freqs, 1, n_mics)
        R_instant = x @ x_h             # (n_freqs, n_mics, n_mics)

        if self._cov is None:
            self._cov = R_instant
        else:
            alpha = self.forget_factor
            self._cov = (1.0 - alpha) * self._cov + alpha * R_instant

        return self._cov

    def reset_covariance(self) -> None:
        """Reset the running covariance estimate (e.g., on scene change)."""
        self._cov = None

    def compute_weights(
        self,
        covariance: np.ndarray,
        steering: np.ndarray,
    ) -> np.ndarray:
        """Compute MVDR beamforming weights (fully vectorized over frequencies).

        w(f) = R^{-1}(f) d(f) / (d^H(f) R^{-1}(f) d(f))

        Uses np.linalg.solve (batched) instead of explicit inversion for
        better numerical stability and ~3x speedup over the per-frequency loop.

        Args:
            covariance: (n_freqs, n_mics, n_mics) spatial covariance matrices.
            steering: (n_freqs, n_mics) steering vectors.

        Returns:
            Beamforming weights of shape (n_freqs, n_mics).
        """
        # Add diagonal loading for numerical stability
        loading = self.diagonal_loading * np.eye(self.n_mics, dtype=covariance.dtype)
        cov_reg = covariance + loading[np.newaxis, :, :]

        # Solve R @ x = d for all frequencies at once: (n_freqs, n_mics)
        try:
            R_inv_d = np.linalg.solve(cov_reg, steering)
        except np.linalg.LinAlgError:
            return steering / self.n_mics

        # MVDR denominator: d^H R^{-1} d for each frequency
        denom = np.einsum('fi,fi->f', steering.conj(), R_inv_d)  # (n_freqs,)

        # Where denominator is negligible, fall back to delay-and-sum
        valid = np.abs(denom) >= 1e-12
        safe_denom = np.where(valid, denom, 1.0)
        weights = np.where(
            valid[:, np.newaxis],
            R_inv_d / safe_denom[:, np.newaxis],
            steering / self.n_mics,
        )
        return weights

    def update_covariance(self, multichannel_audio: np.ndarray) -> np.ndarray:
        """Update the running SCM from one audio block and return the estimate.

        Call this **once per audio block** before calling apply() for multiple
        directions, so the SCM is updated exactly once regardless of how many
        beamforming directions are evaluated.

        Args:
            multichannel_audio: (n_samples, n_mics) time-domain audio, float64.

        Returns:
            Updated (n_freqs, n_mics, n_mics) spatial covariance matrix.
        """
        n_samples = multichannel_audio.shape[0]
        pad_len = (self.fft_size - n_samples % self.fft_size) % self.fft_size
        audio_padded = (
            np.pad(multichannel_audio, ((0, pad_len), (0, 0)), mode='constant')
            if pad_len > 0 else multichannel_audio
        )
        n_blocks = audio_padded.shape[0] // self.fft_size
        for b in range(n_blocks):
            block = audio_padded[b * self.fft_size:(b + 1) * self.fft_size, :]
            X = rfft(block, axis=0)
            self._update_covariance(X)
        return self._cov

    def apply(
        self,
        multichannel_audio: np.ndarray,
        azimuth: float,
        elevation: float = 0.0,
        covariance: np.ndarray | None = None,
    ) -> np.ndarray:
        """Apply MVDR beamforming to extract audio from a target direction.

        When processing multiple directions for the same audio block, pass the
        covariance returned by update_covariance() to avoid updating the SCM
        N times for N persons.  If covariance is None the SCM is updated
        internally (single-person or backward-compatible usage).

        Args:
            multichannel_audio: (n_samples, n_mics) time-domain audio, float64.
            azimuth: Target azimuth in radians.
            elevation: Target elevation in radians.
            covariance: Pre-computed (n_freqs, n_mics, n_mics) SCM. When None
                the running covariance is updated from this block.

        Returns:
            Beamformed single-channel audio of shape (n_samples,) as float64.
        """
        n_samples = multichannel_audio.shape[0]

        # Zero-pad to fft_size
        pad_len = (self.fft_size - n_samples % self.fft_size) % self.fft_size
        if pad_len > 0:
            multichannel_audio = np.pad(
                multichannel_audio, ((0, pad_len), (0, 0)), mode='constant'
            )

        n_padded = multichannel_audio.shape[0]
        n_blocks = n_padded // self.fft_size

        steering = self.compute_steering_vector(azimuth, elevation)
        output_blocks = []

        for b in range(n_blocks):
            block = multichannel_audio[b * self.fft_size:(b + 1) * self.fft_size, :]
            X = rfft(block, axis=0)  # (n_freqs, n_mics)

            if covariance is not None:
                # Multi-direction mode: use the shared pre-computed SCM
                cov = covariance
            else:
                # Single-direction / backward-compatible: update SCM per block
                cov = self._update_covariance(X)

            weights = self.compute_weights(cov, steering)
            Y = np.sum(weights.conj() * X, axis=1)  # (n_freqs,)
            y = irfft(Y, n=self.fft_size)
            output_blocks.append(y)

        output = np.concatenate(output_blocks)
        return output[:n_samples]

    # ------------------------------------------------------------------
    # Delay-and-sum
    # ------------------------------------------------------------------

    def _das_setup(self) -> None:
        """Lazily compute constants for the streaming delay-and-sum."""
        if getattr(self, '_das_ready', False):
            return
        # Largest possible |tau_m| (samples) over all directions
        max_adv = float(np.max(np.linalg.norm(self._rel_positions, axis=1)))
        self._das_max_delay = max_adv / self.speed_of_sound * self.sample_rate
        # Constant output latency: max |tau| plus a look-ahead so that the
        # (two-sided) fractional-delay sinc kernel never needs samples of
        # the *next* block (avoids clicks at block ends).
        lookahead = 16
        self._das_latency = self._das_max_delay + lookahead
        # Context (history) length: covers the largest net delay
        # (2 * max + look-ahead) plus a margin for the kernel tails.
        self._das_ctx = int(np.ceil(2.0 * self._das_max_delay)) + lookahead + 48
        self._das_tail: np.ndarray | None = None
        self._das_ready = True

    @property
    def das_latency_samples(self) -> float:
        """Constant output latency (samples) of :meth:`apply_das_multi`."""
        self._das_setup()
        return self._das_latency

    @property
    def das_context_samples(self) -> int:
        """Number of trailing samples kept as delay-and-sum history."""
        self._das_setup()
        return self._das_ctx

    def reset_das(self) -> None:
        """Forget the delay-and-sum history (e.g. after an audio gap)."""
        self._das_setup()
        self._das_tail = None

    def push_context(self, multichannel_audio: np.ndarray) -> None:
        """Update the delay-and-sum history without beamforming.

        Call this for blocks that are not beamformed so that the next
        block is filtered with the correct (contiguous) history.  Only the
        last few samples are kept, so passing a view of just the block's
        tail is enough.
        """
        self._das_setup()
        ctx = self._das_ctx
        a = np.asarray(multichannel_audio)
        if a.shape[0] >= ctx:
            self._das_tail = np.array(a[-ctx:], dtype=np.float32)
        else:
            prev = (self._das_tail if self._das_tail is not None
                    else np.zeros((ctx, a.shape[1]), dtype=np.float32))
            self._das_tail = np.concatenate([prev, a.astype(np.float32)])[-ctx:]

    def apply_das_multi(
        self,
        multichannel_audio: np.ndarray,
        azimuths: Sequence[float],
        elevation: float = 0.0,
    ) -> np.ndarray:
        """Delay-and-sum beamforming toward several directions at once.

        Streaming, frequency-domain fractional-delay DAS: the block is
        prefixed with the last samples of the previous block (history) and
        zero-padded, every channel is delayed by ``L - tau_m`` (``L`` = the
        maximum possible |tau| plus a small look-ahead, so all delays are
        causal) via a linear phase shift, and the channels are averaged.  The history prefix and the
        zero padding absorb the circular wrap-around, so consecutive output
        blocks join seamlessly.  The output has a constant latency of
        :attr:`das_latency_samples` (~1.2 ms for a ~0.1 m array).

        The FFT of the block is computed once and shared by all directions.

        Args:
            multichannel_audio: (n_samples, n_mics) time-domain audio.
            azimuths: Target azimuths in radians (array frame).
            elevation: Target elevation in radians.

        Returns:
            (len(azimuths), n_samples) float32 array of beamformed audio.
        """
        self._das_setup()
        x = np.asarray(multichannel_audio, dtype=np.float32)
        n_samples, n_mics = x.shape
        ctx = self._das_ctx
        n_dirs = len(azimuths)

        tail = self._das_tail
        if tail is None or tail.shape[1] != n_mics:
            tail = np.zeros((ctx, n_mics), dtype=np.float32)
        seg = np.concatenate([tail, x], axis=0)  # (ctx + n, n_mics)
        self.push_context(x)

        if n_dirs == 0:
            return np.zeros((0, n_samples), dtype=np.float32)

        n_fft = 1
        while n_fft < seg.shape[0] + ctx:
            n_fft <<= 1
        X = rfft(seg, n=n_fft, axis=0)  # (n_freqs, n_mics)
        freqs = np.arange(X.shape[0]) * (self.sample_rate / n_fft)

        # Net (causal) delay per direction and mic, in seconds:
        #   L - tau_m = L + (p_m . d) / c  in [L - D, L + D]
        dirs = np.stack([_unit_vector(az, elevation) for az in azimuths])
        advance = dirs @ self._rel_positions.T / self.speed_of_sound  # (K, M)
        net_delay = self._das_latency / self.sample_rate + advance     # (K, M)

        # Y_k(f) = 1/M sum_m X_m(f) exp(-j 2 pi f net_delay_km)
        phase = np.exp(-2j * np.pi * freqs[np.newaxis, :, np.newaxis]
                       * net_delay[:, np.newaxis, :])               # (K, F, M)
        Y = np.einsum('kfm,fm->kf', phase, X) / n_mics
        y = irfft(Y, n=n_fft, axis=1)
        return y[:, ctx:ctx + n_samples].astype(np.float32)

    def apply_das(
        self,
        multichannel_audio: np.ndarray,
        azimuth: float,
        elevation: float = 0.0,
    ) -> np.ndarray:
        """Delay-and-sum toward a single direction (see apply_das_multi).

        Note: this advances the streaming history, so for several
        directions on the same block use :meth:`apply_das_multi`.

        Returns:
            Beamformed single-channel audio of shape (n_samples,), float32.
        """
        return self.apply_das_multi(multichannel_audio, [azimuth], elevation)[0]


def _unit_vector(azimuth: float, elevation: float) -> np.ndarray:
    """Unit vector toward (azimuth, elevation); x-forward, y-left, z-up."""
    cos_el = np.cos(elevation)
    return np.array([
        cos_el * np.cos(azimuth),
        cos_el * np.sin(azimuth),
        np.sin(elevation),
    ])
