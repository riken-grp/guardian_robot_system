#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import PhysicalDBWriter

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode


class CheckWheelChairNode(MongoDBNode):
    def __init__(self, name="CheckWheelChairNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.physical_db_wheelchair = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "wheelchair"
        )

        self.timer = self.create_timer(0.5, self.timer_callback)

    def timer_callback(self):
        ret = self.dbmanager.tracking_db.find(
            {"wheelchair.sitting": True},
        )
        for r in ret:
            self.update(self.physical_db_wheelchair, "wheelchair", r)

    def update(self, db, event, contents):
        query = {"contents.instance_id": contents["instance_id"], "event": event}
        if db.db.find_one(query) is None:
            db.insert(contents, priority=100)


def main():
    rclpy.init()
    node = CheckWheelChairNode()
    rclpy.spin(node)
    rclpy.shutdown()
