"""Self-contained Kalman filter tracker for person tracking.

State vector: [x, y, vx, vy]
Measurement vector: [x, y]
Uses greedy nearest-neighbor association.
"""

import math
import time

import numpy as np
from scipy.optimize import linear_sum_assignment


class KalmanFilter:
    """Linear Kalman filter with state [x, y, vx, vy] and measurement [x, y]."""

    def __init__(self, x, y, process_noise=0.5, measurement_noise=0.1):
        # State: [x, y, vx, vy]
        self.x = np.array([x, y, 0.0, 0.0], dtype=np.float64)

        # State covariance
        self.P = np.diag([1.0, 1.0, 10.0, 10.0])

        # Measurement matrix: we observe [x, y]
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=np.float64)

        # Measurement noise
        self.R = np.eye(2) * measurement_noise

        self._process_noise = process_noise
        self._measurement_noise = measurement_noise

    def predict(self, dt):
        """Predict the next state given elapsed time dt."""
        # State transition matrix
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=np.float64)

        # Process noise matrix
        q = self._process_noise
        dt2 = dt * dt
        dt3 = dt2 * dt / 2.0
        dt4 = dt2 * dt2 / 4.0
        Q = q * np.array([
            [dt4, 0, dt3, 0],
            [0, dt4, 0, dt3],
            [dt3, 0, dt2, 0],
            [0, dt3, 0, dt2],
        ], dtype=np.float64)

        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, z):
        """Update with measurement z = [x, y]."""
        z = np.asarray(z, dtype=np.float64)
        y = z - self.H @ self.x                     # Innovation
        S = self.H @ self.P @ self.H.T + self.R     # Innovation covariance (2x2)

        # Kalman gain via solve: K = P H^T S^{-1}
        # Equivalent: S K^T = H P  →  K = solve(S, H @ P).T
        K = np.linalg.solve(S, self.H @ self.P).T   # (4, 2)

        self.x = self.x + K @ y

        # Joseph form: guarantees symmetry and positive-definiteness of P
        I = np.eye(4)
        I_KH = I - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ self.R @ K.T

    @property
    def position(self):
        return self.x[0], self.x[1]

    @property
    def velocity(self):
        return self.x[2], self.x[3]


class TrackedPerson:
    """A single tracked person with Kalman filter state."""

    _next_id = 0

    def __init__(self, x, y, process_noise=0.5, measurement_noise=0.1,
                 timestamp: float | None = None):
        self.person_id = TrackedPerson._next_id
        TrackedPerson._next_id += 1

        self.kf = KalmanFilter(x, y, process_noise, measurement_noise)
        self.last_seen = timestamp if timestamp is not None else time.time()
        self.hits = 1

    def predict(self, dt):
        self.kf.predict(dt)

    def update(self, x, y, timestamp: float | None = None):
        self.kf.update([x, y])
        self.last_seen = timestamp if timestamp is not None else time.time()
        self.hits += 1

    @property
    def position(self):
        return self.kf.position

    @property
    def velocity(self):
        return self.kf.velocity

    @property
    def azimuth(self):
        x, y = self.position
        return math.atan2(y, x)

    @property
    def distance(self):
        x, y = self.position
        return math.sqrt(x * x + y * y)


class PersonTracker:
    """Multi-person tracker using greedy nearest-neighbor association."""

    def __init__(self, tracking_distance_threshold=1.0, person_timeout=2.0,
                 process_noise=0.5, measurement_noise=0.1):
        self.tracks: list[TrackedPerson] = []
        self.tracking_distance_threshold = tracking_distance_threshold
        self.person_timeout = person_timeout
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self._last_time = None

    def update(self, detections, timestamp: float | None = None):
        """Update tracker with new detections.

        Uses the Hungarian algorithm (optimal assignment) instead of greedy
        nearest-neighbor. Distance matrix is computed via numpy broadcasting.

        Args:
            detections: List of [x, y] positions (np.ndarray or list).
            timestamp: Optional external timestamp in seconds. When provided
                (e.g., from ROS message header), dt and timeout checks use
                this value instead of wall-clock time, enabling correct
                behaviour with rosbag playback and simulation.

        Returns:
            List of active TrackedPerson objects.
        """
        now = timestamp if timestamp is not None else time.time()
        if self._last_time is None:
            dt = 0.05  # Default ~20Hz on first call
        else:
            dt = now - self._last_time
        self._last_time = now

        # Clamp dt to avoid instability from large gaps
        dt = max(0.001, min(dt, 1.0))

        # Predict all existing tracks forward
        for track in self.tracks:
            track.predict(dt)

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()

        if self.tracks and detections:
            # Vectorised distance matrix via broadcasting
            track_pos = np.array([list(t.position) for t in self.tracks])  # (T, 2)
            det_pos = np.array([[float(d[0]), float(d[1])] for d in detections])  # (D, 2)
            diff = track_pos[:, np.newaxis, :] - det_pos[np.newaxis, :, :]  # (T, D, 2)
            dist_matrix = np.sqrt(np.sum(diff ** 2, axis=2))                # (T, D)

            # Hungarian algorithm: globally optimal one-to-one assignment
            row_ind, col_ind = linear_sum_assignment(dist_matrix)
            for i, j in zip(row_ind, col_ind):
                if dist_matrix[i, j] <= self.tracking_distance_threshold:
                    self.tracks[i].update(
                        detections[j][0], detections[j][1], timestamp=now
                    )
                    matched_tracks.add(i)
                    matched_detections.add(j)

        # Create new tracks for unmatched detections
        for j, det in enumerate(detections):
            if j not in matched_detections:
                self.tracks.append(TrackedPerson(
                    det[0], det[1],
                    self.process_noise, self.measurement_noise,
                    timestamp=now,
                ))

        # Remove stale tracks
        self.tracks = [
            t for t in self.tracks
            if (now - t.last_seen) < self.person_timeout
        ]

        return self.tracks
