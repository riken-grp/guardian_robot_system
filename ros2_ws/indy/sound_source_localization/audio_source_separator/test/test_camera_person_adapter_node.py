"""CameraPersonAdapterNode: camera persons -> TrackedPersonArray (merged with LiDAR outside the FOV)."""

import math

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('recognition_msgs.msg')
pytest.importorskip('ssl_msgs.msg')
pytest.importorskip('tf2_ros')

from geometry_msgs.msg import TransformStamped  # noqa: E402
from recognition_msgs.msg import Person, Persons  # noqa: E402
from ssl_msgs.msg import TrackedPerson, TrackedPersonArray  # noqa: E402

from audio_source_separator.camera_person_adapter_node import CameraPersonAdapterNode  # noqa: E402


def _tf(parent, child, xyz, q):
    t = TransformStamped()
    t.header.frame_id = parent
    t.child_frame_id = child
    t.transform.translation.x, t.transform.translation.y, \
        t.transform.translation.z = xyz
    (t.transform.rotation.x, t.transform.rotation.y,
     t.transform.rotation.z, t.transform.rotation.w) = q
    return t


@pytest.fixture(params=['merge'])
def node(request):
    rclpy.init()
    n = _init([
        rclpy.parameter.Parameter('output_frame', rclpy.Parameter.Type.STRING, 'base'),
        rclpy.parameter.Parameter('mode', rclpy.Parameter.Type.STRING, request.param),
    ])
    out = []
    n._pub.publish = out.append
    yield n, out
    n.destroy_node()
    rclpy.shutdown()


def _init(overrides):
    # parameter_overrides must be given at construction: wrap Node.__init__
    orig = rclpy.node.Node.__init__

    def init(self, name, **kw):
        orig(self, name, parameter_overrides=overrides, **kw)

    rclpy.node.Node.__init__ = init
    try:
        n = CameraPersonAdapterNode()
    finally:
        rclpy.node.Node.__init__ = orig
    # camera optical frame 0.1 m ahead, 1.0 m above base
    # (optical: x right, y down, z forward  ->  q = (-0.5, 0.5, -0.5, 0.5))
    n._tf_buffer.set_transform_static(
        _tf('base', 'cam', (0.1, 0.0, 1.0), (-0.5, 0.5, -0.5, 0.5)), 'test')
    n._tf_buffer.set_transform_static(
        _tf('base', 'lidar', (0.0, 0.0, 0.3), (0.0, 0.0, 0.0, 1.0)), 'test')
    return n


def _camera(n, persons):
    msg = Persons()
    msg.header.frame_id = 'cam'
    msg.header.stamp = n.get_clock().now().to_msg()
    for iid, xyz in persons:
        p = Person()
        p.instance_id = iid
        p.body_location_sensor = list(xyz)
        msg.persons.append(p)
    n._on_persons(msg)


def _lidar(n, persons):
    msg = TrackedPersonArray()
    msg.header.frame_id = 'lidar'
    msg.header.stamp = n.get_clock().now().to_msg()
    for pid, x, y in persons:
        p = TrackedPerson()
        p.person_id, p.x, p.y = pid, x, y
        msg.persons.append(p)
    n._on_lidar(msg)


def _deg(rad):
    return math.degrees(rad)


@pytest.mark.parametrize('node', ['camera'], indirect=True)
def test_camera_mode(node):
    n, out = node
    # 2 m ahead of the camera, 1 m to its left (optical x is right)
    # plus ignored entries: no tracking ID, behind the camera
    _camera(n, [(124117, (-1.0, 0.0, 2.0)), (-1, (0.0, 0.0, 2.0)), (7, (0.0, 0.0, -1.0))])
    assert len(out) == 1  # published on every camera message
    msg = out[0]
    assert msg.header.frame_id == 'base'
    (p,) = msg.persons
    assert p.person_id == 124117
    assert p.x == pytest.approx(2.1, abs=1e-3) and p.y == pytest.approx(1.0, abs=1e-3)
    assert _deg(p.azimuth) == pytest.approx(_deg(math.atan2(1.0, 2.1)), abs=0.1)
    assert p.distance == pytest.approx(math.hypot(2.1, 1.0), abs=1e-3)


def test_merge(node):
    n, out = node
    _camera(n, [(124117, (0.0, 0.0, 2.0))])  # straight ahead, x = 2.1 m
    assert out == []  # merge publishes on LiDAR messages
    _lidar(n, [
        (1, 2.15, 0.1),       # same person as the camera one -> dropped
        (2, 0.0, 1.7),        # 90 deg, outside the FOV -> kept (+1e9)
        (3, 1.5, 0.5),        # inside the FOV, no camera person -> dropped (camera trusted)
        (4, 0.09, -0.4),      # -77 deg, 0.41 m: robot part / dock -> dropped
    ])
    (msg,) = out
    ids = {p.person_id: p for p in msg.persons}
    assert set(ids) == {124117, 1000000002}
    assert _deg(ids[1000000002].azimuth) == pytest.approx(90.0, abs=0.1)
    assert ids[1000000002].distance == pytest.approx(1.7, abs=1e-3)


def test_merge_without_camera_uses_lidar_in_fov(node):
    n, out = node
    # no camera message (camera stream stopped)
    _lidar(n, [(3, 1.5, 0.5), (4, 0.09, -0.4)])
    (msg,) = out
    assert [p.person_id for p in msg.persons] == [1000000003]


def test_merge_camera_timeout(node):
    n, out = node
    _camera(n, [(124117, (0.0, 0.0, 2.0))])
    n._cam_recv -= 2.0  # the last camera message is 2 s old (camera_timeout 1 s)
    _lidar(n, [(3, 1.5, 0.5)])
    (msg,) = out
    assert [p.person_id for p in msg.persons] == [1000000003]
