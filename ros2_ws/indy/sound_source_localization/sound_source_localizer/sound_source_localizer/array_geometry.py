"""Microphone array geometry management.

Loads microphone positions from a YAML configuration file and computes
inter-microphone distances, steering vectors, and time delays for
beamforming / SRP-PHAT processing.
"""

import numpy as np
import yaml


SPEED_OF_SOUND = 343.0  # m/s


def load_array_geometry(yaml_path: str) -> np.ndarray:
    """Load microphone positions from a YAML file.

    Args:
        yaml_path: Path to the array geometry YAML file.

    Returns:
        (N, 3) array of microphone positions in metres [x, y, z].
    """
    with open(yaml_path, 'r') as f:
        config = yaml.safe_load(f)

    mics = config['microphones']
    # Sort by channel index if present, otherwise preserve YAML order
    if mics and 'channel' in mics[0]:
        mics_sorted = sorted(mics, key=lambda m: m['channel'])
    else:
        mics_sorted = mics
    positions = np.array([[m['x'], m['y'], m['z']] for m in mics_sorted],
                         dtype=np.float64)
    return positions


def compute_inter_mic_distances(positions: np.ndarray) -> np.ndarray:
    """Compute pairwise Euclidean distances between microphones.

    Args:
        positions: (N, 3) microphone positions.

    Returns:
        (N, N) symmetric distance matrix.
    """
    diff = positions[:, np.newaxis, :] - positions[np.newaxis, :, :]
    return np.sqrt(np.sum(diff ** 2, axis=-1))


def direction_vector(azimuth_rad: float, elevation_rad: float) -> np.ndarray:
    """Unit direction vector for a given azimuth and elevation.

    Azimuth is measured counter-clockwise from the x-axis in the x-y plane.
    Elevation is measured upward from the x-y plane.

    Returns:
        (3,) unit vector.
    """
    cos_el = np.cos(elevation_rad)
    return np.array([
        cos_el * np.cos(azimuth_rad),
        cos_el * np.sin(azimuth_rad),
        np.sin(elevation_rad),
    ])


def compute_time_delays(positions: np.ndarray,
                        azimuth_rad: float,
                        elevation_rad: float) -> np.ndarray:
    """Compute inter-microphone time delays for a plane-wave from (az, el).

    The delay for mic *i* relative to the array centroid is:
        tau_i = - (d . p_i) / c

    where *d* is the unit direction toward the source and *p_i* is the
    mic position relative to the centroid.

    Args:
        positions: (N, 3) microphone positions.
        azimuth_rad: Source azimuth in radians.
        elevation_rad: Source elevation in radians.

    Returns:
        (N,) array of time delays in seconds (relative to centroid).
    """
    d = direction_vector(azimuth_rad, elevation_rad)
    centroid = positions.mean(axis=0)
    relative = positions - centroid
    # Negative sign: sound *arriving from* direction d reaches mics closer
    # to d earlier (negative delay).
    delays = -relative @ d / SPEED_OF_SOUND
    return delays


def compute_pair_delays(positions: np.ndarray,
                        azimuth_rad: float,
                        elevation_rad: float,
                        pairs: np.ndarray) -> np.ndarray:
    """Compute time-delay differences for selected microphone pairs.

    Args:
        positions: (N, 3) microphone positions.
        azimuth_rad: Source azimuth in radians.
        elevation_rad: Source elevation in radians.
        pairs: (P, 2) array of mic-index pairs.

    Returns:
        (P,) array of TDOA values tau_i - tau_j in seconds.
    """
    delays = compute_time_delays(positions, azimuth_rad, elevation_rad)
    return delays[pairs[:, 0]] - delays[pairs[:, 1]]
