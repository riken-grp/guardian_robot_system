#!/usr/bin/env python
# coding: utf-8 -*-
"""Recognize whether each person has noticed the robot.

Combines the outputs of the other action recognition nodes, per instance_id:

- looking     : recog/person/looking_at   (StringStamped, json {id: 0/1})
- waving hand : recog/person/hand_waving  (StringStamped, json {id: 0/1})
- raising hand: recog/person/hand_state   (Pointings)
- approaching : computed here from the distance history of
                recog/person/pose/associated (body_location_sensor)

A person is "noticed" when any of the following holds:

- waving a hand
- raising a hand
- looking at the robot continuously for ``looking_min_sec``
- approaching the robot while looking at it

Once noticed, the state is kept for ``hold_sec`` after the last evidence so
that it does not flicker.

Persons farther than ``max_distance`` are not noticed.  The distance is the
latest valid-depth sample of body_location_sensor; if there is no sample
within ``stale_sec`` the distance is unknown (output ``-1``) and the person
is regarded as in range (a person without depth can still be noticed).

Cues for instance_id < 0 (not associated, several per frame possible) are
ignored.

Output: recog/person/noticed (StringStamped), json
    {instance_id: {"noticed": 0/1, "looking": bool, "looking_duration": float,
                   "waving_hand": bool, "raising_hand": bool,
                   "approaching": bool, "approach_speed": float,
                   "distance": float}}
"""

import json
import math
from collections import deque

import numpy as np
import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons, Pointings


class _PersonState:
    def __init__(self, maxlen):
        self.looking = (False, -math.inf)  # (value, received time)
        self.looking_since = None
        self.waving = (False, -math.inf)
        self.raising = (False, -math.inf)
        # (time, distance) samples within approach_window_sec (time ordered)
        self.distances = deque(maxlen=maxlen)
        self.last_distance = (-math.inf, -1.0)  # latest (time, distance)
        self.last_noticed = -math.inf
        self.last_seen = -math.inf


class NoticedRecognizer:
    """ROS-independent logic. All times are in seconds."""

    def __init__(
        self,
        stale_sec=1.0,
        looking_min_sec=1.0,
        approach_window_sec=1.5,
        approach_min_speed=0.2,
        approach_min_samples=5,
        max_distance=6.0,
        hold_sec=2.0,
        forget_sec=10.0,
    ):
        self.stale_sec = stale_sec
        self.looking_min_sec = looking_min_sec
        self.approach_window_sec = approach_window_sec
        self.approach_min_speed = approach_min_speed
        self.approach_min_samples = approach_min_samples
        self.max_distance = max_distance
        self.hold_sec = hold_sec
        self.forget_sec = forget_sec
        self.states = {}

    def _state(self, instance_id):
        if instance_id not in self.states:
            self.states[instance_id] = _PersonState(maxlen=300)
        return self.states[instance_id]

    # ---- inputs -----------------------------------------------------------
    def update_looking(self, instance_id, looking, now):
        if instance_id < 0:
            return
        s = self._state(instance_id)
        looking = bool(looking)
        fresh = now - s.looking[1] <= self.stale_sec
        if looking and (s.looking_since is None or not (s.looking[0] and fresh)):
            s.looking_since = now
        if not looking:
            s.looking_since = None
        s.looking = (looking, now)

    def update_waving(self, instance_id, waving, now):
        if instance_id < 0:
            return
        self._state(instance_id).waving = (bool(waving), now)

    def update_raising(self, instance_id, raising, now):
        if instance_id < 0:
            return
        self._state(instance_id).raising = (bool(raising), now)

    def update_distance(self, instance_id, location_sensor, now):
        if instance_id < 0:
            return
        s = self._state(instance_id)
        s.last_seen = now
        if len(location_sensor) < 3 or location_sensor[2] <= 0:
            return  # no valid depth
        d = math.hypot(location_sensor[0], location_sensor[2])
        s.distances.append((now, d))
        s.last_distance = (now, d)

    # ---- evaluation -------------------------------------------------------
    def _fresh(self, cue, now):
        value, t = cue
        return value and (now - t) <= self.stale_sec

    def _approach(self, s, now):
        """Return (approaching, speed [m/s, positive when approaching], distance).

        distance is -1 when there is no valid sample within stale_sec.
        """
        t_last, d_last = s.last_distance
        distance = d_last if now - t_last <= self.stale_sec else -1.0

        # samples are time ordered: drop the ones out of the window
        pts = s.distances
        while pts and now - pts[0][0] > self.approach_window_sec:
            pts.popleft()
        if len(pts) < self.approach_min_samples:
            return False, 0.0, distance
        if pts[-1][0] - pts[0][0] < self.approach_window_sec / 2:
            return False, 0.0, distance
        # least-squares slope of d(t) (same as np.polyfit(t, d, 1)[0])
        a = np.array(pts)
        t = a[:, 0] - a[:, 0].mean()
        d = a[:, 1] - a[:, 1].mean()
        slope = float(np.dot(t, d) / np.dot(t, t))
        speed = -slope
        return speed >= self.approach_min_speed, speed, distance

    def evaluate(self, instance_ids, now):
        results = {}
        for instance_id in instance_ids:
            if instance_id < 0:
                continue
            s = self._state(instance_id)
            looking = self._fresh(s.looking, now)
            looking_duration = (
                now - s.looking_since if looking and s.looking_since is not None else 0.0
            )
            waving = self._fresh(s.waving, now)
            raising = self._fresh(s.raising, now)
            approaching, speed, distance = self._approach(s, now)

            # unknown distance (-1) is regarded as in range
            in_range = distance < 0 or distance <= self.max_distance
            evidence = in_range and (
                waving
                or raising
                or looking_duration >= self.looking_min_sec
                or (approaching and looking)
            )
            if evidence:
                s.last_noticed = now
            noticed = now - s.last_noticed <= self.hold_sec

            results[instance_id] = {
                "noticed": int(noticed),
                "looking": looking,
                "looking_duration": float(looking_duration),
                "waving_hand": waving,
                "raising_hand": raising,
                "approaching": approaching,
                "approach_speed": speed,
                "distance": float(distance),
            }
        self._forget(now)
        return results

    def _forget(self, now):
        for instance_id in list(self.states.keys()):
            s = self.states[instance_id]
            last = max(s.last_seen, s.looking[1], s.waving[1], s.raising[1])
            if now - last > self.forget_sec:
                del self.states[instance_id]


