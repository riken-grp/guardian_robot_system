import rclpy
import pytest
from action_recognition.hand_waving_node import WavingHandNode


def test_hand_waving_node_initialization():
    rclpy.init()
    try:
        from action_recognition.hand_waving_node import WavingHandRecognizer
        node = WavingHandNode()
        node.destroy_node()
    finally:
        rclpy.shutdown()


from types import SimpleNamespace

import numpy as np

from action_recognition.base_recognition_node import normalize_keypoints
from action_recognition.hand_waving_node import WavingHandRecognizer


class _FakeModel:
    def __init__(self):
        self.features = None

    def predict(self, features):
        self.features = features
        return np.ones(len(features), dtype=int)


def _person(instance_id, value):
    kps = np.full((17, 3), float(value))
    kps[:, 2] = 1.0 + np.arange(17)  # valid depth
    return SimpleNamespace(
        instance_id=instance_id,
        pose_sensor=SimpleNamespace(keypoints=kps.reshape(-1).tolist()),
    )


def _frame(*ps):
    return SimpleNamespace(persons=list(ps))


def test_normalize_ignores_invalid_keypoints():
    kps = np.zeros((17, 3))
    kps[:2] = [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]
    out = normalize_keypoints(kps.reshape(-1)).reshape(-1, 3)
    assert out.shape == (17, 3)
    np.testing.assert_allclose(out[0], [-1, -1, -1])
    np.testing.assert_allclose(out[1], [1, 1, 1])
    assert np.all(out[2:] == 0)
    assert np.all(normalize_keypoints(np.zeros(51)) == 0)


def test_waving_buffer_order_and_cleanup():
    model = _FakeModel()
    rec = WavingHandRecognizer(model=model, seq_len=3)
    assert rec(_frame(_person(1, 0), _person(-1, 0))) == [0, 0]
    assert rec(_frame(_person(1, 1), _person(-1, 0))) == [0, 0]
    assert rec(_frame(_person(1, 2), _person(2, 0))) == [1, 0]
    assert set(rec.buffer) == {1, 2}  # -1 is never buffered
    # feature = normalized frames concatenated, oldest first
    assert model.features.shape == (1, 3 * 51)
    expected = np.concatenate(
        [normalize_keypoints(np.asarray(_person(1, v).pose_sensor.keypoints)) for v in range(3)]
    )
    np.testing.assert_allclose(model.features[0], expected)
    # id 1 disappears -> its buffer is dropped
    rec(_frame(_person(2, 0)))
    assert set(rec.buffer) == {2}
    assert rec(_frame()) == []
    assert rec.buffer == {}


def test_waving_ring_buffer_wraps():
    model = _FakeModel()
    rec = WavingHandRecognizer(model=model, seq_len=2)
    frames = []
    for i in range(5):
        kps = np.zeros((17, 3))
        kps[0] = [0.0, 0.0, 1.0]
        kps[1] = [float(i), 0.0, 1.0]
        frames.append(kps.reshape(-1))
        rec(_frame(SimpleNamespace(instance_id=1, pose_sensor=SimpleNamespace(keypoints=frames[-1].tolist()))))
    expected = np.concatenate([normalize_keypoints(f) for f in frames[-2:]])
    np.testing.assert_allclose(model.features[0], expected)
