# coding: utf-8

import math
import os

import numpy as np
import rclpy
from rclpy.duration import Duration
from tf2_ros import TransformException

_EPS = np.finfo(float).eps * 4.0


class Sensor3DMapper:
    def __init__(self, tf_buffer, world_frame_id):
        self.tf_buffer = tf_buffer
        self.world_frame_id = world_frame_id
        self.matrix_R_T = None
        self.rover_matrix_R_T = None

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
        # calc transformation from sensor coordinate to the world coordinate
        self.matrix_R_T = self._update_tf(frame_id, self.world_frame_id, time)
        return self.matrix_R_T is not None

    def update_rover_tf(self, frame_id, time=rclpy.time.Time(seconds=0)):
        # calc transformation from sensor coordinate to the rover coordinate
        # call this only from nodes that use project_to_rover()
        if self.rover_frame_id is not None:
            self.rover_matrix_R_T = self._update_tf(frame_id, self.rover_frame_id, time)
        return self.rover_matrix_R_T is not None

    def _update_tf(self, frame_id, target_frame_id, time):
        try:
            tran = self.tf_buffer.lookup_transform(
                target_frame_id, frame_id, time, timeout=Duration(seconds=0.1)
            )
        except TransformException as e:
            print(e)
            return None

        t = tran.transform.translation
        r = tran.transform.rotation

        return np.dot(
            self.translation_matrix([t.x, t.y, t.z]),
            self.quaternion_matrix([r.x, r.y, r.z, r.w]),
        )

    def project_to_map(self, points_sensor, info):
        """
        Sensor coordinate (Xs, Ys, Zs) to map coordinate (X, Y, Z)
        """
        if self.matrix_R_T is not None:
            # sensor to map
            xyz1 = np.hstack((points_sensor, np.ones((len(points_sensor), 1)))).T
            xyz = (self.matrix_R_T @ xyz1).T[:, :3]
        else:
            xyz = np.zeros_like(points_sensor)
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
        robot_direction /= np.linalg.norm(robot_direction)
        theta = np.arctan2(robot_direction[1], robot_direction[0])
        robot_location = np.hstack((robot_location, robot_direction, theta))

        return robot_location

    def get_3d_value(self, detections, dimg, cinfo):
        # image to sensor coordinate
        points_3d = self.get_bb_to_center_3d(detections, dimg, cinfo)
        dets = np.hstack((detections, points_3d))

        # sensor to world coordinate
        mapped_points = self.project_to_map(points_3d, cinfo)
        dets = np.hstack((dets, mapped_points))

        return dets

    def get_3d_pose(self, poses, dimg, cinfo):
        if len(poses) == 0:
            return poses

        n_persons = len(poses)
        points = poses.reshape(-1, 3)

        # compute camera and global coordinates
        points_3d, flags = self.get_3d(points, dimg, cinfo)
        points_3d_global = self.project_to_map(points_3d, cinfo)

        points_3d = points_3d.reshape((n_persons, -1, 3))
        points_3d_global = points_3d_global.reshape((n_persons, -1, 3))
        flags = flags.reshape((n_persons, -1))

        poses = np.concatenate(
            (poses[:, :, :2], points_3d, points_3d_global, poses[:, :, 2:3]), axis=2
        )

        return poses

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
        fcenter_3d_global = self.project_to_map(fcenter_3d, cinfo)

        for i, person in enumerate(associated.persons):
            if fflag[i] and flags[i]:
                person.face_location_sensor = fcenter_3d[i, :3].tolist()
                person.face_location_global = fcenter_3d_global[i, :3].tolist()

        return associated

    def get_bb_to_center_3d(self, dets, dimg, cinfo):
        cx = dets[:, 0] + dets[:, 2] // 2
        cy = dets[:, 1] + dets[:, 3] // 2
        points = np.vstack((cx, cy)).T
        points_3d, flags = self.get_3d(points, dimg, cinfo)

        return points_3d

    def get_3d(self, points, depth_img, dinfo):
        # image (x,y) to sensor (Xs,Ys,Zs)
        # return (Xs,Ys,Zs), flags
        points_pos = np.floor(points).astype(np.int64)

        idx = points_pos[:, 1] * depth_img.shape[1] + points_pos[:, 0]
        flag = idx >= 0
        flag[flag] = idx[flag] < (depth_img.shape[0] * depth_img.shape[1])

        depth_values = np.zeros((len(points_pos), 1))
        depth_values[flag] = depth_img.reshape(-1, 1)[idx[flag]]
        depth_values /= 1000.0

        flag[(depth_values == 0).reshape((-1,))] = False

        xy = (points[:, :2] - np.array([dinfo.k[2], dinfo.k[5]])) / np.array(
            [dinfo.k[0], dinfo.k[4]]
        )
        xy = xy * depth_values

        return np.hstack((xy, depth_values)), flag
