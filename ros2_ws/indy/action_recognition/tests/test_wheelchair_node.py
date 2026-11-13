import rclpy
import pytest
from action_recognition.wheelchair_node import WheelChairNode


def test_wheelchair_node_initialization():
    rclpy.init()
    try:
        node = WheelChairNode()
        node.destroy_node()
    finally:
        rclpy.shutdown()

from types import SimpleNamespace

import numpy as np

from action_recognition.wheelchair_node import WheelChairRecognizer


class _FakeModel:
    def predict(self, features):
        return np.ones(len(features), dtype=int)


def test_wheelchair_skips_persons_without_keypoints():
    rec = WheelChairRecognizer(model=_FakeModel())
    kps = np.ones(51).tolist()
    ps = SimpleNamespace(
        persons=[
            SimpleNamespace(pose_sensor=SimpleNamespace(keypoints=kps)),
            SimpleNamespace(pose_sensor=SimpleNamespace(keypoints=[])),
        ]
    )
    assert [int(r) for r in rec(ps)] == [1, 0]
