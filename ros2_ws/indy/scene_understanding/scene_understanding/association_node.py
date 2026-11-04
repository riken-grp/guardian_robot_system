#!/usr/bin/env python
# coding: utf-8 -*-
import datetime
from collections import defaultdict, deque

import message_filters
import numpy as np
import rclpy
from pymongo import MongoClient
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Objects, Persons, Relations

from . import configs as cfg


class AssociationNode(Node):
    def __init__(self, name="RegisterDBNode"):
        super().__init__(name)
        self._declare_parameters()
        self._initialize_components()
        self._initialize_publishers_and_subscribers()

    def _declare_parameters(self):
        self.declare_parameter("iou_threshold", 0.9)
        self.declare_parameter("face_slop", 0.2)
        self.declare_parameter("face_buffer_size", 100)

    def _initialize_components(self):
        self.iou_threshold = self.get_parameter("iou_threshold").value
        self.face_slop_ns = int(self.get_parameter("face_slop").value * 1e9)
        buffer_size = self.get_parameter("face_buffer_size").value

        self.tracking = {}

        # associated poses / faces waiting for a counterpart with a close timestamp
        self.apose_buffer = deque(maxlen=buffer_size)
        self.face_buffer = deque(maxlen=buffer_size)

    def _initialize_publishers_and_subscribers(self):
        self.pub_poses = self.create_publisher(
            Persons, "out_person_topic", qos_profile=qos.qos_profile_system_default
        )
        self.pub_faces = self.create_publisher(
            Persons, "out_face_topic", qos_profile=qos.qos_profile_system_default
        )

        sub_track = message_filters.Subscriber(
            self, Objects, "in_track_topic", qos_profile=qos.qos_profile_system_default
        )
        sub_pose = message_filters.Subscriber(
            self, Persons, "in_person_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub_face = self.create_subscription(
            Persons,
            "in_face_topic",
            self.callback_face,
            qos_profile=qos.qos_profile_system_default,
        )

        self.sub_track_pose = message_filters.ApproximateTimeSynchronizer(
            [sub_track, sub_pose], 100, 0.2
        )
        self.sub_track_pose.registerCallback(self.callback_track_pose)

    def bb_matching(self, bbs1, bbs2, iou_threshold):
        if len(bbs1) == 0 or len(bbs2) == 0:
            return None, None, range(len(bbs1))

        iou_matrix = self.iou_batch(bbs1, bbs2)
        matched_indices = np.empty((0, 2), dtype=int)
        if min(iou_matrix.shape) > 0:
            a = (iou_matrix > iou_threshold).astype(np.int32)
            if a.sum(1).max() == 1 and a.sum(0).max() == 1:
                matched_indices = np.stack(np.where(a), axis=1)
            else:
                matched_indices = self.linear_assignment(-iou_matrix)
                if len(matched_indices) > 0:
                    valid = (
                        iou_matrix[matched_indices[:, 0], matched_indices[:, 1]]
                        > iou_threshold
                    )
                    matched_indices = matched_indices[valid]

        matched_body_indices = [b for b, p in matched_indices]
        unmatched = [b for b in range(len(bbs1)) if b not in matched_body_indices]
        return iou_matrix, matched_indices, unmatched

    def linear_assignment(self, cost_matrix):
        try:
            import lap

            _, x, y = lap.lapjv(cost_matrix, extend_cost=True)
            n_rows, n_cols = cost_matrix.shape
            return np.array(
                [[y[i], i] for i in x if 0 <= i < n_cols and 0 <= y[i] < n_rows]
            )
        except ImportError:
            from scipy.optimize import linear_sum_assignment

            x, y = linear_sum_assignment(cost_matrix)
            return np.array(list(zip(x, y)))

    def iou_batch(self, bb_test, bb_gt):
        """
        Computes IOU between two bboxes in the form [x,y,w,h]
        """
        bb_gt = np.expand_dims(bb_gt, 0)
        bb_test = np.expand_dims(bb_test, 1)

        xx1 = np.maximum(bb_test[..., 0], bb_gt[..., 0])
        yy1 = np.maximum(bb_test[..., 1], bb_gt[..., 1])
        xx2 = np.minimum(
            bb_test[..., 0] + bb_test[..., 2], bb_gt[..., 0] + bb_gt[..., 2]
        )
        yy2 = np.minimum(
            bb_test[..., 1] + bb_test[..., 3], bb_gt[..., 1] + bb_gt[..., 3]
        )
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        wh = w * h
        t = bb_test[..., 2] * bb_test[..., 3]
        g = bb_gt[..., 2] * bb_gt[..., 3]
        u = t + g - wh
        o = wh / u
        return o

    def face_check(self, pbbs, fbbs):
        if len(pbbs) == 0 or len(fbbs) == 0:
            return {}

        pbbs = np.array(pbbs)
        fbbs = np.array(fbbs)

        pcs = np.zeros_like(pbbs[:, :2])
        fcs = np.zeros_like(fbbs[:, :2])

        pcs[:, 0] = pbbs[:, 0] + pbbs[:, 2] // 2
        pcs[:, 1] = pbbs[:, 1] + pbbs[:, 3] // 6

        fcs[:, 0] = fbbs[:, 0] + fbbs[:, 2] // 2
        fcs[:, 1] = fbbs[:, 1] + fbbs[:, 3] // 2

        dists = np.zeros((len(pcs), len(fcs)))

        for i, pb in enumerate(pcs[:, :2]):
            for j, fb in enumerate(fcs[:, :2]):
                dists[i, j] = np.sum((pb - fb) ** 2)

        matches = {}
        while True:
            i, j = np.unravel_index(np.argmin(dists), dists.shape)
            if self.is_face_in_body(pbbs[i], fbbs[j]) and dists[i, j] < 99999999:
                matches[i] = j
                dists[i, :] = 99999999
                dists[:, j] = 99999999
            else:
                break
        return matches

    def is_face_in_body(self, body, face):
        x_check = body[0] <= face[0] and body[0] + body[2] >= face[0] + face[2]
        y_check = body[1] <= face[1] and body[1] + body[3] >= face[1] + face[3]
        return x_check and y_check

    def callback_track_pose(self, tracklets, poses):
        person_tracklets = [
            o for o in tracklets.objects if o.class_id == cfg.PERSON_CLASS
        ]
        objbbs = [o.location for o in person_tracklets]
        pbbs = [p.body_location for p in poses.persons]

        op_ious, op_match, unmatched_pose = self.bb_matching(
            objbbs, pbbs, self.iou_threshold
        )

        for p in poses.persons:
            p.instance_id = -1

        if op_ious is not None:
            for obj_idx, p_idx in op_match:
                o = person_tracklets[obj_idx]
                poses.persons[p_idx].instance_id = o.instance_id

        self.pub_poses.publish(poses)

        faces = self._pop_nearest(self.face_buffer, poses.header.stamp)
        if faces is None:
            self.apose_buffer.append(poses)
        else:
            self.associate_faces(poses, faces)

    def callback_face(self, faces):
        poses = self._pop_nearest(self.apose_buffer, faces.header.stamp)
        if poses is None:
            self.face_buffer.append(faces)
        else:
            self.associate_faces(poses, faces)

    def _stamp_ns(self, stamp):
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    def _pop_nearest(self, buffer, stamp):
        # pop the message whose stamp is closest to the given stamp (within slop)
        if len(buffer) == 0:
            return None
        t = self._stamp_ns(stamp)
        diffs = [abs(self._stamp_ns(m.header.stamp) - t) for m in buffer]
        idx = int(np.argmin(diffs))
        if diffs[idx] > self.face_slop_ns:
            self.get_logger().info(
                f"no face/pose pair within slop (nearest diff: {diffs[idx] / 1e9:.3f}s)",
                throttle_duration_sec=10.0,
            )
            return None
        msg = buffer[idx]
        del buffer[idx]
        return msg

    def associate_faces(self, poses, faces):
        pbbs = [p.body_location for p in poses.persons]
        fbbs = [p.face_location for p in faces.persons]

        face_body_matches = self.face_check(pbbs, fbbs)

        for f in faces.persons:
            f.instance_id = -1

        for p_idx, p in enumerate(poses.persons):
            if p_idx in face_body_matches:
                f_idx = face_body_matches[p_idx]
                faces.persons[f_idx].instance_id = p.instance_id

        self.pub_faces.publish(faces)


def main():
    rclpy.init()
    node = AssociationNode()
    rclpy.spin(node)
    rclpy.shutdown()
