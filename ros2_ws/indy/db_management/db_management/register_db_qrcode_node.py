#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from .mongo_node_base import MongoDBNode

from .dbmanager import TopicDBManager


class RegisterDBQRCodeNode(MongoDBNode):
    def __init__(self, name="RegisterDBQRCodeNode"):
        super().__init__(name)
        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.subscription = self.create_subscription(
            StringStamped,  # メッセージ型
            "in_qrcode_topic",  # トピック名
            self.qrcode_callback,  # コールバック関数
            qos_profile=qos.qos_profile_system_default,
        )

    def qrcode_callback(self, qrcode):
        try:
            qrcode_data = json.loads(qrcode.data)
            self.dbmanager.insert_qrcode(qrcode_data, priority=60)

        except json.JSONDecodeError as e:
            self.get_logger().error(f"Failed to decode QR code data: {e}")


def main():
    rclpy.init()
    node = RegisterDBQRCodeNode()
    rclpy.spin(node)
    rclpy.shutdown()
