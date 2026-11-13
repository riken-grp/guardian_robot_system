# coding: utf-8

import math
import os

import numpy as np
import rclpy
from rclpy.duration import Duration
from tf2_ros import TransformException

_EPS = np.finfo(float).eps * 4.0

# half size of the neighborhood used to read the depth of a keypoint [px]
DEPTH_WINDOW_RADIUS = 3
# keypoints below this confidence are not lifted to 3D
KEYPOINT_CONF_THRESH = 0.5
# central part of a bbox (ratio of w/h) used to estimate its depth
BBOX_DEPTH_REGION_RATIO = 0.5
PERSON_BBOX_DEPTH_REGION_RATIO = 0.3
MAX_REGION_SAMPLES = 2500
# shoulders and hips (COCO keypoints)
TORSO_KEYPOINTS = [5, 6, 11, 12]


class Sensor3DMapper:
    def __init__(self, tf_buffer, world_frame_id, logger=None):
        self.tf_buffer = tf_buffer
        self.world_frame_id = world_frame_id
        self.logger = logger
        # last successfully looked-up transforms; kept when a lookup fails so
        # that a late / missing TF does not drop the global coordinates
        self.matrix_R_T = None
        self.rover_matrix_R_T = None
        self.last_tf_error = None

        robot_name = os.getenv("ROBOT_NAME")
        if robot_name is None:
            print("warning: ROBOT_NAME not set; rover coordinate computation disabled")
            self.rover_frame_id = None
        else:
            self.rover_frame_id = robot_name + "_base_link"

    def translation_matrix(self, direction):
        M = np.identity(4)
        M[:3, 3] = direction[:3]
        return M

    def quaternion_matrix(self, quaternion):
        q = np.array(quaternion[:4], dtype=np.float64, copy=True)
        nq = np.dot(q, q)
        if nq < _EPS:
            return np.identity(4)
        q *= math.sqrt(2.0 / nq)
        q = np.outer(q, q)
        return np.array(
            (
                (1.0 - q[1, 1] - q[2, 2], q[0, 1] - q[2, 3], q[0, 2] + q[1, 3], 0.0),
                (q[0, 1] + q[2, 3], 1.0 - q[0, 0] - q[2, 2], q[1, 2] - q[0, 3], 0.0),
                (q[0, 2] - q[1, 3], q[1, 2] + q[0, 3], 1.0 - q[0, 0] - q[1, 1], 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
            dtype=np.float64,
        )

    def update_tf(self, frame_id, time=rclpy.time.Time(seconds=0)):
        """Update the sensor -> world transform without blocking.

        Returns True if a transform is available (freshly looked up, or the
        last successful one kept as a fallback).
        """
        matrix = self._update_tf(frame_id, self.world_frame_id, time)
        if matrix is not None:
            self.matrix_R_T = matrix
        return self.matrix_R_T is not None

    def update_rover_tf(self, frame_id, time=rclpy.time.Time(seconds=0)):
        # calc transformation from sensor coordinate to the rover coordinate
        # call this only from nodes that use project_to_rover()
        if self.rover_frame_id is not None:
            matrix = self._update_tf(frame_id, self.rover_frame_id, time)
            if matrix is not None:
                self.rover_matrix_R_T = matrix
        return self.rover_matrix_R_T is not None

    def _update_tf(self, frame_id, target_frame_id, time):
        """Non-blocking TF lookup.

        Tries the transform at ``time`` first and then the latest available
        one (e.g. when ``time`` is newer than the last TF message).  Never
        waits: a blocking lookup in the image callback would delay every
        frame when TF is late or missing.
        """
        tran = None
        for t in (time, rclpy.time.Time()):
            try:
                tran = self.tf_buffer.lookup_transform(target_frame_id, frame_id, t)
                break
            except TransformException as e:
                self.last_tf_error = e
        if tran is None:
            if self.logger is not None:
                self.logger.warn(
                    f"TF lookup {frame_id} -> {target_frame_id} failed: "
                    f"{self.last_tf_error}",
                    throttle_duration_sec=5.0,
                )
            return None

        t = tran.transform.translation
        r = tran.transform.rotation

        return np.dot(
            self.translation_matrix([t.x, t.y, t.z]),
            self.quaternion_matrix([r.x, r.y, r.z, r.w]),
        )

    def project_to_map(self, points_sensor, info, flags=None):
        """
        Sensor coordinate (Xs, Ys, Zs) to map coordinate (X, Y, Z)

        Points whose ``flags`` is False (no valid depth) are returned as (0, 0, 0)
        instead of being transformed, so that they do not collapse onto the
        camera origin in the map frame.
        """
        points_sensor = np.asarray(points_sensor, dtype=np.float64).reshape(-1, 3)
        if self.matrix_R_T is not None:
            # sensor to map
            xyz1 = np.hstack((points_sensor, np.ones((len(points_sensor), 1)))).T
            xyz = (self.matrix_R_T @ xyz1).T[:, :3]
        else:
            xyz = np.zeros_like(points_sensor)
        if flags is not None:
            xyz[~np.asarray(flags, dtype=bool).reshape(-1)] = 0.0
        return xyz

    def project_to_rover(self, points_sensor, info):
        """
        Sensor coordinate (Xs, Ys, Zs) to rover coordinate (X, Y, Z)
        """
        if self.rover_matrix_R_T is not None:
            # sensor to map
            xyz1 = np.hstack((points_sensor, np.ones((len(points_sensor), 1)))).T
            xyz = (self.rover_matrix_R_T @ xyz1).T[:, :3]
        else:
            xyz = np.zeros_like(points_sensor)
        return xyz

    def get_robot_location(self, dinfo):
        # location of the camera origin
        robot_location = self.project_to_map([[0, 0, 0]], dinfo)[0][:2]  # only x, y
        # an unit vector in the camera coordinate
        robot_direction = self.project_to_map([[0, 0, 1]], dinfo)[0][:2]  # only x, y
        # unit vector in the world coordinate
        robot_direction -= robot_location
        norm = np.linalg.norm(robot_direction)
        if norm < _EPS:
            # no TF (all zeros) or camera looking straight up / down
            robot_direction = np.zeros(2)
        else:
            robot_direction /= norm
        theta = np.arctan2(robot_direction[1], robot_direction[0])
        robot_location = np.hstack((robot_location, robot_direction, theta))

        return robot_location

    def get_3d_value(self, detections, dimg, cinfo, region_ratio=BBOX_DEPTH_REGION_RATIO):
        """Append sensor / world 3D locations of bbox centers to detections.

        detections: (N, >=4) array whose first 4 columns are x, y, w, h.
        Returns (N, C + 6): [detections, Xs, Ys, Zs, Xg, Yg, Zg].
        Rows without valid depth get zeros for both sensor and world coords.
        """
        detections = np.asarray(detections, dtype=np.float64)
        if len(detections) == 0:
            ncol = detections.shape[1] if detections.ndim == 2 else 0
            return np.zeros((0, ncol + 6))
        # image to sensor coordinate
        points_3d, flags = self.get_bb_to_center_3d(
            detections, dimg, cinfo, region_ratio=region_ratio
        )
        # sensor to world coordinate
        mapped_points = self.project_to_map(points_3d, cinfo, flags)
        return np.hstack((detections, points_3d, mapped_points))

    def get_3d_pose(self, poses, dimg, cinfo, keypoint_thresh=KEYPOINT_CONF_THRESH):
        """Add sensor / world 3D coordinates to each keypoint.

        poses: (N, K, 3) array of (x, y, conf).
        Returns (N, K, 9): (x, y, Xs, Ys, Zs, Xg, Yg, Zg, conf).
        Keypoints with low confidence or without valid depth get zeros.
        """
        poses = np.asarray(poses, dtype=np.float64)
        if len(poses) == 0:
            n_kp = poses.shape[1] if poses.ndim == 3 else 0
            return np.zeros((0, n_kp, 9))

        n_persons, n_kp = poses.shape[:2]
        points = poses.reshape(-1, 3)
        valid = (points[:, 2] >= keypoint_thresh) & np.all(points[:, :2] > 0, axis=1)

        # compute camera and global coordinates
        points_3d, flags = self.get_3d(points[:, :2], dimg, cinfo, valid=valid)
        points_3d_global = self.project_to_map(points_3d, cinfo, flags)

        points_3d = points_3d.reshape((n_persons, n_kp, 3))
        points_3d_global = points_3d_global.reshape((n_persons, n_kp, 3))

        return np.concatenate(
            (poses[:, :, :2], points_3d, points_3d_global, poses[:, :, 2:3]), axis=2
        )

    def get_3d_person(
        self,
        detections,
        poses,
        dimg,
        cinfo,
        keypoint_thresh=KEYPOINT_CONF_THRESH,
        region_ratio=PERSON_BBOX_DEPTH_REGION_RATIO,
    ):
        """3D body location and 3D keypoints for each detected person.

        The body location is the median of valid torso keypoints (shoulders and
        hips) in 3D.  When none of them is valid, it falls back to the bbox
        center back-projected with the median depth of the bbox center region.

        Returns (detections3d, poses3d) with the layouts of ``get_3d_value`` and
        ``get_3d_pose``.
        """
        detections = np.asarray(detections, dtype=np.float64)
        poses3d = self.get_3d_pose(poses, dimg, cinfo, keypoint_thresh)
        if len(detections) == 0:
            ncol = detections.shape[1] if detections.ndim == 2 else 0
            return np.zeros((0, ncol + 6)), poses3d

        body_3d, flags = self.get_bb_to_center_3d(
            detections, dimg, cinfo, region_ratio=region_ratio
        )
        for i in range(min(len(detections), len(poses3d))):
            torso = poses3d[i, TORSO_KEYPOINTS, 2:5]
            torso = torso[torso[:, 2] > 0]
            if len(torso) > 0:
                body_3d[i] = np.median(torso, axis=0)
                flags[i] = True

        body_global = self.project_to_map(body_3d, cinfo, flags)
        return np.hstack((detections, body_3d, body_global)), poses3d

    def get_3d_face(self, associated, dimg, cinfo):
        if len(associated.persons) == 0:
            return associated

        n_persons = len(associated.persons)
        fflag = [False] * n_persons
        bbs = np.zeros((n_persons, 4))
        for i, person in enumerate(associated.persons):
            if len(person.face_location) != 4:
                continue
            floc = np.asarray(person.face_location).reshape((-1, 4))
            bbs[i] = floc
            fflag[i] = True

        fcenter = np.zeros((n_persons, 2))  # center (x, y)
        fcenter[:, 0] = bbs[:, 0] + bbs[:, 2] / 2
        fcenter[:, 1] = bbs[:, 1] + bbs[:, 3] / 2

        fcenter_3d, flags = self.get_3d(fcenter, dimg, cinfo)
        fcenter_3d_global = self.project_to_map(fcenter_3d, cinfo, flags)

        for i, person in enumerate(associated.persons):
            if fflag[i] and flags[i]:
                person.face_location_sensor = fcenter_3d[i, :3].tolist()
                person.face_location_global = fcenter_3d_global[i, :3].tolist()

        return associated

    def get_bb_to_center_3d(self, dets, dimg, cinfo, region_ratio=BBOX_DEPTH_REGION_RATIO):
        """Back-project bbox centers using a robust depth of the bbox.

        The depth is the median of valid (non-zero) depth values inside the
        central region of the bbox (``region_ratio`` of its width / height),
        which is far more robust to holes and background pixels than reading
        the single center pixel.

        Returns (points_3d (N, 3), flags (N,)).
        """
        dets = np.asarray(dets, dtype=np.float64)
        depth, scale = self._depth_view(dimg)
        sx, sy = self._depth_scale(depth, cinfo)
        dh, dw = depth.shape[:2]

        cx = dets[:, 0] + dets[:, 2] / 2.0
        cy = dets[:, 1] + dets[:, 3] / 2.0
        hw = np.maximum(dets[:, 2] * region_ratio / 2.0, 1.0)
        hh = np.maximum(dets[:, 3] * region_ratio / 2.0, 1.0)
        x0 = np.clip(np.floor((cx - hw) * sx), 0, dw).astype(np.int64)
        x1 = np.clip(np.ceil((cx + hw) * sx), 0, dw).astype(np.int64)
        y0 = np.clip(np.floor((cy - hh) * sy), 0, dh).astype(np.int64)
        y1 = np.clip(np.ceil((cy + hh) * sy), 0, dh).astype(np.int64)
        # subsample large regions to bound the cost
        sizes = (x1 - x0) * (y1 - y0)
        steps = np.maximum(1, np.sqrt(sizes / MAX_REGION_SAMPLES).astype(np.int64))

        depth_values = np.zeros(len(dets))
        for i in np.nonzero(sizes > 0)[0]:
            # strided view of the raw depth (no copy / conversion of the image)
            vals = self._valid_depth(
                depth[y0[i] : y1[i] : steps[i], x0[i] : x1[i] : steps[i]]
            )
            if len(vals) > 0:
                depth_values[i] = np.median(vals) * scale

        flags = depth_values > 0
        points_3d = self._back_project(np.vstack((cx, cy)).T, depth_values, cinfo)
        return points_3d, flags

    def get_3d(self, points, depth_img, dinfo, valid=None, window=DEPTH_WINDOW_RADIUS):
        """image (x, y) to sensor (Xs, Ys, Zs).

        The depth of each point is the median of valid (non-zero) depth values
        in a (2 * window + 1)^2 neighborhood, so that a single missing pixel does
        not invalidate the point.  Points outside the image, points with
        ``valid`` False, and points without valid depth get (0, 0, 0) and
        flag False.

        Returns (Xs, Ys, Zs) (N, 3), flags (N,).
        """
        points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        n = len(points)
        depth, scale = self._depth_view(depth_img)
        sx, sy = self._depth_scale(depth, dinfo)
        dh, dw = depth.shape[:2]

        u = np.floor(points[:, 0] * sx).astype(np.int64)
        v = np.floor(points[:, 1] * sy).astype(np.int64)
        flag = (u >= 0) & (u < dw) & (v >= 0) & (v < dh)
        if valid is not None:
            flag &= np.asarray(valid, dtype=bool).reshape(-1)

        depth_values = np.zeros(n)
        idx = np.nonzero(flag)[0]
        if len(idx) > 0:
            # gather all (2w+1)^2 windows at once: (M, k*k)
            offs = np.arange(-window, window + 1)
            vv = v[idx, None, None] + offs[None, :, None]
            uu = u[idx, None, None] + offs[None, None, :]
            inside = (vv >= 0) & (vv < dh) & (uu >= 0) & (uu < dw)
            patches = depth[np.clip(vv, 0, dh - 1), np.clip(uu, 0, dw - 1)]
            patches = patches.reshape(len(idx), -1).astype(np.float64)
            # pixels outside the image / without depth are ignored
            invalid = ~inside.reshape(len(idx), -1) | ~(patches > 0)
            invalid |= ~np.isfinite(patches)
            patches[invalid] = np.nan
            has_depth = ~invalid.all(axis=1)
            if has_depth.any():
                depth_values[idx[has_depth]] = (
                    np.nanmedian(patches[has_depth], axis=1) * scale
                )

        flag &= depth_values > 0
        return self._back_project(points, depth_values, dinfo), flag

    @staticmethod
    def _back_project(points, depth_values, cinfo):
        """Pinhole back-projection; rows with depth 0 become (0, 0, 0)."""
        depth_values = np.asarray(depth_values, dtype=np.float64).reshape(-1, 1)
        xy = (points[:, :2] - np.array([cinfo.k[2], cinfo.k[5]])) / np.array(
            [cinfo.k[0], cinfo.k[4]]
        )
        return np.hstack((xy * depth_values, depth_values))

    @staticmethod
    def _depth_view(depth_img):
        """Return (2D depth array without copy, scale to meters).

        16UC1 images are in millimeters (scale 0.001), 32FC1 in meters.
        The image is not converted; only sampled values are scaled.
        """
        depth_img = np.asarray(depth_img)
        if depth_img.ndim == 3:
            depth_img = depth_img[:, :, 0]
        if np.issubdtype(depth_img.dtype, np.integer):
            return depth_img, 0.001
        return depth_img, 1.0

    @staticmethod
    def _valid_depth(vals):
        """Valid (positive, finite) depth values of a sampled region, flattened."""
        if np.issubdtype(vals.dtype, np.integer):
            return vals[vals > 0]
        return vals[np.isfinite(vals) & (vals > 0)]

    @staticmethod
    def _depth_scale(depth_img, cinfo):
        """Scale from color-image pixel coords to depth-image pixel coords.

        1.0 when the depth image is aligned to the color image (same size).
        """
        dh, dw = depth_img.shape[:2]
        sx = dw / cinfo.width if getattr(cinfo, "width", 0) else 1.0
        sy = dh / cinfo.height if getattr(cinfo, "height", 0) else 1.0
        return sx, sy
