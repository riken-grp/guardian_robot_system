# coding: utf-8 -*-
"""Person detection + pose (17-keypoint COCO) estimation, replacing
ultralytics YOLOv8-pose (AGPL-3.0) with RTMPose (Apache-2.0) via `rtmlib`.
"""

import numpy as np
from rtmlib import Body


class RTMPoseEstimator:
    def __init__(self, mode="balanced", device="cuda", score_thr=0.3):
        self.body = Body(mode=mode, backend="onnxruntime", device=device, to_openpose=False)
        # rtmlib's Body() has no constructor argument for the detector's score
        # threshold; it's read from this plain instance attribute at inference
        # time, so setting it after construction is the only way to apply it.
        self.body.det_model.score_thr = score_thr

    def pose(self, img):
        # Body.__call__() computes bboxes internally via det_model() but never
        # returns them, so we call det_model/pose_model ourselves to get both.
        bboxes = self.body.det_model(img)
        if len(bboxes) == 0:
            return np.empty((0, 6)), np.empty((0, 17, 3))

        keypoints, scores = self.body.pose_model(img, bboxes=bboxes)

        bbs = np.zeros((len(bboxes), 6))
        bbs[:, :4] = bboxes
        bbs[:, 4] = 1.0  # rtmlib's detector doesn't expose per-box confidence,
        bbs[:, 5] = 0  # only already-thresholded boxes; single person class

        # (x, y, conf) per keypoint
        poses = np.concatenate([keypoints, scores[..., np.newaxis]], axis=-1)

        return bbs, poses
