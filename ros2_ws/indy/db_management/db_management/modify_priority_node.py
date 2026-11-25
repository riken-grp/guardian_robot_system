#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from .mongo_node_base import MongoDBNode

from .dbmanager import TopicDBManager


class ModifyPriorityNode(MongoDBNode):
    """physical_topic / cyber_topic の全イベントの priority を毎秒 1 減らし，0 未満を消す."""

    def __init__(self, name="ModifyPriorityNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.timer = self.create_timer(1, self.callback_timer)

    def callback_timer(self):
        self.dbmanager.step_physical_db()
        self.dbmanager.step_cyber_db()


def main():
    rclpy.init()
    node = ModifyPriorityNode()
    rclpy.spin(node)
    rclpy.shutdown()
