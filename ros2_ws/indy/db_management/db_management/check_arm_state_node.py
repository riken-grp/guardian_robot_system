#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import PhysicalDBWriter

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode
from .recognition_available_region_checker import \
    RecognitionAvailableRegionChecker


class CheckArmStateNode(MongoDBNode):
    def __init__(self, name="CheckArmStateNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.previous = {}
        self.recognition_available_checker = RecognitionAvailableRegionChecker(
            mongo_uri, mongo_port
        )

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.physical_db_raising_hand = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "raising_hand"
        )

        self.timer = self.create_timer(0.5, self.timer_callback)

    def timer_callback(self):
        ret = self.dbmanager.tracking_db.find(
            {
                "$or": [
                    {"hand_state.raising_right_hand": True},
                    {"hand_state.raising_left_hand": True},
                ]
            }
        )
        for r in ret:
            if "location_global" in r:
                flag, region_id = self.recognition_available_checker.is_in(
                    r["location_global"]
                )

                prev_l, prev_r = self.get_prev_hand_state(r)
                if flag:
                    lraise = r["hand_state"]["raising_left_hand"]
                    rraise = r["hand_state"]["raising_right_hand"]
                    if prev_l != lraise or prev_r != rraise:
                        self.physical_db_raising_hand.insert(r, priority=30)
                        self.previous[r["instance_id"]] = (lraise, rraise)

        ret = self.dbmanager.tracking_db.find(
            {
                "hand_state.raising_right_hand": False,
                "hand_state.raising_left_hand": False,
            }
        )
        for r in ret:
            self.check_down_hand(self.physical_db_raising_hand, r)

    def get_prev_hand_state(self, r):
        if r["instance_id"] in self.previous:
            prev_l, prev_r = self.previous[r["instance_id"]]
        else:
            prev_l, prev_r = False, False

        return prev_l, prev_r

    def check_down_hand(self, db, contents):
        query = {
            "contents.instance_id": contents["instance_id"],
            "event": "raising_hand",
        }
        if contents["instance_id"] in self.previous:
            del self.previous[contents["instance_id"]]
        if db.db.find_one(query) is not None:
            db.db.delete_one(query)


def main():
    rclpy.init()
    node = CheckArmStateNode()
    rclpy.spin(node)
    rclpy.shutdown()
