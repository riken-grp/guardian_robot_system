#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import PhysicalDBWriter

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode
from .recognition_available_region_checker import \
    RecognitionAvailableRegionChecker


class CheckWavingHandNode(MongoDBNode):
    def __init__(self, name="CheckWavingHandNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.previous = {}
        self.recognition_available_checker = RecognitionAvailableRegionChecker(
            mongo_uri, mongo_port
        )

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.physical_db_waving_hand = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "waving_hand"
        )

        self.timer = self.create_timer(0.5, self.timer_callback)

    def timer_callback(self):
        ret = self.dbmanager.tracking_db.find({"hand_waving.hand_waving": True})
        for r in ret:
            if "location_global" in r:
                flag, region_id = self.recognition_available_checker.is_in(
                    r["location_global"]
                )

                prev = self.get_prev_hand_state(r)
                if flag:
                    wave = r["hand_waving"]["hand_waving"]
                    if prev != wave:
                        self.physical_db_waving_hand.insert(r, priority=100)
                        self.previous[r["instance_id"]] = wave

        ret = self.dbmanager.tracking_db.find(
            {
                "hand_waving.hand_waving": False,
            }
        )
        for r in ret:
            self.check_non_waving_hand(self.physical_db_waving_hand, r)

    def get_prev_hand_state(self, r):
        if r["instance_id"] in self.previous:
            wave = self.previous[r["instance_id"]]
        else:
            wave = False

        return wave

    def check_non_waving_hand(self, db, contents):
        query = {
            "contents.instance_id": contents["instance_id"],
            "event": "waving_hand",
        }
        if contents["instance_id"] in self.previous:
            del self.previous[contents["instance_id"]]
        if db.db.find_one(query) is not None:
            db.db.delete_one(query)


def main():
    rclpy.init()
    node = CheckWavingHandNode()
    rclpy.spin(node)
    rclpy.shutdown()
