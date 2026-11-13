"""Distance-based clustering of LaserScan points for person detection."""

import math

import numpy as np


def laserscan_to_cartesian(ranges, angle_min, angle_increment, max_range,
                           min_range=0.0):
    """Convert LaserScan polar coordinates to Cartesian (x, y) points.

    Filters out invalid ranges (inf, nan, zero, outside [min_range, max_range]).

    Returns:
        np.ndarray of shape (N, 2) with [x, y] columns,
        np.ndarray of shape (N,) with original indices into the ranges array.
    """
    n = len(ranges)
    angles = angle_min + np.arange(n) * angle_increment
    ranges = np.asarray(ranges, dtype=np.float64)

    # Filter invalid readings
    valid = np.isfinite(ranges) & (ranges >= min_range) & (ranges <= max_range)
    angles = angles[valid]
    ranges = ranges[valid]
    indices = np.where(valid)[0]

    x = ranges * np.cos(angles)
    y = ranges * np.sin(angles)

    points = np.column_stack((x, y))
    return points, indices


def cluster_points(points, distance_threshold, circular=False):
    """Cluster ordered points by consecutive Euclidean distance.

    Points from a LaserScan are ordered by angle, so consecutive points
    that are close together likely belong to the same object.

    Args:
        points: np.ndarray of shape (N, 2).
        distance_threshold: Maximum distance between consecutive points
            to belong to the same cluster.
        circular: If True, check whether the last and first clusters should
            be merged (handles persons near the 0°/360° wrap-around of a
            full 360° LiDAR scan).

    Returns:
        List of np.ndarray, each of shape (M, 2) representing a cluster.
    """
    if len(points) == 0:
        return []

    points = np.asarray(points)
    # Vectorised: split wherever the gap between consecutive points exceeds
    # the threshold.
    gaps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    breaks = np.flatnonzero(gaps > distance_threshold) + 1
    clusters = np.split(points, breaks)

    # For full 360° scans: check if last cluster and first cluster belong to
    # the same object split by the angular wrap-around boundary.
    if circular and len(clusters) >= 2:
        last_pt = clusters[-1][-1]
        first_pt = clusters[0][0]
        if np.linalg.norm(last_pt - first_pt) <= distance_threshold:
            clusters[0] = np.vstack([clusters[-1], clusters[0]])
            clusters.pop()

    return clusters


def filter_person_clusters(clusters, min_size, max_size, min_width, max_width,
                           max_depth=None):
    """Filter clusters that match person-like characteristics.

    A person's torso at chest height is roughly arc-shaped: wide but
    shallow. The "width" is the arc length along the scan and the
    "depth" is the radial extent. Walls and large objects tend to have
    depth >= width, while a person has depth < width.

    Args:
        clusters: List of np.ndarray clusters from cluster_points().
        min_size: Minimum number of points in cluster.
        max_size: Maximum number of points in cluster.
        min_width: Minimum cluster width in meters.
        max_width: Maximum cluster width in meters.
        max_depth: Maximum radial depth of cluster in meters (None = no limit).

    Returns:
        List of np.ndarray centroids, shape (M, 2) each being [x, y].
    """
    centroids = []

    for cluster in clusters:
        n_points = len(cluster)
        if n_points < min_size or n_points > max_size:
            continue

        extent = np.ptp(cluster, axis=0)  # [dx, dy]
        width = math.sqrt(extent[0] ** 2 + extent[1] ** 2)

        if width < min_width or width > max_width:
            continue

        # Depth: radial extent (distance spread from the sensor)
        if max_depth is not None:
            distances = np.sqrt(cluster[:, 0] ** 2 + cluster[:, 1] ** 2)
            depth = distances.max() - distances.min()
            if depth > max_depth:
                continue

        centroid = np.mean(cluster, axis=0)
        centroids.append(centroid)

    return centroids


def extract_person_positions(ranges, angle_min, angle_increment,
                             max_range=10.0,
                             min_range=0.0,
                             cluster_distance_threshold=0.15,
                             min_cluster_size=3,
                             max_cluster_size=50,
                             min_cluster_width=0.1,
                             max_cluster_width=0.6,
                             max_cluster_depth=None,
                             return_clusters=False):
    """Full pipeline: LaserScan -> person position candidates.

    Args:
        ranges: List/array of range values from LaserScan.
        angle_min: Start angle of the scan (radians).
        angle_increment: Angular step between readings (radians).
        max_range: Maximum valid range to consider.
        cluster_distance_threshold: Max distance between consecutive points in a cluster.
        min_cluster_size: Minimum points per cluster.
        max_cluster_size: Maximum points per cluster.
        min_cluster_width: Minimum cluster width (meters).
        max_cluster_width: Maximum cluster width (meters).
        max_cluster_depth: Maximum radial depth (meters). None = no limit.
        return_clusters: If True, also return the filtered cluster point arrays.

    Returns:
        List of [x, y] np.ndarray centroids representing detected persons.
        If return_clusters is True, returns (centroids, person_clusters) where
        person_clusters is a list of np.ndarray (M, 2) for each person.
    """
    points, _ = laserscan_to_cartesian(ranges, angle_min, angle_increment, max_range,
                                       min_range=min_range)

    # Auto-detect full 360° scan (within ~11°) for wrap-around cluster merging
    total_angle = angle_increment * len(ranges)
    is_circular = abs(total_angle - 2 * math.pi) < 0.2

    clusters = cluster_points(points, cluster_distance_threshold, circular=is_circular)

    if not return_clusters:
        centroids = filter_person_clusters(
            clusters, min_cluster_size, max_cluster_size,
            min_cluster_width, max_cluster_width, max_cluster_depth
        )
        return centroids

    centroids = []
    person_clusters = []
    for cluster in clusters:
        n_points = len(cluster)
        if n_points < min_cluster_size or n_points > max_cluster_size:
            continue
        extent = np.ptp(cluster, axis=0)
        width = math.sqrt(extent[0] ** 2 + extent[1] ** 2)
        if width < min_cluster_width or width > max_cluster_width:
            continue
        if max_cluster_depth is not None:
            distances = np.sqrt(cluster[:, 0] ** 2 + cluster[:, 1] ** 2)
            depth = distances.max() - distances.min()
            if depth > max_cluster_depth:
                continue
        centroids.append(np.mean(cluster, axis=0))
        person_clusters.append(cluster)
    return centroids, person_clusters
