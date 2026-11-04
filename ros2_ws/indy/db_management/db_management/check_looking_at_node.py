#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import PhysicalDBWriter

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode


class CheckLookingAt(MongoDBNode):
    def __init__(self, name="CheckLookingAt"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.physical_db_looking = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "looking"
        )
        self.physical_db_long_looking = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "long_looking"
        )
        self.physical_db_many_looking = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "many_looking"
        )

        self.timer = self.create_timer(0.5, self.timer_callback)

    def timer_callback(self):
        self._looking_num_person_based(
            target=1, num_person=5, duration=10, event="many_looking"
        )
        self._looking_num_person_based(
            target=2, num_person=5, duration=10, event="many_looking"
        )
        self._looking_time_based(target=1, duration=1, event="looking")
        self._looking_time_based(target=1, duration=10, event="long_looking")
        self._looking_time_based(target=2, duration=1, event="looking")
        self._looking_time_based(target=2, duration=10, event="long_looking")

    def _looking_num_person_based(self, target, num_person, duration, event):
        current_person = self.dbmanager.tracking_db.count_documents(
            {"looking_at.target": target, "looking_at.life": {"$gt": duration}}
        )
        if current_person >= num_person:
            # self.get_logger().info('たくさんの人がDJ Leeを見てる')
            self.update(
                self.physical_db_many_looking,
                "many_looking",
                {"target": target, "num_person": current_person},
            )

    def _looking_time_based(self, target, duration, event):
        ret = self.dbmanager.tracking_db.find_one(
            {"looking_at.target": target, "looking_at.life": {"$gt": duration}}
        )
        if ret is not None:
            db = (
                self.physical_db_long_looking
                if event == "long_looking"
                else self.physical_db_looking
            )
            self.update(
                db,
                event,
                {"target": target, "duration": ret["looking_at"]["life"]},
            )

    def update(self, db, event, contents):
        query = {"event": event, "contents.target": contents["target"]}
        r = db.db.find_one(query)
        if r is None:
            db.insert(contents)
        else:
            db.db.update_one(query, {"$set": {"contents": contents}})


def main():
    rclpy.init()
    node = CheckLookingAt()
    rclpy.spin(node)
    rclpy.shutdown()
