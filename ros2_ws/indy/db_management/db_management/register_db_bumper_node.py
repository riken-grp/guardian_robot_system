#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import DBManager
from rclpy import qos
from .mongo_node_base import MongoDBNode
from std_msgs.msg import UInt8


class RegisterDBBumperNode(MongoDBNode):
    def __init__(self, name="RegisterDBBumperNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.physical_db = DBManager(mongo_uri, mongo_port, dbname, "physical_topic")
        self.last_bumper_time = None

        self.sub_dbg = self.create_subscription(
            UInt8,
            "in_bumper_topic",
            self.callback_bumper,
            qos_profile=qos.qos_profile_system_default,
        )

    def callback_bumper(self, bumper):
        val = bumper.data
        if val == 1:
            now = self.get_clock().now()
            if self.last_bumper_time is None or (now - self.last_bumper_time).nanoseconds >= 6e10:
                self.physical_db.insert("bumper", {"value": val}, priority=100)
                self.last_bumper_time = now


def main():
    rclpy.init()
    node = RegisterDBBumperNode()
    rclpy.spin(node)
    rclpy.shutdown()
