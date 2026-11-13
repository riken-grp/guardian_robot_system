"""Tests for the vectorised LaserScan clustering."""

import numpy as np

from lidar_person_tracker.clustering import cluster_points


def _reference(points, thr, circular=False):
    clusters, cur = [], [0]
    for i in range(1, len(points)):
        if np.linalg.norm(points[i] - points[i - 1]) <= thr:
            cur.append(i)
        else:
            clusters.append(points[cur])
            cur = [i]
    clusters.append(points[cur])
    if circular and len(clusters) >= 2:
        if np.linalg.norm(clusters[-1][-1] - clusters[0][0]) <= thr:
            clusters[0] = np.vstack([clusters[-1], clusters[0]])
            clusters.pop()
    return clusters


def test_matches_reference():
    rng = np.random.default_rng(0)
    for circular in (False, True):
        for _ in range(20):
            pts = np.cumsum(rng.uniform(-0.2, 0.2, size=(200, 2)), axis=0)
            got = cluster_points(pts, 0.15, circular=circular)
            ref = _reference(pts, 0.15, circular=circular)
            assert len(got) == len(ref)
            for g, r in zip(got, ref):
                np.testing.assert_array_equal(g, r)


def test_edge_cases():
    assert cluster_points(np.zeros((0, 2)), 0.1) == []
    one = cluster_points(np.array([[1.0, 2.0]]), 0.1)
    assert len(one) == 1 and one[0].shape == (1, 2)
