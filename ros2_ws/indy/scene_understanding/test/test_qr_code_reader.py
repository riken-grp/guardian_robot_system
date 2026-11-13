"""qr_code_reader_node: a candidate that cannot be decoded does not hide the others."""

import cv2
import numpy as np
import pytest
import rclpy

from scene_understanding.qr_code_reader_node import QRCodeReader


def qr(text, size=200):
    img = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


@pytest.fixture
def frame():
    f = np.full((480, 800, 3), 255, np.uint8)
    f[100:300, 80:280] = qr("dock-A")
    f[100:300, 480:680] = qr("room-12")
    return f


class FailingDecoder:
    """QRCodeDetector whose detectAndDecodeMulti raises (as with 'mode 14')."""

    def __init__(self, qcd, bad_index=None):
        self.qcd, self.bad_index = qcd, bad_index
        self.calls = 0

    def detectAndDecodeMulti(self, frame):
        raise cv2.error("mode 14 in function 'decodeSymbols'")

    def detectMulti(self, frame):
        return self.qcd.detectMulti(frame)

    def decodeMulti(self, frame, points):
        i, self.calls = self.calls, self.calls + 1
        if i == self.bad_index:
            raise cv2.error("mode 14 in function 'decodeSymbols'")
        return self.qcd.decodeMulti(frame, points)


@pytest.fixture
def node():
    rclpy.init()
    n = QRCodeReader()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def test_normal(node, frame):
    ok, info, points = node.detect_and_decode(frame)
    assert ok and sorted(info) == ["dock-A", "room-12"]
    assert len(points) == 2


def test_falls_back_to_one_by_one(node, frame):
    node.qcd = FailingDecoder(cv2.QRCodeDetector())
    ok, info, points = node.detect_and_decode(frame)
    assert ok and sorted(info) == ["dock-A", "room-12"]


def test_bad_candidate_does_not_hide_the_others(node, frame):
    node.qcd = FailingDecoder(cv2.QRCodeDetector(), bad_index=0)
    ok, info, points = node.detect_and_decode(frame)
    assert ok and len(info) == 2 == len(points)
    assert sorted(info) in (["", "dock-A"], ["", "room-12"])


def test_nothing(node):
    node.qcd = FailingDecoder(cv2.QRCodeDetector())
    ok, info, points = node.detect_and_decode(np.full((240, 320, 3), 255, np.uint8))
    assert not ok
