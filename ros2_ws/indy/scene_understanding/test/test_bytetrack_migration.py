"""ByteTrack migration (supervision.ByteTrack -> trackers.ByteTrackTracker).

Skipped when the `trackers` package is not installed.
"""

import sys
import types

import numpy as np
import pytest

sv = pytest.importorskip("supervision")
trackers = pytest.importorskip("trackers")

# the RT-DETR model is not needed for the tracking logic tested here
for _name in ("cv2", "torch", "transformers"):
    try:
        __import__(_name)
    except Exception:
        sys.modules[_name] = types.ModuleType(_name)
_tf = sys.modules["transformers"]
for _attr in ("RTDetrForObjectDetection", "RTDetrImageProcessor"):
    if not hasattr(_tf, _attr):
        setattr(_tf, _attr, None)

from scene_understanding.object_detector import (  # noqa: E402
    legacy_to_bytetrack,
    tracked_to_array,
)


def make_tracker(**kw):
    params = legacy_to_bytetrack(0.5, 300, 0.8)
    params.update(kw)
    return trackers.ByteTrackTracker(frame_rate=30.0, **params)


def dets(boxes, conf, cls=None):
    n = len(conf)
    return sv.Detections(
        xyxy=np.array(boxes, float).reshape(-1, 4),
        confidence=np.array(conf, float),
        class_id=np.zeros(n, int) if cls is None else np.array(cls, int),
    )


def run(tracker, frames):
    return [tracked_to_array(tracker.update(d)) for d in frames]


def test_legacy_parameter_conversion():
    p = legacy_to_bytetrack(track_thresh=0.5, track_buffer=300, match_thresh=0.8)
    assert p["high_conf_det_threshold"] == 0.5
    assert p["track_activation_threshold"] == pytest.approx(0.6)
    assert p["minimum_iou_threshold"] == pytest.approx(0.2)
    assert p["lost_track_buffer"] == 300
    assert p["minimum_consecutive_frames"] == 2
    assert legacy_to_bytetrack(0.95, 1, 1.2)["track_activation_threshold"] == 1.0
    assert legacy_to_bytetrack(0.95, 1, 1.2)["minimum_iou_threshold"] == 0.0


def test_id_assigned_on_second_frame_and_kept():
    box = [100, 100, 150, 200]
    out = run(make_tracker(), [dets([box], [0.9]) for _ in range(5)])
    assert out[0].shape == (0, 7)  # unconfirmed (tracker_id -1) is dropped
    for a in out[1:]:
        assert a.shape == (1, 7)
        assert a[0, 4] == 1  # 1-based like sv.ByteTrack
    np.testing.assert_allclose(out[-1][0, :4], box, atol=1)


def test_columns_conf_and_class():
    frames = [dets([[0, 0, 10, 10], [50, 50, 80, 90]], [0.9, 0.7], [3, 5])] * 3
    a = run(make_tracker(), frames)[-1]
    a = a[np.argsort(a[:, 0])]
    np.testing.assert_allclose(a[:, 5], [0.9, 0.7])
    np.testing.assert_allclose(a[:, 6], [3, 5])
    assert set(a[:, 4]) == {1, 2}


def test_one_frame_false_positive_never_gets_an_id():
    t = make_tracker()
    frames = [dets([[0, 0, 10, 10]], [0.95])] + [dets([], [])] * 3
    assert all(len(a) == 0 for a in run(t, frames))
    # the next object gets the first id
    out = run(t, [dets([[50, 50, 80, 90]], [0.9])] * 2)
    assert out[1][0, 4] == 1


def test_below_activation_threshold_does_not_start_a_track():
    out = run(make_tracker(), [dets([[0, 0, 10, 10]], [0.55])] * 5)
    assert all(len(a) == 0 for a in out)


def test_lost_track_is_recovered_with_the_same_id():
    box = [100, 100, 150, 200]
    frames = [dets([box], [0.9])] * 3 + [dets([], [])] * 10 + [dets([box], [0.9])]
    out = run(make_tracker(), frames)
    assert out[2][0, 4] == 1 and out[-1][0, 4] == 1


def test_matching_uses_iou_threshold():
    # IoU between the two boxes is 1/3 (>= 0.2): same track
    t = make_tracker()
    run(t, [dets([[0, 0, 100, 100]], [0.9])] * 2)
    a = tracked_to_array(t.update(dets([[50, 0, 150, 100]], [0.9])))
    assert len(a) == 1 and a[0, 4] == 1
    # with minimum_iou_threshold 0.5 it does not match
    t = make_tracker(minimum_iou_threshold=0.5)
    run(t, [dets([[0, 0, 100, 100]], [0.9])] * 2)
    assert len(tracked_to_array(t.update(dets([[50, 0, 150, 100]], [0.9])))) == 0


def test_empty_input():
    t = make_tracker()
    assert tracked_to_array(t.update(dets([], []))).shape == (0, 7)
