import numpy as np
from sensor_msgs.msg import CameraInfo

from scene_understanding.mapper import Sensor3DMapper

W, H = 640, 480
FX = FY = 500.0
CX, CY = 320.0, 240.0


def make_cinfo():
    c = CameraInfo()
    c.width, c.height = W, H
    c.k = [FX, 0.0, CX, 0.0, FY, CY, 0.0, 0.0, 1.0]
    return c


def make_mapper(translation=None):
    m = Sensor3DMapper(tf_buffer=None, world_frame_id="map")
    if translation is not None:
        m.matrix_R_T = m.translation_matrix(translation)
    return m


def test_bbox_depth_robust_to_holes_and_background():
    depth = np.full((H, W), 4000, np.uint16)  # background 4 m
    depth[200:300, 300:400] = 2000  # object 2 m
    depth[245:255, 345:355] = 0  # hole at the bbox center
    m = make_mapper(translation=[1.0, 2.0, 3.0])
    dets = np.array([[300, 200, 100, 100, 1, 0.9, 0]], float)  # x, y, w, h, id, conf, cls

    out = m.get_3d_value(dets, depth, make_cinfo())

    sensor, world = out[0, 7:10], out[0, 10:13]
    u, v = 350.0, 250.0
    np.testing.assert_allclose(sensor, [(u - CX) / FX * 2, (v - CY) / FY * 2, 2.0])
    np.testing.assert_allclose(world, sensor + [1.0, 2.0, 3.0])


def test_invalid_depth_gives_zero_global_not_camera_origin():
    depth = np.zeros((H, W), np.uint16)
    m = make_mapper(translation=[1.0, 2.0, 3.0])
    dets = np.array([[300, 200, 100, 100, 1, 0.9, 0]], float)

    out = m.get_3d_value(dets, depth, make_cinfo())

    np.testing.assert_array_equal(out[0, 7:13], 0.0)


def test_out_of_image_points_do_not_wrap():
    depth = np.zeros((H, W), np.uint16)
    depth[11, 0:5] = 1500  # would be read by a row-wrapping index of (W+2, 10)
    m = make_mapper()
    pts, flags = m.get_3d(np.array([[W + 2, 10], [-3, 10]], float), depth, make_cinfo(), window=0)
    assert not flags.any()
    np.testing.assert_array_equal(pts, 0.0)


def test_float_depth_in_meters():
    depth = np.full((H, W), 1.5, np.float32)
    depth[0, 0] = np.nan
    pts, flags = make_mapper().get_3d(np.array([[CX, CY]]), depth, make_cinfo())
    assert flags.all()
    np.testing.assert_allclose(pts[0], [0, 0, 1.5])


def test_person_body_from_torso_and_low_conf_keypoints_ignored():
    depth = np.full((H, W), 5000, np.uint16)  # background 5 m
    depth[100:400, 250:390] = 2500  # person 2.5 m
    m = make_mapper(translation=[0.0, 0.0, 1.0])
    dets = np.array([[200, 100, 240, 300, 0.9, 0]], float)  # wide bbox, x, y, w, h
    poses = np.zeros((1, 17, 3))
    for k, (x, y) in {5: (280, 150), 6: (360, 150), 11: (290, 300), 12: (350, 300)}.items():
        poses[0, k] = (x, y, 0.9)
    poses[0, 9] = (100, 100, 0.2)  # low confidence wrist on background
    # keypoint 0 stays (0, 0, 0): undetected

    dets3d, poses3d = m.get_3d_person(dets, poses, depth, make_cinfo())

    assert poses3d.shape == (1, 17, 9)
    np.testing.assert_allclose(poses3d[0, [5, 6, 11, 12], 4], 2.5)
    np.testing.assert_array_equal(poses3d[0, [0, 9], 2:8], 0.0)
    body = dets3d[0, 6:9]
    np.testing.assert_allclose(body, [((320 - CX) / FX) * 2.5, ((225 - CY) / FY) * 2.5, 2.5])
    np.testing.assert_allclose(dets3d[0, 9:12], body + [0, 0, 1.0])


