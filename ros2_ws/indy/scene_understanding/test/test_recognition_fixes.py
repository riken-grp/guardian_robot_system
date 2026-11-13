import sys
import types

import numpy as np
import pytest

# heavy / GPU-only dependencies are not needed for the pure logic tested here
for _name in ("face_recognition", "zstandard"):
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = types.ModuleType(_name)

from scene_understanding.aruco_reader_node import rvec_to_quaternion  # noqa: E402
from scene_understanding.association_node import AssociationNode  # noqa: E402


def test_face_check_continues_after_invalid_closest_pair():
    # body 0 is closest to face 0 but the face is outside of it; body 1
    # contains face 0, body 0 contains face 1.  The old code stopped at the
    # first invalid pair and returned no match at all.
    pbbs = [[100, 100, 50, 200], [140, 90, 100, 200]]
    fbbs = [[150, 100, 20, 20], [105, 110, 20, 20]]
    node = types.SimpleNamespace(is_face_in_body=lambda b, f: AssociationNode.is_face_in_body(None, b, f))
    matches = AssociationNode.face_check(node, pbbs, fbbs)
    assert matches == {0: 1, 1: 0}


def test_face_check_no_valid_pair():
    node = types.SimpleNamespace(is_face_in_body=lambda b, f: False)
    assert AssociationNode.face_check(node, [[0, 0, 10, 10]], [[0, 0, 5, 5]]) == {}


@pytest.mark.parametrize(
    "rvec",
    [[0, 0, 0], [0.1, -0.2, 0.3], [np.pi, 0, 0], [0, np.pi - 1e-9, 0], [2.0, 1.0, -1.5]],
)
def test_rvec_to_quaternion_matches_rotation_matrix(rvec):
    import cv2

    rvec = np.asarray(rvec, float)
    R, _ = cv2.Rodrigues(rvec)
    x, y, z, w = rvec_to_quaternion(rvec)
    assert np.isclose(x * x + y * y + z * z + w * w, 1.0)
    Rq = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    np.testing.assert_allclose(Rq, R, atol=1e-7)


def test_person_builder_uses_conf_column_and_threshold():
    from std_msgs.msg import Header

    from scene_understanding.message_builders import PersonMessageBuilder

    det = np.array([[10, 10, 50, 100, 0.9, 0, 0, 0, 2.0, 1, 1, 2.0]])
    pose = np.zeros((1, 17, 9))
    pose[0, :, 0:2] = 30
    pose[0, :, 5] = 7.0  # world X (used to be read as the confidence)
    pose[0, :, 8] = 0.1  # low confidence -> nothing drawn
    img = np.zeros((120, 80, 3), np.uint8)
    b = PersonMessageBuilder()
    msg, extra, markers, vis = b.build_from_tracklets(Header(), det, pose, img, True)
    assert extra is None and len(msg.persons) == 1
    assert msg.persons[0].pose.dim == 2 and msg.persons[0].pose_sensor.dim == 3
    assert np.allclose(msg.persons[0].pose.confidences, 0.1)
    assert vis is not None and not np.shares_memory(vis, img)
    # only the bbox / label are drawn, no keypoints (all below threshold)
    pose[0, :, 8] = 0.9
    _, _, _, vis2 = b.build_from_tracklets(Header(), det, pose, img, True)
    assert (vis2 != vis).any()
    _, _, _, vis3 = b.build_from_tracklets(Header(), det, pose, img, False)
    assert vis3 is None


def test_object_builder_empty():
    from std_msgs.msg import Header

    from scene_understanding.message_builders import ObjectMessageBuilder

    h = Header()
    h.frame_id = "cam"
    msg, extra, _, vis = ObjectMessageBuilder({0: "person"}).build_from_tracklets(
        h, np.zeros((0, 13)), None, False
    )
    assert msg.header.frame_id == "cam" and len(msg.objects) == 0 and vis is None
