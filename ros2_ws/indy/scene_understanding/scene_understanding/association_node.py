#!/usr/bin/env python
# coding: utf-8 -*-
"""tracked object / body pose / face の対応付けノード.

各トピックを stamp 付きでバッファに貯め、出力はそれぞれ自分のメッセージ起点で 1 回だけ行う。
- pose/associated : pose 1 件ごと。同時刻の tracked から instance_id を付ける
- face/associated : face 1 件ごと。同時刻の (instance_id 付き) pose を参照して instance_id を付ける
相手メッセージは参照するだけで pop しないので、複数から参照されても重複出力は起きない。

確定タイミング:
- stamp が完全一致する相手があれば即確定 (同じ画像フレームを処理した結果)
- なければ相手トピックの最新 stamp が t + slop を超える (= 候補が出揃う) か、
  match_timeout 経過で slop 以内の最近傍に確定
"""
import datetime
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np
import rclpy
from pymongo import MongoClient
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Objects, Persons, Relations

from . import configs as cfg


@dataclass
class _Pending:
    stamp: int  # ns
    msg: object
    arrival: float  # time.monotonic()


class _MatchStats:
    """照合結果を集計し、一定間隔でログに出す."""

    KEYS = (
        "track_in",
        "pose_in",
        "pose_exact",
        "pose_approx",
        "pose_no_track",
        "face_in",
        "face_exact",
        "face_approx",
        "face_no_pose",
    )

    def __init__(self):
        self.reset(time.monotonic())

    def reset(self, now):
        self.t_start = now
        self.cnt = dict.fromkeys(self.KEYS, 0)
        self.delay = {"pose": [], "face": []}
        self.miss_diff = {"pose": [], "face": []}

    @staticmethod
    def _summary(values, scale=1e3):
        if not values:
            return "-"
        return f"avg={np.mean(values) * scale:.0f}ms max={np.max(values) * scale:.0f}ms"

    def format(self, now, n_pending_pose, n_pending_face):
        c = self.cnt
        elapsed = now - self.t_start
        pose_out = c["pose_exact"] + c["pose_approx"]
        face_out = c["face_exact"] + c["face_approx"]
        return (
            f"[assoc {elapsed:.0f}s] "
            f"track in={c['track_in']} | "
            f"pose in={c['pose_in']} out={pose_out} "
            f"(exact={c['pose_exact']} approx={c['pose_approx']} no_track={c['pose_no_track']}) "
            f"delay {self._summary(self.delay['pose'])} "
            f"miss_diff {self._summary(self.miss_diff['pose'])} | "
            f"face in={c['face_in']} out={face_out} "
            f"(exact={c['face_exact']} approx={c['face_approx']} no_pose={c['face_no_pose']}) "
            f"delay {self._summary(self.delay['face'])} "
            f"miss_diff {self._summary(self.miss_diff['face'])} | "
            f"pending pose={n_pending_pose} face={n_pending_face}"
        )


_WAIT = object()


