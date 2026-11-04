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
    ):
        self.mic_positions = mic_positions
        self.sample_rate = sample_rate
        self.num_sources = num_sources
        self.resolution_deg = resolution_deg
        self.frequency_range = frequency_range

        self.pairs = _select_pairs(len(mic_positions), max_pairs)

        self.azimuths, self.elevations = _build_candidate_directions(
            azimuth_range, elevation_range, resolution_deg
        )

        # Pre-compute sample-delay table: (A, E, P)
        self._precompute_delays()

    def _precompute_delays(self) -> None:
        """Pre-compute fractional sample delays for every (az, el, pair).

        Fully vectorized via einsum: builds all direction vectors at once,
        computes per-mic delays with a single matrix product, then derives
        pair TDOAs by index selection — no Python loops.
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

    def locate(self, channels: np.ndarray) -> List[Tuple[float, float, float]]:
        """Run SRP-PHAT on a block of multi-channel audio.

        Args:
            channels: (C, N) float64 array, one row per channel.

        Returns:
            List of (azimuth_rad, elevation_rad, power) tuples for each
            detected source, sorted by descending power.
        """
        n_samples = channels.shape[1]
        n_fft = 1
        while n_fft < 2 * n_samples - 1:
            n_fft <<= 1

        # Compute GCC-PHAT for all pairs
        gcc_matrix = gcc_phat_all_pairs(channels, self.pairs, n_fft=n_fft)

        # Evaluate steered response power for each candidate direction (vectorized)
        # delay_samples: (n_az, n_el, n_pairs) — convert to integer sample indices
        delay_indices = np.round(self.delay_samples).astype(np.int64) % n_fft
        # gcc_matrix: (n_pairs, n_fft)
        # gathered[ai, ei, pi] = gcc_matrix[pi, delay_indices[ai, ei, pi]]
        pair_idx = np.arange(len(self.pairs))
        gathered = gcc_matrix[pair_idx[np.newaxis, np.newaxis, :], delay_indices]
        power_map = gathered.sum(axis=2)  # (n_az, n_el)

        # Peak detection: find top-N peaks
        results = self._find_peaks(power_map)
        return results

    def _find_peaks(
        self, power_map: np.ndarray
    ) -> List[Tuple[float, float, float]]:
        """Find the top-N peaks in the power map with simple suppression.

        Args:
            power_map: (n_az, n_el) steered response power.

        Returns:
            List of (azimuth_rad, elevation_rad, power).
        """
        pm = power_map.copy()
        peaks: List[Tuple[float, float, float]] = []
        suppression_radius = max(1, int(15.0 / self.resolution_deg))

        for _ in range(self.num_sources):
            idx_flat = np.argmax(pm)
            ai, ei = np.unravel_index(idx_flat, pm.shape)
            power_val = pm[ai, ei]
            if power_val <= 0.0:
                break

            az_rad = float(self.azimuths[ai])
            el_rad = float(self.elevations[ei])
            peaks.append((az_rad, el_rad, float(power_val)))

            # Suppress neighbourhood
            az_lo = max(0, ai - suppression_radius)
            az_hi = min(pm.shape[0], ai + suppression_radius + 1)
            el_lo = max(0, ei - suppression_radius)
            el_hi = min(pm.shape[1], ei + suppression_radius + 1)
            pm[az_lo:az_hi, el_lo:el_hi] = 0.0

        return peaks
