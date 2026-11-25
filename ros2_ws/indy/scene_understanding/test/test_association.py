"""association_node: track / pose / face are joined by the frame stamp."""

import pytest
import rclpy
from rclpy.time import Time
from recognition_msgs.msg import Object, Objects, Person, Persons

from scene_understanding.association_node import AssociationNode

BOX = [100.0, 100.0, 50.0, 200.0]
FACE = [115.0, 105.0, 20.0, 20.0]


def stamp(sec):
    return Time(nanoseconds=int(sec * 1e9)).to_msg()


def tracked(sec, iid=7):
    m = Objects()
    m.header.stamp = stamp(sec)
    o = Object()
    o.class_id = 0
    o.instance_id = iid
    o.location = BOX
    m.objects = [o]
    return m


def poses(sec):
    m = Persons()
    m.header.stamp = stamp(sec)
    p = Person()
    p.body_location = BOX
    m.persons = [p]
    return m


def faces(sec):
    m = Persons()
    m.header.stamp = stamp(sec)
    p = Person()
    p.face_location = FACE
    m.persons = [p]
    return m


@pytest.fixture
def node():
    rclpy.init()
    n = AssociationNode()
    n.out = {"pose": [], "face": []}
    n.pub_poses.publish = lambda m: n.out["pose"].append(m)
    n.pub_faces.publish = lambda m: n.out["face"].append(m)
    yield n
    n.destroy_node()
    rclpy.shutdown()


def sec_of(m):
    return m.header.stamp.sec + m.header.stamp.nanosec * 1e-9


def test_same_frame_in_any_order(node):
    node.callback_face(faces(10.0))
    node.callback_pose(poses(10.0))
    assert node.out == {"pose": [], "face": []}  # waits for the track
    node.callback_track(tracked(10.0))
    assert [p.persons[0].instance_id for p in node.out["pose"]] == [7]
    assert [f.persons[0].instance_id for f in node.out["face"]] == [7]
    assert node.stats.out["pose"]["exact"] == node.stats.out["face"]["exact"] == 1


def test_waits_for_slower_track_without_timeout(node):
    for i in range(5):
        node.callback_pose(poses(10.0 + 0.1 * i))
    assert node.out["pose"] == []
    for i in range(5):
        node.callback_track(tracked(10.0 + 0.1 * i, iid=i))
    assert [p.persons[0].instance_id for p in node.out["pose"]] == list(range(5))


def test_frame_skipped_by_the_tracker_uses_the_neighbor(node):
    node.callback_track(tracked(10.0))
    node.callback_pose(poses(10.0))
    node.callback_pose(poses(10.1))  # the tracker skipped 10.1
    assert len(node.out["pose"]) == 1  # 10.1 still waits
    node.callback_track(tracked(10.2))
    assert [round(sec_of(p), 1) for p in node.out["pose"]] == [10.0, 10.1]
    assert node.stats.out["pose"] == {"exact": 1, "near": 1, "drop": 0}


def test_no_track_within_slop_is_dropped(node):
    node.callback_track(tracked(10.0))
    node.callback_pose(poses(11.0))
    node.callback_track(tracked(12.0))  # passed 11.0, nothing within 0.2 s
    assert node.out["pose"] == []
    assert node.stats.out["pose"]["drop"] == 1


def test_timeout_when_the_track_stops(node):
    node.callback_track(tracked(10.0))
    node.callback_pose(poses(10.1))
    node._process()
    assert node.out["pose"] == []
    node.pending_poses[0].arrival -= 2.0  # match_timeout (1 s) elapsed
    node._process()
    assert len(node.out["pose"]) == 1  # nearest within slop


def test_face_of_a_dropped_pose_does_not_wait(node):
    node.callback_track(tracked(10.0))
    node.callback_pose(poses(10.0))
    node.callback_pose(poses(11.0))
    node.callback_track(tracked(12.0))  # pose 11.0 dropped
    node.callback_face(faces(11.0))
    assert node.stats.out["face"]["drop"] == 1
    assert node.pending_faces == type(node.pending_faces)()


def test_buffers_are_pruned(node):
    for i in range(100):
        t = 10.0 + 0.1 * i
        node.callback_track(tracked(t))
        node.callback_pose(poses(t))
    assert len(node.out["pose"]) == 100
    assert len(node.tracks.items) <= 51  # buffer_duration 5 s
