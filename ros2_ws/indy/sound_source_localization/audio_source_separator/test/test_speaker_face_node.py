"""SpeakerFaceNode: speech segment + face image of the speaker."""

import time

import numpy as np
import pytest

rclpy = pytest.importorskip('rclpy')
cv2 = pytest.importorskip('cv2')
pytest.importorskip('recognition_msgs.msg')
pytest.importorskip('ssl_msgs.msg')

from recognition_msgs.msg import Person, Persons  # noqa: E402
from sensor_msgs.msg import CompressedImage  # noqa: E402
from ssl_msgs.msg import SpeechSegment  # noqa: E402

from audio_source_separator.speaker_face_node import (  # noqa: E402
    SpeakerFaceNode, crop_box, face_score)

S = 1_000_000_000
T0 = 1000 * S          # stamp of the first frame


def _stamp(msg, t_ns):
    msg.header.stamp.sec = t_ns // S
    msg.header.stamp.nanosec = t_ns % S


def _image(t_ns, color=(0, 0, 255)):
    img = np.zeros((480, 640, 3), np.uint8)
    img[100:200, 300:400] = color          # the "face" area
    ok, buf = cv2.imencode('.jpg', img)
    assert ok
    m = CompressedImage()
    _stamp(m, t_ns)
    m.header.frame_id = 'cam'
    m.format = 'jpeg'
    m.data = buf.tobytes()
    return m


def _faces(t_ns, *faces):
    m = Persons()
    _stamp(m, t_ns)
    for iid, loc, ori in faces:
        p = Person()
        p.instance_id = iid
        p.face_location = [float(v) for v in loc]
        p.face_orientation = [float(v) for v in ori]
        m.persons.append(p)
    return m


def _segment(pid, start_ns, end_ns):
    m = SpeechSegment()
    m.person_id = pid
    m.sample_rate = 16000
    m.duration = (end_ns - start_ns) / S
    m.audio_data = [0.0] * 160
    m.speech_start_ns = start_ns
    m.speech_end_ns = end_ns
    return m


@pytest.fixture
def node():
    rclpy.init()
    n = SpeakerFaceNode()
    out = []
    n._pub.publish = out.append
    yield n, out
    n.destroy_node()
    rclpy.shutdown()


def test_helpers():
    assert crop_box([300, 100, 100, 100], 640, 480, 0.4) == (260, 60, 440, 240)
    assert crop_box([600, 450, 100, 100], 640, 480, 0.4) == (560, 410, 640, 480)
    assert crop_box([0, 0, 0, 10], 640, 480, 0.4) is None
    # frontal beats turned at the same size; size counts
    assert face_score([0, 0, 50, 50], [0, 0, 0]) > face_score([0, 0, 50, 50], [60, 0, 0])
    assert face_score([0, 0, 80, 80], [10, 0, 0]) > face_score([0, 0, 50, 50], [0, 0, 0])


def test_best_face_of_the_speaker(node):
    n, out = node
    for k in range(5):
        n._on_image(_image(T0 + k * S // 10))
    n._on_faces(_faces(T0, (7, [300, 100, 60, 60], [40, 0, 0]),
                           (8, [100, 100, 100, 100], [0, 0, 0])))
    n._on_faces(_faces(T0 + S // 10, (7, [300, 100, 100, 100], [5, 0, 0])))
    n._on_faces(_faces(T0 + 2 * S // 10, (7, [300, 100, 100, 100], [50, 10, 0])))
    n._on_speech(_segment(7, T0, T0 + 3 * S // 10))
    n._on_timer()
    assert out == []                       # faces up to end + post_margin not yet in
    n._on_faces(_faces(T0 + 6 * S // 10))  # (empty) faces newer than the end
    n._on_timer()
    assert len(out) == 1
    m = out[0]
    assert m.face_found and m.segment.person_id == 7
    assert m.face_stamp_ns == T0 + S // 10                  # the large frontal one
    assert list(m.face_location) == [300.0, 100.0, 100.0, 100.0]
    assert m.face_image.header.stamp.nanosec == S // 10
    img = cv2.imdecode(np.frombuffer(bytes(m.face_image.data), np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (180, 180)                       # 100 px + 40 % per side
    assert img[90, 90, 2] > 200 and img[5, 5, 2] < 50        # red face, black margin


def test_no_face_published_after_max_wait(node):
    n, out = node
    n._max_wait = 0.05
    n._on_image(_image(T0))
    n._on_faces(_faces(T0, (8, [300, 100, 100, 100], [0, 0, 0])))   # someone else
    n._on_speech(_segment(7, T0, T0 + S))
    n._on_timer()
    assert out == []
    time.sleep(0.06)
    n._on_timer()
    assert len(out) == 1 and not out[0].face_found
    assert len(out[0].face_image.data) == 0 and out[0].segment.person_id == 7


def test_faces_outside_the_utterance_or_without_image_are_not_used(node):
    n, out = node
    n._on_image(_image(T0))
    n._on_faces(_faces(T0, (7, [300, 100, 100, 100], [0, 0, 0])))            # 2 s before
    n._on_faces(_faces(T0 + 2 * S + S // 2, (7, [300, 100, 100, 100], [0, 0, 0])))  # no image
    n._on_faces(_faces(T0 + 4 * S))
    n._on_speech(_segment(7, T0 + 2 * S, T0 + 3 * S))
    n._on_timer()
    assert len(out) == 1 and not out[0].face_found


def test_buffers_are_bounded(node):
    n, _ = node
    for k in range(100):                   # 10 s of images at 10 Hz
        n._on_image(_image(T0 + k * S // 10))
    assert len(n._imgs) <= 31 and n._img_stamps == sorted(n._img_stamps)
    for k in range(0, 200, 5):             # 20 s of faces
        n._on_image(_image(T0 + k * S // 10))
        n._on_faces(_faces(T0 + k * S // 10, (7, [300, 100, 100, 100], [0, 0, 0])))
    assert n._faces[0].stamp_ns >= n._latest_face_ns - 15 * S
