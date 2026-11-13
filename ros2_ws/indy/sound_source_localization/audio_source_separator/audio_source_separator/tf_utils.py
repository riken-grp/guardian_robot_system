"""Small TF helpers (no tf2_geometry_msgs dependency)."""

import numpy as np


def quaternion_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """Rotation matrix (3, 3) of a unit quaternion (x, y, z, w)."""
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    xx, yy, zz = x * x * s, y * y * s, z * z * s
    xy, xz, yz = x * y * s, x * z * s, y * z * s
    wx, wy, wz = w * x * s, w * y * s, w * z * s
    return np.array([
        [1.0 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1.0 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1.0 - (xx + yy)],
    ])


def transform_to_matrix(transform) -> tuple[np.ndarray, np.ndarray]:
    """(R, t) of a geometry_msgs/Transform (or TransformStamped)."""
    tf = getattr(transform, 'transform', transform)
    q = tf.rotation
    t = tf.translation
    return (quaternion_to_matrix(q.x, q.y, q.z, q.w),
            np.array([t.x, t.y, t.z], dtype=np.float64))


def transform_points(transform, points: np.ndarray) -> np.ndarray:
    """Apply a geometry_msgs/Transform(Stamped) to (N, 3) points."""
    rot, trans = transform_to_matrix(transform)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return pts @ rot.T + trans
