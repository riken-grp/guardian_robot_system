# coding: utf-8 -*-
"""Object detection + tracking, replacing ultralytics YOLOv8 (AGPL-3.0).

Detection: RT-DETR (Apache-2.0) via HuggingFace transformers.
Tracking: ByteTrack (Apache-2.0) of the `trackers` package (roboflow), which
replaces the deprecated ``supervision.ByteTrack``.  It operates on
``sv.Detections`` built from plain numpy arrays, so it has no dependency on
ultralytics.

Differences from ``sv.ByteTrack`` that matter here (see ``legacy_to_bytetrack``):

* ``minimum_matching_threshold`` (sv) is a threshold on the *cost*
  ``1 - IoU * score`` (accept if cost <= thresh), whereas
  ``minimum_iou_threshold`` (trackers) is a threshold on the IoU itself
  (accept if IoU >= thresh, no score fusion, used in both stages).
  ``match_thresh=0.8`` therefore corresponds to ``minimum_iou_threshold=0.2``.
* sv used ``track_activation_threshold`` both to split high / low confidence
  detections and (+0.1) to start new tracks.  trackers separates them:
  ``high_conf_det_threshold`` splits the two association stages and
  ``track_activation_threshold`` is the confidence needed to start a track.
* ``minimum_consecutive_frames``: sv's default 1 confirmed a track on its
  second matched frame (the creating frame counts as 0 there) and dropped
  unconfirmed tracks on the first miss.  In trackers the creating frame counts
  as 1 and an id is never assigned on the creating frame, so ``2`` (the
  trackers default) reproduces the previous behaviour.
* ``update()`` returns *all* detections, with ``tracker_id == -1`` for
  unconfirmed ones, in an arbitrary order; sv returned only confirmed tracks.
  Unconfirmed detections are dropped here.
* track ids are 0-based in trackers (1-based in sv).  ``id_offset`` (default
  1) keeps the previous id range, so instance_id 0 is never used.
"""

import cv2
import numpy as np
import supervision as sv
import torch
from transformers import RTDetrForObjectDetection, RTDetrImageProcessor

try:
    from trackers import ByteTrackTracker
except ImportError as e:  # pragma: no cover - depends on the environment
    raise ImportError(
        "scene_understanding requires the `trackers` package for ByteTrack "
        "(pip install trackers)"
    ) from e


def legacy_to_bytetrack(track_thresh=0.5, track_buffer=300, match_thresh=0.8):
    """Convert the sv.ByteTrack style parameters to ByteTrackTracker kwargs."""
    return dict(
        lost_track_buffer=int(track_buffer),
        high_conf_det_threshold=float(track_thresh),
        # sv started new tracks above track_activation_threshold + 0.1
        track_activation_threshold=min(float(track_thresh) + 0.1, 1.0),
        minimum_iou_threshold=max(0.0, 1.0 - float(match_thresh)),
        minimum_consecutive_frames=2,
    )


def tracked_to_array(tracked, id_offset=1):
    """sv.Detections from ByteTrackTracker.update() -> (N, 7) array.

    Columns: x1, y1, x2, y2, track_id, conf, class.  Unconfirmed detections
    (tracker_id < 0) are removed.
    """
    if len(tracked) == 0 or tracked.tracker_id is None:
        return np.empty((0, 7))
    tracker_id = np.asarray(tracked.tracker_id).astype(np.int64)
    keep = tracker_id >= 0
    if not keep.any():
        return np.empty((0, 7))
    n = int(keep.sum())
    conf = tracked.confidence
    conf = np.ones(n) if conf is None else np.asarray(conf, np.float64)[keep]
    cls = tracked.class_id
    cls = np.zeros(n) if cls is None else np.asarray(cls, np.float64)[keep]
    return np.hstack(
        (
            np.asarray(tracked.xyxy, np.float64)[keep],
            (tracker_id[keep] + id_offset).astype(np.float64).reshape(-1, 1),
            conf.reshape(-1, 1),
            cls.reshape(-1, 1),
        )
    )


class RTDetrTracker:
    def __init__(
        self,
        model="PekingU/rtdetr_r101vd_coco_o365",
        device="cuda",
        lost_track_buffer=300,
        frame_rate=30.0,
        high_conf_det_threshold=0.5,
        track_activation_threshold=0.6,
        minimum_iou_threshold=0.2,
        minimum_consecutive_frames=2,
        id_offset=1,
    ):
        self.device = device
        self.image_processor = RTDetrImageProcessor.from_pretrained(model)
        self.model = RTDetrForObjectDetection.from_pretrained(model).to(device).eval()
        self.names = self.model.config.id2label
        self.id_offset = int(id_offset)
        self.tracker = ByteTrackTracker(
            lost_track_buffer=int(lost_track_buffer),
            frame_rate=float(frame_rate),
            track_activation_threshold=float(track_activation_threshold),
            minimum_consecutive_frames=int(minimum_consecutive_frames),
            minimum_iou_threshold=float(minimum_iou_threshold),
            high_conf_det_threshold=float(high_conf_det_threshold),
        )

    def track(self, img, conf=0.3):
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        inputs = self.image_processor(images=img_rgb, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)

        h, w = img.shape[:2]
        result = self.image_processor.post_process_object_detection(
            outputs, target_sizes=torch.tensor([(h, w)]), threshold=conf
        )[0]

        detections = sv.Detections(
            xyxy=result["boxes"].cpu().numpy().reshape(-1, 4),
            confidence=result["scores"].cpu().numpy(),
            class_id=result["labels"].cpu().numpy().astype(int),
        )
        # ByteTrackTracker.update() replaces sv.ByteTrack.update_with_detections()
        tracked = self.tracker.update(detections)
        # xyxy, track_id, conf, class (confirmed tracks only)
        return tracked_to_array(tracked, self.id_offset)
