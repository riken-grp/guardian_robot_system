# -*- coding: utf-8 -*-

import numpy as np

face_image_size = 128
face_image_size_2d = (face_image_size, face_image_size)
cimg_width = 5

bones = [
    [0, 1],
    [0, 2],
    [1, 3],
    [2, 4],
    [3, 5],
    [4, 6],
    [5, 6],
    [5, 7],
    [6, 8],
    [7, 9],
    [8, 10],
    [5, 11],
    [6, 12],
    [11, 12],
    [11, 13],
    [12, 14],
    [13, 15],
    [14, 16],
]

colors = np.floor(np.random.rand(100, 4) * 255).astype(np.uint8)
colors[:, 3] = 1

HEAD_KEYPOINTS = np.array([0, 5, 6])  # nose, lsholder, rsholder

# detection
LOCATION_2D_COLUMN = range(0, 4)
INSTANCE_ID_COLUMN = 4
CONFIDENCE_COLUMN = 5
CLASS_ID_COLUMN = 6
LOCATION_SENSOR_COLUMN = range(7, 10)
LOCATION_GLOBAL_COLUMN = range(10, 13)

# pose
# person detection results
POSE_DET_LOCATION_2D_COLUMN = range(0, 4)
POSE_DET_CONFIDENCE_COLUMN = 4
POSE_CLASS_ID_COLUMN = 5
POSE_DET_LOCATION_SENSOR_COLUMN = range(6, 9)
POSE_DET_LOCATION_GLOBAL_COLUMN = range(9, 12)
# pose (keypoint) results
POSE_KEYPOINT_IMAGE_COLUMN = [0, 1]
POSE_KEYPOINT_SENSOR_COLUMN = [2, 3, 4]
POSE_KEYPOINT_GLOBAL_COLUMN = [5, 6, 7]
POSE_KEYPOINT_CONF_COLUMN = 8


PERSON_CLASS = 0

POSE_IOU_THRESHOLD = 0.000001
