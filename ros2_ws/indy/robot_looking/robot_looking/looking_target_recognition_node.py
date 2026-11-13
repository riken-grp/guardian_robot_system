#!/usr/bin/env python
# coding: utf-8 -*-
"""Decide which target the robot should look at.

Priority:
1. While the human tracker reports voice activity, the speaking person
   (audio path, recog from human_tracker/audio_info).
2. The person who spoke most recently (new "asr" observation in the Actions
   collection, not older than ``asr_max_age``).
3. The current target, while it is still tracked (count > unobserve_threshold)
   and for at most ``max_duration`` seconds.
4. The largest tracked person (or object if no person is tracked).  After
   ``max_duration`` another target is preferred when there is one.

The audio path (AudioInfo: x, y in mm in the robot frame) is only used to
decide *who* speaks; the location is taken from the tracking collection
(``face_location_sensor`` / ``location_sensor``) by the instance_id, so that
both paths output the sensor frame.  A speaker without a tracked instance is
ignored (the visual path continues).  When no AudioInfo has been received for
``vad_timeout`` seconds, the voice activity is considered finished.

Output: recog/robot_looking_target (StringStamped), json
    {"instance_id", "type", "class_id", "name", "location", "start_time"}
``location`` is the face (or body) location in the sensor frame.
"""

import datetime
import json
import time

import rclpy
from common_msgs.msg import StringStamped
from human_tracker_msgs.msg import AudioInfoList
from pymongo import ASCENDING, DESCENDING, MongoClient
from rclpy import qos
from rclpy.node import Node

# fields read from the tracking collection
TRACKING_PROJECTION = {
    "_id": 0,
    "instance_id": 1,
    "class_id": 1,
    "name": 1,
    "location": 1,
    "location_sensor": 1,
    "face_location_sensor": 1,
    "count": 1,
}


def _area(target):
    loc = target.get("location") or []
    return loc[2] * loc[3] if len(loc) >= 4 else 0.0


class LookingTargetRecognizer:
    def __init__(
        self,
        tracking_db,
        action_db,
        max_duration,
        unobserve_threshold,
        asr_max_age=5.0,
        clock=time.time,
    ):
        self.tracking_db = tracking_db
        self.action_db = action_db
        self.max_duration = max_duration
        self.unobserve_threshold = unobserve_threshold
        self.asr_max_age = asr_max_age
        self.clock = clock

        self.current_target_id = None
        self.start_time = None
        self.last_talking_id = None  # _id of the last processed asr observation
        self.expired_id = None  # target looked at for max_duration

    def _reset(self):
        self.current_target_id = None
        self.start_time = None

    def lookup(self, instance_id):
        """Tracked target by instance_id (None if not tracked)."""
        if instance_id is None or instance_id < 0:
            return None
        return self.tracking_db.find_one({"instance_id": instance_id}, TRACKING_PROJECTION)

    def focus(self, instance_id, now=None):
        """Make instance_id the current target (e.g. the speaker of the audio path)."""
        if instance_id != self.current_target_id:
            self.current_target_id = instance_id
            self.start_time = self.clock() if now is None else now

    def _select(self, target, now, keep_start_time=False):
        if not keep_start_time or self.start_time is None:
            self.start_time = now
        self.current_target_id = target["instance_id"]
        target["start_time"] = self.start_time
        return target

    def _new_talking_target(self):
        """instance_id of a new (not yet processed) and recent asr observation."""
        talking = self.action_db.find_one(
            {"command": "observation", "found.event": "asr"},
            projection={"found.contents.instance_id": 1},
            sort=[("inserted", DESCENDING)],
        )
        if talking is None or talking["_id"] == self.last_talking_id:
            return None
        self.last_talking_id = talking["_id"]

        # ObjectId holds its (UTC) creation time, independent of the
        # timezone handling of the "inserted" field
        gen_time = getattr(talking["_id"], "generation_time", None)
        if gen_time is not None and self.asr_max_age > 0:
            age = datetime.datetime.now(datetime.timezone.utc) - gen_time
            if age.total_seconds() > self.asr_max_age:
                return None
        try:
            return talking["found"]["contents"]["instance_id"]
        except (KeyError, TypeError):
            return None

    def __call__(self):
        now = self.clock()
        if self.start_time is not None and now - self.start_time > self.max_duration:
            self.expired_id = self.current_target_id
            self._reset()

        # tracked persons; fall back to all tracked targets (objects)
        targets = list(self.tracking_db.find({"class_id": 0}, TRACKING_PROJECTION))
        if len(targets) == 0:
            targets = list(self.tracking_db.find({}, TRACKING_PROJECTION))
        targets = [t for t in targets if t.get("instance_id", -1) >= 0]
        if len(targets) == 0:
            self._reset()
            return None
        tracking_targets = {t["instance_id"]: t for t in targets}

        # a person who has just spoken
        talking_id = self._new_talking_target()
        if talking_id is not None and talking_id in tracking_targets:
            return self._select(tracking_targets[talking_id], now)

        # keep the current target while it is still observed
        current = tracking_targets.get(self.current_target_id)
        if current is not None and current.get("count", 0) > self.unobserve_threshold:
            return self._select(current, now, keep_start_time=True)

        # otherwise the largest target, preferring another one than the target
        # that has just been looked at for max_duration
        candidates = [t for t in targets if t["instance_id"] != self.expired_id] or targets
        self.expired_id = None
        return self._select(max(candidates, key=_area), now)


