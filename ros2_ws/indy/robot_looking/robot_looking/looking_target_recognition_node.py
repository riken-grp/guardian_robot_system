#!/usr/bin/env python
# coding: utf-8 -*-

import json
import random
import time

import rclpy
from common_msgs.msg import StringStamped
from human_tracker_msgs.msg import AudioInfoList
from pymongo import DESCENDING, MongoClient
from rclpy import qos
from rclpy.clock import Clock
from rclpy.node import Node
from std_msgs.msg import Header


class LookingTargetRecognizer:
    def __init__(self, uri, port, dbname, max_duration, unobserve_threshold):
        self.current_target_id = None
        self.start_time = None
        self.client = MongoClient(uri, port)
        self.max_duration = max_duration
        self.unobserve_threshold = unobserve_threshold
        self.tracking_db = self.client[dbname].tracking
        self.action_db = self.client[dbname].Actions

    def __call__(self):
        if (
            self.start_time is not None
            and self.start_time + self.max_duration < time.time()
        ):
            self.current_target_id = None

        # find tracking target
        targets = list(self.tracking_db.find({"class_id": 0}))

        # if there is no tracking target, find all targets
        if len(targets) == 0:
            targets = list(self.tracking_db.find())

        # if there is no target, return None
        if len(targets) == 0:
            return None

        # sort by instance_id
        tracking_targets = {t["instance_id"]: t for t in targets if t != -1}

        # find talking person
        talking = self.action_db.find_one(
            {"command": "observation", "found.event": "asr"},
            sort=[("inserted", DESCENDING)],
        )

        # if there is a talking person, return it
        if talking is not None:
            target_id = talking["found"]["contents"]["instance_id"]
            if target_id in tracking_targets and target_id != self.current_target_id:
                target = tracking_targets[target_id]
                target["start_time"] = time.time()
                self.current_target_id = target_id
                self.start_time = target["start_time"]
                return target

        # if current target is still tracking, return it
        if (
            self.current_target_id is not None
            and self.current_target_id in tracking_targets
        ):
            if (
                tracking_targets[self.current_target_id]["count"]
                > self.unobserve_threshold
            ):
                t = tracking_targets[self.current_target_id]
                t["start_time"] = self.start_time
                return t
            else:
                self.current_target_id = None
                self.start_time = None
        else:
            self.current_target_id = None
            self.start_time = None

        # if there is only one target, return it
        if len(targets) == 1:
            t = targets[0]
            self.current_target_id = t["instance_id"]
            t["start_time"] = time.time()
            self.start_time = t["start_time"]
            return t

        # sort by size
        tracking_target_ids = sorted(
            targets, key=lambda x: x["location"][2] * x["location"][3], reverse=True
        )
        # return the largest target
        target = tracking_target_ids[0]
        target["start_time"] = time.time()
        self.current_target_id = target["instance_id"]
        self.start_time = target["start_time"]

        return target


class LookingTargetRecognizerFromAduio:
    def __init__(self, max_duration):
        self.current_target_id = None
        self.start_time = None
        self.max_duration = max_duration

    def __call__(self, htl):
        if (
            self.start_time is not None
            and self.start_time + self.max_duration < time.time()
        ):
            self.current_target_id = None

        speaking = {i: ht for i, ht in enumerate(htl.info) if ht.vad != 0}
        self.vad = len(speaking) != 0
        if not self.vad:
            self.current_target_id = None
            self.start_time = None
            return False, None

        target = {}
        if self.current_target_id in speaking:
            s = speaking[self.current_target_id]
            target["instance_id"] = 0
            target["type"] = "person"
            target["class_id"] = 0
            target["name"] = "person"
            target["location_sensor"] = [s.x, s.y, s.z]
            target["start_time"] = self.start_time
            return True, target
        else:
            self.current_target_id = None
            self.start_time = None

        pid, s = random.choice(list(speaking.items()))
        self.current_target_id = pid
        self.start_time = time.time()
        target["instance_id"] = pid
        target["type"] = "person"
        target["class_id"] = 0
        target["name"] = "person"
        target["location_sensor"] = [s.x, s.y, s.z]
        target["start_time"] = self.start_time
        return True, target


class LookingTargetNode(Node):
    def __init__(self, name="LookingTargetNode"):
        super().__init__(name)

        self.declare_parameter("mongo_uri", "")
        self.declare_parameter("mongo_port", 9010)
        self.declare_parameter("dbname", "tBlackBoard")
        self.declare_parameter("max_duration", 60)
        self.declare_parameter("unobserve_threshold", 70)
        mongo_uri = self.get_parameter("mongo_uri").value
        mongo_port = self.get_parameter("mongo_port").value
        dbname = self.get_parameter("dbname").value
        max_duration = self.get_parameter("max_duration").value
        unobserve_threshold = self.get_parameter("unobserve_threshold").value

        self.vad = False
        self.lt_recognizer = LookingTargetRecognizer(
            mongo_uri, mongo_port, dbname, max_duration, unobserve_threshold
        )
        self.lt_recognizer_from_audio = LookingTargetRecognizerFromAduio(max_duration)
        self.pub = self.create_publisher(
            StringStamped, "out_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub = self.create_subscription(
            AudioInfoList,
            "in_humantracker_topic",
            qos_profile=qos.qos_profile_system_default,
            callback=self.ros_callback,
        )

        self.timer = self.create_timer(0.1, self.callback)

    def callback(self):
        if self.vad:
            return
        target = self.lt_recognizer()

        if target is not None:
            self.publish(target)

    def ros_callback(self, htl):
        self.vad, target = self.lt_recognizer_from_audio(htl)

        if not self.vad:
            return

        if target is not None:
            self.publish(target)

    def publish(self, target):
        result = StringStamped()
        result.header = Header()
        result.header.stamp = Clock().now().to_msg()
        result.header.frame_id = ""

        data = {}
        data["instance_id"] = target["instance_id"]
        data["type"] = "person" if target["class_id"] == 0 else "object"
        data["class_id"] = target["class_id"]
        data["name"] = target["name"]
        if (
            "face_location_sensor" in target
            and sum(map(abs, target["face_location_sensor"])) != 0
        ):
            data["location"] = target["face_location_sensor"]
        else:
            data["location"] = target["location_sensor"]
        data["start_time"] = target["start_time"]

        result.data = json.dumps(data)
        self.pub.publish(result)


def main():
    rclpy.init()
    node = LookingTargetNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