def test_person_fallback_to_bbox_and_empty():
    depth = np.full((H, W), 3000, np.uint16)
    m = make_mapper()
    dets = np.array([[300, 200, 40, 80, 0.9, 0]], float)
    dets3d, _ = m.get_3d_person(dets, np.zeros((1, 17, 3)), depth, make_cinfo())
    assert dets3d[0, 8] == 3.0

    dets3d, poses3d = m.get_3d_person(np.zeros((0, 6)), np.zeros((0, 17, 3)), depth, make_cinfo())
    assert dets3d.shape == (0, 12) and poses3d.shape == (0, 17, 9)


def _naive_window_median(depth_m, u, v, window):
    patch = depth_m[max(v - window, 0) : v + window + 1, max(u - window, 0) : u + window + 1]
    vals = patch[patch > 0]
    return np.median(vals) if len(vals) else 0.0


def test_vectorized_window_median_matches_naive_incl_borders():
    rng = np.random.default_rng(0)
    depth = rng.integers(500, 6000, size=(H, W)).astype(np.uint16)
    depth[rng.random((H, W)) < 0.4] = 0  # many holes
    depth[100:110, 100:110] = 0  # a window without any depth
    pts = np.array(
        [[0, 0], [W - 1, H - 1], [1, H - 2], [105, 105], [320.7, 240.2], [W - 2, 3]] * 3,
        float,
    )
    pts[6:] += rng.uniform(0, 50, size=(len(pts) - 6, 2))
    pts = np.clip(pts, 0, [W - 1, H - 1])  # all inside the image
    m = make_mapper()
    out, flags = m.get_3d(pts, depth, make_cinfo())
    depth_m = depth.astype(np.float64) / 1000.0
    for (x, y), z, f in zip(pts, out[:, 2], flags):
        ref = _naive_window_median(depth_m, int(np.floor(x)), int(np.floor(y)), 3)
        assert f == (ref > 0)
        np.testing.assert_allclose(z, ref)


def test_get_3d_does_not_modify_or_copy_input():
    depth = np.full((H, W), 2000, np.uint16)
    before = depth.copy()
    make_mapper().get_3d_value(np.array([[300, 200, 100, 100, 1, 0.9, 0]], float), depth, make_cinfo())
    np.testing.assert_array_equal(depth, before)


class _FakeTransform:
    def __init__(self, x):
        from geometry_msgs.msg import TransformStamped

        self.msg = TransformStamped()
        self.msg.transform.translation.x = x
        self.msg.transform.rotation.w = 1.0


class _FakeBuffer:
    def __init__(self):
        self.ok = True
        self.calls = []

    def lookup_transform(self, target, source, time, *args, **kwargs):
        from tf2_ros import TransformException

        # non-blocking: no timeout must be passed
        assert not args and "timeout" not in kwargs
        self.calls.append(time)
        if not self.ok:
            raise TransformException("no tf")
        return _FakeTransform(1.5).msg


def test_update_tf_non_blocking_and_keeps_last_transform():
    buf = _FakeBuffer()
    m = Sensor3DMapper(tf_buffer=buf, world_frame_id="map")
    assert m.update_tf("camera")
    np.testing.assert_allclose(m.matrix_R_T[:3, 3], [1.5, 0, 0])
    buf.ok = False
    buf.calls.clear()
    assert m.update_tf("camera")  # falls back to the last successful transform
    assert len(buf.calls) == 2  # stamp, then latest
    np.testing.assert_allclose(m.matrix_R_T[:3, 3], [1.5, 0, 0])

    m2 = Sensor3DMapper(tf_buffer=buf, world_frame_id="map")
    assert not m2.update_tf("camera")
    assert m2.matrix_R_T is None


def test_robot_location_without_tf_is_finite():
    loc = make_mapper().get_robot_location(make_cinfo())
    assert np.all(np.isfinite(loc))
