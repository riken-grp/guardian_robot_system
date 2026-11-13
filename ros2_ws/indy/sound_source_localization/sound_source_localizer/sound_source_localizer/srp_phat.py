"""SRP-PHAT (Steered Response Power with Phase Transform) implementation.

Performs broadband sound-source localisation by accumulating GCC-PHAT
cross-correlations steered toward candidate directions.
"""

from typing import List, Tuple

import numpy as np
from scipy.fft import rfft, irfft

from .array_geometry import (
    compute_pair_delays,
    SPEED_OF_SOUND,
)


def _select_pairs(n_mics: int, max_pairs: int = 60) -> np.ndarray:
    """Select microphone pairs for cross-correlation.

    Uses all unique pairs when the total count is below *max_pairs*,
    otherwise selects a subset favouring well-separated pairs.

    Returns:
        (P, 2) int array of mic-index pairs.
    """
    all_pairs = []
    for i in range(n_mics):
        for j in range(i + 1, n_mics):
            all_pairs.append((i, j))
    all_pairs = np.array(all_pairs, dtype=np.int32)
    if len(all_pairs) <= max_pairs:
        return all_pairs
    # Sub-sample: keep every k-th pair
    step = max(1, len(all_pairs) // max_pairs)
    return all_pairs[::step]


def gcc_phat(sig_i: np.ndarray, sig_j: np.ndarray,
             n_fft: int | None = None) -> np.ndarray:
    """Compute GCC-PHAT cross-correlation between two signals.

    Args:
        sig_i: (N,) first channel signal.
        sig_j: (N,) second channel signal.
        n_fft: FFT length (defaults to next power-of-two >= 2*N-1).

    Returns:
        (n_fft,) real-valued cross-correlation with zero-lag at index 0
        (use np.fft.fftshift or manual indexing to interpret).
    """
    n = len(sig_i)
    if n_fft is None:
        n_fft = 1
        while n_fft < 2 * n - 1:
            n_fft <<= 1

    X_i = rfft(sig_i, n=n_fft)
    X_j = rfft(sig_j, n=n_fft)

    cross_spectrum = X_i * np.conj(X_j)
    magnitude = np.abs(cross_spectrum)
    # Avoid division by zero
    magnitude = np.maximum(magnitude, 1e-12)
    gcc = irfft(cross_spectrum / magnitude, n=n_fft)
    return gcc


def gcc_phat_all_pairs(channels: np.ndarray,
                       pairs: np.ndarray,
                       n_fft: int | None = None) -> np.ndarray:
    """Compute GCC-PHAT for all selected microphone pairs.

    Computes a single batched FFT over all channels, then selects pairs
    and cross-multiplies in one vectorized pass — O(C * n_fft) FFTs
    instead of O(2 * P * n_fft).

    Args:
        channels: (C, N) multi-channel signal (C channels, N samples).
        pairs: (P, 2) mic-index pairs.
        n_fft: FFT length.

    Returns:
        (P, n_fft) array of GCC-PHAT cross-correlations.
    """
    n_samples = channels.shape[1]
    if n_fft is None:
        n_fft = 1
        while n_fft < 2 * n_samples - 1:
            n_fft <<= 1

    # Single batched FFT for all channels: (C, n_freqs)
    X = rfft(channels, n=n_fft, axis=1)

    # Vectorized cross-correlation for all pairs simultaneously
    X_i = X[pairs[:, 0]]                           # (P, n_freqs)
    X_j = X[pairs[:, 1]]                           # (P, n_freqs)
    cross = X_i * np.conj(X_j)                     # (P, n_freqs)
    magnitude = np.maximum(np.abs(cross), 1e-12)   # PHAT weighting
    gcc_matrix = irfft(cross / magnitude, n=n_fft, axis=1)  # (P, n_fft)
    return gcc_matrix


def _build_candidate_directions(
    azimuth_range: Tuple[float, float],
    elevation_range: Tuple[float, float],
    resolution_deg: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build arrays of candidate azimuth/elevation angles (radians).

    Returns:
        azimuths: (A,) array in radians.
        elevations: (E,) array in radians.
    """
    az_start, az_end = azimuth_range
    el_start, el_end = elevation_range
    azimuths = np.deg2rad(np.arange(az_start, az_end, resolution_deg))
    elevations = np.deg2rad(np.arange(el_start, el_end + resolution_deg,
                                      resolution_deg))
    return azimuths, elevations


class SrpPhat:
    """SRP-PHAT sound-source localiser."""

    def __init__(
        self,
        mic_positions: np.ndarray,
        sample_rate: int = 16000,
        num_sources: int = 3,
        resolution_deg: float = 5.0,
        frequency_range: Tuple[float, float] = (300.0, 3500.0),
        azimuth_range: Tuple[float, float] = (0.0, 360.0),
        elevation_range: Tuple[float, float] = (-30.0, 30.0),
        max_pairs: int = 60,
        power_threshold: float = 0.05,
        interp_factor: int = 4,
        suppression_deg: float = 15.0,
    ):
        """
        Args:
            power_threshold: Minimum *normalised* steered response power for
                a peak to be reported.  The SRP is divided by its theoretical
                maximum (all pairs perfectly coherent at the steered lag), so
                the value is in [-1, 1] and independent of block / FFT size.
                Peaks below this value are discarded, so silence or diffuse
                noise yields no (or fewer than ``num_sources``) estimates.
                Set to a value <= -1 to disable.
            interp_factor: Oversampling factor of the GCC inverse FFT, used
                for sub-sample (fractional) delay resolution.  1 disables.
            suppression_deg: Neighbourhood (degrees) suppressed around each
                detected peak (azimuth wraps around 0/360).
        """
        self.mic_positions = mic_positions
        self.sample_rate = sample_rate
        self.num_sources = num_sources
        self.resolution_deg = resolution_deg
        self.frequency_range = (float(frequency_range[0]),
                                float(frequency_range[1]))
        self.power_threshold = float(power_threshold)
        self.interp_factor = max(1, int(interp_factor))
        self.suppression_deg = float(suppression_deg)

        self.pairs = _select_pairs(len(mic_positions), max_pairs)

        self.azimuths, self.elevations = _build_candidate_directions(
            azimuth_range, elevation_range, resolution_deg
        )
        # Azimuth grid wraps around when it spans a full circle
        self._az_circular = abs(
            (azimuth_range[1] - azimuth_range[0]) - 360.0) < 1e-6

        # Pre-compute sample-delay table: (A, E, P)
        self._precompute_delays()

    def _precompute_delays(self) -> None:
        """Pre-compute fractional sample delays for every (az, el, pair).

        Fully vectorized via einsum: builds all direction vectors at once,
        computes per-mic delays with a single matrix product, then derives
        pair TDOAs by index selection — no Python loops.

        Also invalidates the per-n_fft caches (band mask, delay indices),
        so call this again whenever ``sample_rate`` changes.
        """
        az = self.azimuths   # (n_az,)
        el = self.elevations  # (n_el,)

        # Direction unit vectors for all (az, el) combinations: (n_az, n_el, 3)
        az_g = az[:, np.newaxis]   # (n_az, 1)
        el_g = el[np.newaxis, :]   # (1, n_el)
        cos_el = np.cos(el_g)
        d = np.stack(
            [cos_el * np.cos(az_g),
             cos_el * np.sin(az_g),
             np.broadcast_to(np.sin(el_g), (len(az), len(el)))],
            axis=-1,
        )  # (n_az, n_el, 3)

        # Per-mic delays: tau[a,e,m] = -(relative_m · d[a,e]) / c
        centroid = self.mic_positions.mean(axis=0)
        relative = self.mic_positions - centroid  # (n_mics, 3)
        delays = -np.einsum('mk,aek->aem', relative, d) / SPEED_OF_SOUND  # (n_az, n_el, n_mics)

        # Pair TDOA: tau_i - tau_j, converted to samples
        pi = self.pairs[:, 0]
        pj = self.pairs[:, 1]
        self.delay_samples = (delays[:, :, pi] - delays[:, :, pj]) * self.sample_rate  # (n_az, n_el, n_pairs)

        # Per-n_fft caches (rebuilt lazily in _get_fft_cache)
        self._fft_cache: dict = {}

    def _get_fft_cache(self, n_fft: int):
        """Return (band_mask, lag_indices, gather_columns, norm) for n_fft.

        * band_mask: (n_freqs,) float mask, 1 inside ``frequency_range``.
        * lag_indices: sorted unique (oversampled) circular lag indices that
          the delay table actually needs (|lag| <= max TDOA).
        * gather_columns: (n_az, n_el, n_pairs) index into ``lag_indices``.
        * norm: GCC value of a perfectly coherent pair at the right lag
          (used to normalise the SRP to [-1, 1]).
        """
        cache = self._fft_cache.get(n_fft)
        if cache is not None:
            return cache

        n_freqs = n_fft // 2 + 1
        freqs = np.arange(n_freqs) * self.sample_rate / n_fft
        f_lo, f_hi = self.frequency_range
        band_mask = ((freqs >= f_lo) & (freqs <= f_hi)).astype(np.float64)
        if not band_mask.any():
            band_mask[:] = 1.0  # degenerate range: fall back to full band

        r = self.interp_factor
        n_ifft = n_fft * r
        delay_idx = np.round(self.delay_samples * r).astype(np.int64) % n_ifft
        lag_indices, inverse = np.unique(delay_idx, return_inverse=True)
        gather_columns = inverse.reshape(delay_idx.shape)

        # Perfectly coherent pair: unit-magnitude cross spectrum with zero
        # phase -> value at lag 0 of the (masked, oversampled) inverse FFT.
        norm = float(irfft(band_mask, n=n_ifft)[0]) * r
        norm = max(norm, 1e-12)

        cache = (band_mask, lag_indices, gather_columns, norm)
        self._fft_cache[n_fft] = cache
        return cache

    def compute_power_map(self, channels: np.ndarray) -> np.ndarray:
        """Normalised steered response power map, shape (n_az, n_el)."""
        n_samples = channels.shape[1]
        n_fft = 1
        while n_fft < 2 * n_samples - 1:
            n_fft <<= 1

        band_mask, lag_indices, gather_columns, norm = self._get_fft_cache(n_fft)
        r = self.interp_factor

        # Single batched FFT for all channels, PHAT weighting, band limit
        X = rfft(channels, n=n_fft, axis=1)
        cross = X[self.pairs[:, 0]] * np.conj(X[self.pairs[:, 1]])
        cross = cross / np.maximum(np.abs(cross), 1e-12) * band_mask
        # Oversampled inverse FFT (zero-padding in the frequency domain)
        # gives fractional-lag resolution.  Scale by r so values match the
        # non-oversampled GCC.
        gcc = irfft(cross, n=n_fft * r, axis=1) * r  # (P, n_fft * r)
        gcc_lags = gcc[:, lag_indices]                # (P, L)

        pair_idx = np.arange(len(self.pairs))
        gathered = gcc_lags[pair_idx[np.newaxis, np.newaxis, :], gather_columns]
        power_map = gathered.sum(axis=2)  # (n_az, n_el)
        return power_map / (norm * len(self.pairs))

    def locate(self, channels: np.ndarray) -> List[Tuple[float, float, float]]:
        """Run SRP-PHAT on a block of multi-channel audio.

        Args:
            channels: (C, N) float array, one row per channel.

        Returns:
            List of (azimuth_rad, elevation_rad, power) tuples for each
            detected source, sorted by descending power.  ``power`` is the
            normalised SRP (1.0 = all microphone pairs perfectly coherent).
            At most ``num_sources`` entries; fewer (possibly none) when the
            peaks are below ``power_threshold``.
        """
        power_map = self.compute_power_map(channels)
        return self._find_peaks(power_map)

    def _find_peaks(
        self, power_map: np.ndarray
    ) -> List[Tuple[float, float, float]]:
        """Find the top-N peaks in the power map with neighbourhood suppression.

        Azimuth suppression wraps around 0/360 degrees (when the grid spans
        the full circle) so that a source near 0 deg is not reported twice.

        Args:
            power_map: (n_az, n_el) normalised steered response power.

        Returns:
            List of (azimuth_rad, elevation_rad, power).
        """
        pm = power_map.astype(np.float64, copy=True)
        n_az, n_el = pm.shape
        peaks: List[Tuple[float, float, float]] = []
        radius = max(1, int(round(self.suppression_deg / self.resolution_deg)))
        offsets = np.arange(-radius, radius + 1)

        for _ in range(self.num_sources):
            idx_flat = int(np.argmax(pm))
            ai, ei = np.unravel_index(idx_flat, pm.shape)
            power_val = pm[ai, ei]
            if not np.isfinite(power_val) or power_val < self.power_threshold:
                break

            peaks.append((float(self.azimuths[ai]),
                          float(self.elevations[ei]),
                          float(power_val)))

            # Suppress neighbourhood (azimuth: modular, elevation: clipped).
            # All elevations of the neighbouring azimuths are suppressed since
            # the elevation resolution of a planar array is poor.
            if self._az_circular:
                az_idx = (ai + offsets) % n_az
            else:
                az_idx = ai + offsets
                az_idx = az_idx[(az_idx >= 0) & (az_idx < n_az)]
            pm[np.unique(az_idx), :] = -np.inf

        return peaks
