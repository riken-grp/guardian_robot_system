#!/usr/bin/env python
# coding: utf-8 -*-
import datetime

import message_filters
import numpy as np
import rclpy
from .mongo_node_base import MongoDBNode

from .dbmanager import TopicDBManager


class RegisterDBNode(MongoDBNode):
    def __init__(self, name="RegisterDBNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.timer = self.create_timer(1, self.callback_timer)

    def callback_timer(self):
        self.dbmanager.step_physical_db()
        self.dbmanager.step_cyber_db()


def main():
    rclpy.init()
    node = RegisterDBNode()
    rclpy.spin(node)
    rclpy.shutdown()