class NoticedNode(Node):
    def __init__(self, name="NoticedNode"):
        super().__init__(name)

        params = {
            "stale_sec": 1.0,
            "looking_min_sec": 1.0,
            "approach_window_sec": 1.5,
            "approach_min_speed": 0.2,
            "approach_min_samples": 5,
            "max_distance": 6.0,
            "hold_sec": 2.0,
            "forget_sec": 10.0,
        }
        for k, v in params.items():
            self.declare_parameter(k, v)
        kwargs = {k: self.get_parameter(k).value for k in params}
        self.get_logger().info(f"NoticedRecognizer parameters: {kwargs}")
        self.recognizer = NoticedRecognizer(**kwargs)

        sdq = qos.qos_profile_system_default
        self.pub = self.create_publisher(StringStamped, "out_topic", qos_profile=sdq)
        self.create_subscription(Persons, "in_person_topic", self.callback_person, sdq)
        self.create_subscription(
            StringStamped, "in_lookingat_topic", self.callback_lookingat, sdq
        )
        self.create_subscription(
            StringStamped, "in_hand_waving_topic", self.callback_hand_waving, sdq
        )
        self.create_subscription(Pointings, "in_hand_topic", self.callback_hand, sdq)

    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _parse(self, msg):
        try:
            return {int(k): v for k, v in json.loads(msg.data).items()}
        except (ValueError, AttributeError) as e:
            self.get_logger().warn(f"Failed to parse json: {e}")
            return {}

    def callback_lookingat(self, msg):
        now = self._now()
        for instance_id, v in self._parse(msg).items():
            self.recognizer.update_looking(instance_id, int(v) == 1, now)

    def callback_hand_waving(self, msg):
        now = self._now()
        for instance_id, v in self._parse(msg).items():
            self.recognizer.update_waving(instance_id, int(v) == 1, now)

    def callback_hand(self, msg):
        now = self._now()
        for p in msg.pointings:
            self.recognizer.update_raising(
                p.instance_id, p.raising_left_hand or p.raising_right_hand, now
            )

    def callback_person(self, persons):
        now = self._now()
        ids = []
        for p in persons.persons:
            if p.instance_id < 0:
                continue
            ids.append(int(p.instance_id))
            self.recognizer.update_distance(
                int(p.instance_id), list(p.body_location_sensor), now
            )
        results = self.recognizer.evaluate(ids, now)

        msg = StringStamped()
        msg.header = persons.header
        msg.data = json.dumps({str(k): v for k, v in results.items()})
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = NoticedNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
