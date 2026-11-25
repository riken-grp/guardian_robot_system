"""Frame gate: frame selection by stamp and republishing of matched pairs."""

import random

import pytest
import rclpy
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage

from scene_understanding.frame_gate_node import FrameGateNode
from scene_understanding.rgbd_matcher import FrameRateLimiter, RgbdMatcher

MS = 1_000_000  # ns


def stamps(fps, n, start=10.0):
    return [int((start + i / fps) * 1e9) for i in range(n)]


def selected(limiter, ts):
    return [t for t in ts if limiter.accept(t)]


@pytest.mark.parametrize("fps, rate", [(30.0, 10.0), (30.0, 15.0), (15.0, 10.0), (30.0, 12.0)])
def test_average_rate(fps, rate):
    ts = stamps(fps, int(fps * 20))  # 20 s
    out = selected(FrameRateLimiter(rate), ts)
    assert abs(len(out) / 20.0 - rate) < 0.2


def test_every_third_frame_at_30fps():
    ts = stamps(30.0, 30)
    assert selected(FrameRateLimiter(10.0), ts) == ts[::3]


def test_rate_zero_and_above_camera_pass_all():
    ts = stamps(30.0, 30)
    assert selected(FrameRateLimiter(0.0), ts) == ts
    assert selected(FrameRateLimiter(60.0), ts) == ts


def test_old_or_duplicate_stamps_rejected():
    lim = FrameRateLimiter(0.0)
    assert lim.accept(1000 * MS)
    assert not lim.accept(1000 * MS)
    assert not lim.accept(900 * MS)


def test_gap_allows_short_burst_then_rate():
    lim = FrameRateLimiter(10.0, burst=2.0)
    assert lim.accept(10_000 * MS)
    assert lim.accept(10_100 * MS)
    # camera dropout of 1 s at 30 fps: at most `burst` frames in a row, then 10 Hz
    ts = [int((11.133 + i / 30.0) * 1e9) for i in range(60)]  # 2 s
    out = selected(lim, ts)
    assert out[:2] == ts[:2]
    assert ts[2] not in out
    assert abs(len(out) / 2.0 - 10.0) <= 1.0


def thinned_30fps(keep, seconds=60, seed=0):
    """30 fps camera stamps, each frame kept with probability ``keep``
    (frames thinned by the transport, as observed over zenoh)."""
    rng = random.Random(seed)
    return [t for t in stamps(30.0, int(30 * seconds)) if rng.random() < keep]


@pytest.mark.parametrize("keep", [0.25, 0.28, 0.3])
def test_irregular_stream_slower_than_rate_passes(keep):
    # ~7.5-9 Hz with 33 / 66 / 133 ms intervals: a minimum-interval limiter
    # passed only about half of such a stream
    ts = thinned_30fps(keep)
    out = selected(FrameRateLimiter(10.0), ts)
    assert len(out) >= 0.85 * len(ts)


def test_bursty_stream_as_observed_over_zenoh_passes():
    # recorded on the server: bursts of 4-5 frames 33 ms apart every ~0.6 s
    # (~8 Hz); the first gate (minimum interval) passed about 45 % of them.
    # burst=3 passes 96 % of the recorded sequence; longer bursts are cut to
    # what the subscriber queues of the nodes can hold anyway.
    ts = [
        int((10.0 + 0.6 * b + 0.0333 * i) * 1e9) for b in range(100) for i in range(4)
    ]
    out = selected(FrameRateLimiter(10.0), ts)
    assert len(out) >= 0.95 * len(ts)


def test_irregular_stream_faster_than_rate_is_limited():
    ts = thinned_30fps(0.6)  # ~18 Hz
    out = selected(FrameRateLimiter(10.0), ts)
    assert abs(len(out) / 60.0 - 10.0) < 0.5


def test_jump_back_resets():
    lim = FrameRateLimiter(10.0)
    assert lim.accept(100_000 * MS)
    assert lim.jumped_back(10_000 * MS)
    assert lim.accept(10_000 * MS)
    assert lim.accept(10_100 * MS)


def test_gated_pairs_match_exactly_downstream():
    """Depth stamps are rewritten, so a tight slop matches every gated pair."""

    class Msg:
        def __init__(self, t):
            self.t = t

    lim = FrameRateLimiter(10.0)
    gate = RgbdMatcher(slop_sec=0.1)
    gated = []
    for i, t in enumerate(stamps(30.0, 90)):
        gate.add_color(t, ("c", t), 0.0)
        # depth stamp slightly off the color stamp, as from the camera
        pair = gate.add_depth(t + 2 * MS, ("d", t + 2 * MS), 0.0)
        if pair and lim.accept(pair[0][1]):
            gated.append((pair[0][1], pair[1]))
    assert len(gated) == 30

    node_matcher = RgbdMatcher(slop_sec=0.005)
    n = 0
    for t, _depth in gated:
        assert node_matcher.add_color(t, t, 0.0) is None
        assert node_matcher.add_depth(t, t, 0.0) == (t, t)  # same stamp
        n += 1
    assert n == 30


# ---------------------------------------------------------------- node


def image(sec, fmt="jpeg"):
    m = CompressedImage()
    m.header.stamp = Time(nanoseconds=int(sec * 1e9)).to_msg()
    m.header.frame_id = "camera_color_optical_frame"
    m.format = fmt
    return m


@pytest.fixture
def node():
    rclpy.init()
    n = FrameGateNode()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def test_node_publishes_every_matched_pair_by_default(node):
    published = []
    node.pub_color.publish = lambda m: published.append(m)
    node.pub_depth.publish = lambda m: None
    for i in range(30):
        t = 10.0 + i / 30.0
        node._color_callback(image(t))
        node._depth_callback(image(t + 0.002, "16UC1; compressedDepth png"))
    assert len(published) == 30  # rate 0 (default): no limit


def test_node_publishes_selected_pairs_with_color_stamp(node):
    node.limiter = FrameRateLimiter(10.0)
    published = []
    node.pub_color.publish = lambda m: published.append(("c", m))
    node.pub_depth.publish = lambda m: published.append(("d", m))

    for i in range(30):  # 1 s at 30 fps
        t = 10.0 + i / 30.0
        node._color_callback(image(t))
        node._depth_callback(image(t + 0.002, "16UC1; compressedDepth png"))

    colors = [m for k, m in published if k == "c"]
    depths = [m for k, m in published if k == "d"]
    assert len(colors) == len(depths) == 10  # rate 10 Hz
    for c, d in zip(colors, depths):
        assert c.header.stamp == d.header.stamp
        assert d.format.endswith("png")
