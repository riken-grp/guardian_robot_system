# coding: utf-8 -*-
"""Object detection + tracking, replacing ultralytics YOLOv8 (AGPL-3.0).

Detection: RT-DETR (Apache-2.0) via HuggingFace transformers.
Tracking: ByteTrack (MIT) via the `supervision` library, operating on plain
numpy detections so it has no dependency on ultralytics.
"""

import cv2
import numpy as np
import supervision as sv
import torch
from transformers import RTDetrForObjectDetection, RTDetrImageProcessor


class RTDetrTracker:
    def __init__(
        self,
        model="PekingU/rtdetr_r101vd_coco_o365",
        device="cuda",
        track_thresh=0.5,
        track_buffer=300,
        match_thresh=0.8,
    ):
        self.device = device
        self.image_processor = RTDetrImageProcessor.from_pretrained(model)
        self.model = RTDetrForObjectDetection.from_pretrained(model).to(device).eval()
        self.names = self.model.config.id2label
        # supervision>=0.23 renamed these constructor args (track_thresh ->
        # track_activation_threshold, track_buffer -> lost_track_buffer,
        # match_thresh -> minimum_matching_threshold); our own ROS parameter
        # names (track_thresh/track_buffer/match_thresh) are kept as-is.
        self.tracker = sv.ByteTrack(
            track_activation_threshold=track_thresh,
            lost_track_buffer=track_buffer,
            minimum_matching_threshold=match_thresh,
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
            xyxy=result["boxes"].cpu().numpy(),
            confidence=result["scores"].cpu().numpy(),
            class_id=result["labels"].cpu().numpy(),
        )
        # sv.ByteTrack is deprecated since supervision-0.28.0 in favor of
        # ByteTrackTracker from the separate `trackers` package (whose update
        # method is named `update()`), but as long as we keep using
        # sv.ByteTrack the method is still update_with_detections().
        tracked = self.tracker.update_with_detections(detections)

        if len(tracked) == 0:
            return np.empty((0, 7))

        # xyxy, track_id, conf, class
        return np.hstack(
            (
                tracked.xyxy,
                tracked.tracker_id.reshape(-1, 1).astype(np.float64),
                tracked.confidence.reshape(-1, 1),
                tracked.class_id.reshape(-1, 1).astype(np.float64),
            )
        )