class LookingTargetRecognizerFromAudio:
    def __init__(self, max_duration, clock=time.time):
        self.max_duration = max_duration
        self.clock = clock
        self.current_human_id = None
        self.start_time = None

    def __call__(self, htl):
        now = self.clock()
        if self.start_time is not None and now - self.start_time > self.max_duration:
            self.current_human_id = None

        speaking = {ht.human_id: ht for ht in htl.info if ht.vad != 0}
        if len(speaking) == 0:
            self.current_human_id = None
            self.start_time = None
            return False, None

        if self.current_human_id in speaking:
            s = speaking[self.current_human_id]
        else:
            # the loudest speaker
            s = max(speaking.values(), key=lambda ht: ht.power)
            self.current_human_id = s.human_id
            self.start_time = now

        # x, y, z are in the robot frame (mm); the location is resolved from
        # the tracking collection by the node
        target = {
            "instance_id": int(s.instance_id),
            "human_id": int(s.human_id),
            "class_id": 0,
            "name": s.person_name or "person",
            "start_time": self.start_time,
        }
        return True, target


class LookingTargetNode(Node):
    def __init__(self, name="LookingTargetNode"):
        super().__init__(name)

        self.declare_parameter("mongo_uri", "")
        self.declare_parameter("mongo_port", 9010)
        self.declare_parameter("dbname", "tBlackBoard")
        self.declare_parameter("max_duration", 60)
        self.declare_parameter("unobserve_threshold", 70)
        self.declare_parameter("asr_max_age", 5.0)
        self.declare_parameter("period", 0.1)
        self.declare_parameter("vad_timeout", 1.0)
        mongo_uri = self.get_parameter("mongo_uri").value
        mongo_port = int(self.get_parameter("mongo_port").value)
        if mongo_port <= 1:
            mongo_port = 9010
        dbname = self.get_parameter("dbname").value or "tBlackBoard"
        max_duration = self.get_parameter("max_duration").value
        unobserve_threshold = self.get_parameter("unobserve_threshold").value
        asr_max_age = float(self.get_parameter("asr_max_age").value)
        period = float(self.get_parameter("period").value)
        self.vad_timeout = float(self.get_parameter("vad_timeout").value)
        self.period = period

        # short timeouts: a DB outage must not block the executor for 30 s
        self.client = MongoClient(
            mongo_uri, mongo_port, serverSelectionTimeoutMS=2000, socketTimeoutMS=2000
        )
        tracking_db = self.client[dbname].tracking
        action_db = self.client[dbname].Actions
        self._ensure_indexes(tracking_db, action_db)

        self.vad = False
        self.last_vad_time = 0.0  # monotonic time of the last resolved speaker
        self.last_audio_publish = 0.0
        self.lt_recognizer = LookingTargetRecognizer(
            tracking_db, action_db, max_duration, unobserve_threshold, asr_max_age
        )
        self.lt_recognizer_from_audio = LookingTargetRecognizerFromAudio(max_duration)
        self.pub = self.create_publisher(
            StringStamped, "out_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub = self.create_subscription(
            AudioInfoList,
            "in_humantracker_topic",
            qos_profile=qos.qos_profile_system_default,
            callback=self.ros_callback,
        )

        self.timer = self.create_timer(period, self.callback)

    def _ensure_indexes(self, tracking_db, action_db):
        try:
            tracking_db.create_index([("class_id", ASCENDING)])
            action_db.create_index(
                [("command", ASCENDING), ("found.event", ASCENDING), ("inserted", DESCENDING)]
            )
        except Exception as e:  # never fail startup because of indexes
            self.get_logger().warn(f"Failed to create indexes: {e}")

    def callback(self):
        if self.vad and time.monotonic() - self.last_vad_time < self.vad_timeout:
            return  # the audio path is publishing
        self.vad = False
        try:
            target = self.lt_recognizer()
        except Exception as e:
            self.get_logger().error(
                f"Failed to read the blackboard: {e}", throttle_duration_sec=5.0
            )
            return

        if target is not None:
            self.publish(target)

    def ros_callback(self, htl):
        vad, target = self.lt_recognizer_from_audio(htl)
        tracked = None
        if vad and target is not None:
            try:
                tracked = self.lt_recognizer.lookup(target["instance_id"])
            except Exception as e:
                self.get_logger().error(
                    f"Failed to read the blackboard: {e}", throttle_duration_sec=5.0
                )
        if tracked is None:
            # nobody speaks, or the speaker is not tracked: visual path
            self.vad = False
            return

        now = time.monotonic()
        self.vad = True
        self.last_vad_time = now
        # keep looking at the speaker after the speech
        self.lt_recognizer.focus(target["instance_id"])
        if now - self.last_audio_publish < self.period:
            return  # AudioInfo may arrive faster than needed
        self.last_audio_publish = now
        tracked.update(target)
        self.publish(tracked)

    def publish(self, target):
        result = StringStamped()
        result.header.stamp = self.get_clock().now().to_msg()
        result.header.frame_id = ""

        data = {}
        data["instance_id"] = target["instance_id"]
        data["type"] = "person" if target.get("class_id") == 0 else "object"
        data["class_id"] = target.get("class_id")
        data["name"] = target.get("name", "")
        face = target.get("face_location_sensor") or []
        if len(face) >= 3 and sum(map(abs, face)) != 0:
            data["location"] = list(face)
        else:
            data["location"] = list(target.get("location_sensor") or [])
        if len(data["location"]) < 3:
            return  # consumers read location[0..2]
        data["start_time"] = target["start_time"]
        if "human_id" in target:
            data["human_id"] = target["human_id"]

        result.data = json.dumps(data)
        self.pub.publish(result)


def main():
    rclpy.init()
    node = LookingTargetNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