class AssociationNode(Node):
    def __init__(self, name="RegisterDBNode"):
        super().__init__(name)
        self._declare_parameters()
        self._initialize_components()
        self._initialize_publishers_and_subscribers()

    def _declare_parameters(self):
        # IoU threshold for matching boxes of two different models (tracker vs
        # pose); 0.9 was too strict after tracker smoothing
        self.declare_parameter("iou_threshold", 0.5)
        # tracked <-> pose の許容 stamp 差 [s] (旧 ApproximateTimeSynchronizer の slop)
        self.declare_parameter("track_slop", 0.2)
        # pose <-> face の許容 stamp 差 [s]
        self.declare_parameter("face_slop", 0.2)
        # 相手が出揃わなくても確定させるまでの待ち時間 [s]
        self.declare_parameter("match_timeout", 3.0)
        # 参照用に保持する期間 [s] (最新 stamp からこれより古いものは捨てる)
        self.declare_parameter("buffer_duration", 10.0)
        self.declare_parameter("stats_period", 10.0)

    def _initialize_components(self):
        self.iou_threshold = self.get_parameter("iou_threshold").value
        self.track_slop_ns = int(self.get_parameter("track_slop").value * 1e9)
        self.face_slop_ns = int(self.get_parameter("face_slop").value * 1e9)
        self.match_timeout = float(self.get_parameter("match_timeout").value)
        self.buffer_ns = int(self.get_parameter("buffer_duration").value * 1e9)
        self.stats_period = float(self.get_parameter("stats_period").value)

        self.tracking = {}

        self._reset_buffers()
        self.stats = _MatchStats()

    def _reset_buffers(self):
        # 参照専用 (pop しない。古いものは _prune で捨てる)
        self.tracks = deque()  # (stamp_ns, Objects)
        self.resolved_poses = deque()  # (stamp_ns, Persons with instance_id)
        # 確定待ち
        self.pending_poses = []  # [_Pending(Persons)]
        self.pending_faces = []  # [_Pending(Persons)]
        # 各トピックで受信した最新 stamp
        self.latest_track_ns = None
        self.latest_pose_ns = None
        self.latest_face_ns = None

    def _initialize_publishers_and_subscribers(self):
        self.pub_poses = self.create_publisher(
            Persons, "out_person_topic", qos_profile=qos.qos_profile_system_default
        )
        self.pub_faces = self.create_publisher(
            Persons, "out_face_topic", qos_profile=qos.qos_profile_system_default
        )

        self.sub_track = self.create_subscription(
            Objects,
            "in_track_topic",
            self.callback_track,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_pose = self.create_subscription(
            Persons,
            "in_person_topic",
            self.callback_pose,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_face = self.create_subscription(
            Persons,
            "in_face_topic",
            self.callback_face,
            qos_profile=qos.qos_profile_system_default,
        )

        # タイムアウト処理・古いバッファの削除用 (コールバックと同じスレッドで動くのでロック不要)
        self.create_timer(0.05, self._process)
        self.create_timer(self.stats_period, self._log_stats)

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

        # squared distances between body "head" points and face centers (P, F)
        dists = np.sum((pcs[:, None, :] - fcs[None, :, :]) ** 2, axis=2).astype(
            np.float64
        )

        # greedy matching; a closest pair whose face is not inside the body is
        # only excluded (the other pairs remain candidates)
        matches = {}
        while np.isfinite(dists).any():
            i, j = np.unravel_index(np.argmin(dists), dists.shape)
            if self.is_face_in_body(pbbs[i], fbbs[j]):
                matches[int(i)] = int(j)
                dists[i, :] = np.inf
                dists[:, j] = np.inf
            else:
                dists[i, j] = np.inf
        return matches

    def is_face_in_body(self, body, face):
        x_check = body[0] <= face[0] and body[0] + body[2] >= face[0] + face[2]
        y_check = body[1] <= face[1] and body[1] + body[3] >= face[1] + face[3]
        return x_check and y_check


    # ------------------------------------------------------------------
    # 受信: バッファに積んで処理を試みるだけ
    # ------------------------------------------------------------------
    def callback_track(self, tracklets):
        t = self._stamp_ns(tracklets.header.stamp)
        self._check_time_jump(self.latest_track_ns, t)
        self.stats.cnt["track_in"] += 1
        self.tracks.append((t, tracklets))
        self.latest_track_ns = self._max(self.latest_track_ns, t)
        self._process()

    def callback_pose(self, poses):
        t = self._stamp_ns(poses.header.stamp)
        self._check_time_jump(self.latest_pose_ns, t)
        self.stats.cnt["pose_in"] += 1
        self.pending_poses.append(_Pending(t, poses, time.monotonic()))
        self.latest_pose_ns = self._max(self.latest_pose_ns, t)
        self._process()

    def callback_face(self, faces):
        t = self._stamp_ns(faces.header.stamp)
        self._check_time_jump(self.latest_face_ns, t)
        self.stats.cnt["face_in"] += 1
        self.pending_faces.append(_Pending(t, faces, time.monotonic()))
        self.latest_face_ns = self._max(self.latest_face_ns, t)
        self._process()

    # ------------------------------------------------------------------
    # 確定処理
    # ------------------------------------------------------------------
    def _process(self):
        now = time.monotonic()
        # pose を先に確定させる (face は instance_id 付きの pose を参照するため)
        self.pending_poses = [p for p in self.pending_poses if not self._try_pose(p, now)]
        self.pending_faces = [f for f in self.pending_faces if not self._try_face(f, now)]
        self._prune()

    def _try_pose(self, p, now):
        """pose を確定できたら True (publish 済み or 破棄)."""
        track = self._find_exact(self.tracks, p.stamp)
        kind = "exact"
        if track is None:
            timed_out = now - p.arrival > self.match_timeout
            complete = (
                self.latest_track_ns is not None
                and self.latest_track_ns > p.stamp + self.track_slop_ns
            )
            if not (complete or timed_out):
                return False
            diff, track = self._nearest(self.tracks, p.stamp)
            kind = "approx"
            if track is None or diff > self.track_slop_ns:
                # 旧実装 (ApproximateTimeSynchronizer) 同様、tracked が無い pose は出力しない
                self.stats.cnt["pose_no_track"] += 1
                if diff is not None:
                    self.stats.miss_diff["pose"].append(diff / 1e9)
                return True

        self.stats.cnt[f"pose_{kind}"] += 1
        self.stats.delay["pose"].append(now - p.arrival)
        self._annotate_pose(track, p.msg)
        self.pub_poses.publish(p.msg)
        self.resolved_poses.append((p.stamp, p.msg))
        return True

    def _try_face(self, f, now):
        """face を確定できたら True (publish 済み or 破棄)."""
        poses = self._find_exact(self.resolved_poses, f.stamp)
        kind = "exact"
        if poses is None:
            timed_out = now - f.arrival > self.match_timeout
            if not timed_out:
                # 完全一致の pose がまだ確定待ちなら待つ
                if any(p.stamp == f.stamp for p in self.pending_poses):
                    return False
                # slop 内の pose が確定待ち、または pose 側の候補が出揃っていなければ待つ
                if any(
                    abs(p.stamp - f.stamp) <= self.face_slop_ns
                    for p in self.pending_poses
                ):
                    return False
                complete = (
                    self.latest_pose_ns is not None
                    and self.latest_pose_ns > f.stamp + self.face_slop_ns
                )
                if not complete:
                    return False
            diff, poses = self._nearest(self.resolved_poses, f.stamp)
            kind = "approx"
            if poses is None or diff > self.face_slop_ns:
                # 旧実装同様、対応する pose が無い face は出力しない
                self.stats.cnt["face_no_pose"] += 1
                if diff is not None:
                    self.stats.miss_diff["face"].append(diff / 1e9)
                return True

        self.stats.cnt[f"face_{kind}"] += 1
        self.stats.delay["face"].append(now - f.arrival)
        self.associate_faces(poses, f.msg)
        return True

    def _annotate_pose(self, tracklets, poses):
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

    # ------------------------------------------------------------------
    # バッファ管理
    # ------------------------------------------------------------------
    def _prune(self):
        latest = [
            t
            for t in (self.latest_track_ns, self.latest_pose_ns, self.latest_face_ns)
            if t is not None
        ]
        if not latest:
            return
        horizon = max(latest) - self.buffer_ns
        for buf in (self.tracks, self.resolved_poses):
            while buf and buf[0][0] < horizon:
                buf.popleft()

    def _check_time_jump(self, latest, t):
        # rosbag のループ再生などで stamp が大きく巻き戻ったらバッファを捨てる
        if latest is not None and t < latest - self.buffer_ns:
            self.get_logger().warn(
                f"timestamp jumped back by {(latest - t) / 1e9:.1f}s; clearing buffers"
            )
            self._reset_buffers()

    def _log_stats(self):
        now = time.monotonic()
        self.get_logger().info(
            self.stats.format(now, len(self.pending_poses), len(self.pending_faces))
        )
        self.stats.reset(now)

    @staticmethod
    def _stamp_ns(stamp):
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    @staticmethod
    def _max(a, b):
        return b if a is None else max(a, b)

    @staticmethod
    def _find_exact(buf, t):
        for s, msg in reversed(buf):
            if s == t:
                return msg
        return None

    @staticmethod
    def _nearest(buf, t):
        """(stamp 差 ns, msg) を返す。空なら (None, None)."""
        best_diff, best = None, None
        for s, msg in buf:
            d = abs(s - t)
            if best_diff is None or d < best_diff:
                best_diff, best = d, msg
        return best_diff, best

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
