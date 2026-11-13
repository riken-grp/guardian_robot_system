"""SpeakerIdNode compares speech and persons in a common (base) frame."""

import math

import pytest

rclpy = pytest.importorskip('rclpy')
pytest.importorskip('recognition_msgs.msg')
pytest.importorskip('ssl_msgs.msg')
pytest.importorskip('tf2_ros')

from geometry_msgs.msg import TransformStamped  # noqa: E402
from recognition_msgs.msg import Person, Persons  # noqa: E402
from ssl_msgs.msg import SpeechSegment  # noqa: E402

from audio_source_separator.speaker_id_node import SpeakerIdNode  # noqa: E402


def _tf(parent, child, xyz, q):
    t = TransformStamped()
    t.header.frame_id = parent
    t.child_frame_id = child
    t.transform.translation.x, t.transform.translation.y, \
        t.transform.translation.z = xyz
    (t.transform.rotation.x, t.transform.rotation.y,
     t.transform.rotation.z, t.transform.rotation.w) = q
    return t


@pytest.fixture
def node():
    rclpy.init()
    n = SpeakerIdNode()
    n.set_parameters([rclpy.parameter.Parameter(
        'base_frame', rclpy.Parameter.Type.STRING, 'base')])
    # mic array 0.5 m above base; camera optical frame at 1.0 m height
    # (optical: x right, y down, z forward  ->  q = (-0.5, 0.5, -0.5, 0.5))
    n._tf_buffer.set_transform_static(
        _tf('base', 'mic', (0.0, 0.0, 0.5), (0.0, 0.0, 0.0, 1.0)), 'test')
    n._tf_buffer.set_transform_static(
        _tf('base', 'cam', (0.1, 0.0, 1.0), (-0.5, 0.5, -0.5, 0.5)), 'test')
    out = []
    n.pub_speech.publish = out.append
    yield n, out
    n.destroy_node()
    rclpy.shutdown()


def _person(iid, xyz):
    p = Person()
    p.instance_id = iid
    p.body_location_sensor = list(xyz)
    return p


def test_match_in_base_frame(node):
    n, out = node
    persons = Persons()
    persons.header.frame_id = 'cam'
    # Person A: 2 m ahead, 1 m to the LEFT of the camera
    #   (optical x = right -> -1.0, y = down, z = forward 2.0)
    # Person B: 2 m ahead, 1 m to the RIGHT
    persons.persons = [_person(10, (-1.0, 0.3, 2.0)),
                       _person(20, (1.0, 0.3, 2.0))]
    n._on_persons(persons)

    seg = SpeechSegment()
    seg.header.frame_id = 'mic'
    seg.person_id = 1
    # Speaker to the LEFT in the mic frame (x forward, y left)
    seg.azimuth = math.atan2(1.0, 2.1)
    seg.distance = math.hypot(2.1, 1.0)
    n._on_speech(seg)
    assert out[-1].person_id == 10

    seg2 = SpeechSegment()
    seg2.header.frame_id = 'mic'
    seg2.person_id = 2
    seg2.azimuth = -math.atan2(1.0, 2.1)
    seg2.distance = math.hypot(2.1, 1.0)
    n._on_speech(seg2)
    assert out[-1].person_id == 20


def test_missing_tf_keeps_id(node):
    n, out = node
    persons = Persons()
    persons.header.frame_id = 'unknown_cam'
    persons.persons = [_person(10, (0.0, 0.0, 2.0))]
    n._on_persons(persons)
    seg = SpeechSegment()
    seg.header.frame_id = 'mic'
    seg.person_id = 3
    seg.distance = 2.0
    n._on_speech(seg)
    assert out[-1].person_id == 3
