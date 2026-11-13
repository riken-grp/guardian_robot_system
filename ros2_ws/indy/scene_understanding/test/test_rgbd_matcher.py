"""Color / depth matching by stamp (replaces ApproximateTimeSynchronizer)."""

import struct

import cv2
import numpy as np
import pytest
import rclpy
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage

from scene_understanding.image_processing_node import ImageProcessingNode
from scene_understanding.rgbd_matcher import RgbdMatcher

MS = 1_000_000  # ns


def stream(matcher, n=150, fps=15.0, lag=0.0, depth_offset_ms=0, start=10.0):
    """Camera at ``fps``; depth arrives ``lag`` s after color (arrival order)."""
    events = []
    for i in range(n):
        t = start + i / fps
        events.append((t, 0, int(t * 1e9), f"c{i}"))
        events.append((t + lag, 1, int(t * 1e9) + depth_offset_ms * MS, f"d{i}"))
    pairs = []
    for arrival, kind, stamp, name in sorted(events):
        add = matcher.add_color if kind == 0 else matcher.add_depth
        pair = add(stamp, name, arrival)
        if pair:
            pairs.append(pair)
    return pairs


@pytest.mark.parametrize("lag", [0.0, 0.3, 0.6, 1.5])
def test_depth_lag(lag):
    # ApproximateTimeSynchronizer(queue 5) produced 5/150 pairs at lag 0.6 s
    m = RgbdMatcher(slop_sec=0.1, buffer_sec=2.0)
    pairs = stream(m, lag=lag)
    assert len(pairs) >= 149
    assert all(c[1:] == d[1:] for c, d in pairs)  # same frame
    assert m.stats.cnt["exact"] == len(pairs)


def test_depth_lag_beyond_buffer():
    m = RgbdMatcher(slop_sec=0.1, buffer_sec=1.0)
    pairs = stream(m, lag=1.5)
    # while the camera runs nothing matches; only the color frames of the
    # last second (still buffered when the stream ends) find their depth
    assert len(pairs) <= 16
    assert m.stats.cnt["expired"] > 100


def test_color_lag():
    m = RgbdMatcher()
    pairs = stream(m, lag=-0.6)
    assert len(pairs) >= 149 and all(c[1:] == d[1:] for c, d in pairs)


def test_approximate_stamps():
    # realsense: aligned depth has the depth frame stamp, a few ms off
    m = RgbdMatcher(slop_sec=0.1)
    pairs = stream(m, depth_offset_ms=7, lag=0.2)
    assert len(pairs) >= 148 and all(c[1:] == d[1:] for c, d in pairs)
    assert m.stats.cnt["approx"] == len(pairs)


def test_approximate_waits_until_final():
    m = RgbdMatcher(slop_sec=0.1)
    assert m.add_depth(100 * MS, "d0", 0.0) is None
    # nearest depth is older: a closer one may still come
    assert m.add_color(160 * MS, "c0", 0.0) is None
    # a closer depth after the color: final
    assert m.add_depth(165 * MS, "d1", 0.0) == ("c0", "d1")


def test_no_depth_within_slop_is_dropped():
    m = RgbdMatcher(slop_sec=0.05)
    m.add_color(100 * MS, "c0", 0.0)
    assert m.add_depth(300 * MS, "d0", 0.0) is None  # 200 ms off
    assert m.stats.cnt["no_depth"] == 1 and m.colors == []


def test_only_the_newest_pair():
    m = RgbdMatcher()
    for i in range(3):
        m.add_color(i * 66 * MS, f"c{i}", 0.0)
    # only the depth of the newest color arrives (the others were dropped)
    assert m.add_depth(132 * MS, "d2", 0.0) == ("c2", "d2")
    assert m.colors == []
    assert m.stats.cnt["superseded"] == 2


def test_reordered_frames():
    m = RgbdMatcher()
    m.add_color(200 * MS, "c2", 0.0)
    m.add_color(100 * MS, "c1", 0.0)  # late arrival of an older frame
    assert [c.stamp for c in m.colors] == [100 * MS, 200 * MS]
    assert m.add_depth(200 * MS, "d2", 0.0) == ("c2", "d2")


def test_stats_format():
    m = RgbdMatcher()
    stream(m, n=30, lag=0.4)
    s = m.reset_stats().format(10.0, 0, 0)
    assert "pairs=" in s and "depth lag avg=+400ms" in s
    assert m.stats.cnt["color_in"] == 0


# --------------------------------------------------------------- node level
class RgbdNode(ImageProcessingNode):
    def __init__(self):
        super().__init__("rgbd_test", subscribe_camera_info=False,
                         subscribe_depth=True, rgbd_sync=True)
        self.processed = []

    def process_image_with_depth(self, header, cv_image, cv_depth):
        self.processed.append((header.stamp, cv_image.shape, cv_depth.dtype, cv_depth[0, 0]))


def color_msg(sec):
    m = CompressedImage(format="jpeg")
    m.header.stamp = Time(seconds=sec).to_msg()
    m.data = cv2.imencode(".jpg", np.zeros((48, 64, 3), np.uint8))[1].tobytes()
    return m


def depth_msg(sec, mm=1234):
    m = CompressedImage(format="16UC1; compressedDepth png")
    m.header.stamp = Time(seconds=sec).to_msg()
    png = cv2.imencode(".png", np.full((48, 64), mm, np.uint16))[1].tobytes()
    m.data = struct.pack("<iff", 0, 0.0, 0.0) + png  # 12 byte header
    return m


@pytest.fixture
def node():
    rclpy.init()
    n = RgbdNode()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def test_node_processes_matched_pairs(node):
    # 10 frames at 15 fps; all the depth frames arrive after the color frames
    secs = [100 + i / 15 for i in range(10)]
    for t in secs:
        node._rgbd_color_callback(color_msg(t))
    assert node.processed == []
    for t in secs:
        node._rgbd_depth_callback(depth_msg(t))
    assert len(node.processed) == 10
    assert node.processed[0][1:] == ((48, 64, 3), np.uint16, 1234)
    assert node.get_parameter("rgbd_slop").value == 0.1
