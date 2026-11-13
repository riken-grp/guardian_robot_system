#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from pyindy.mongo import PhysicalDBWriter

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode


class CheckNumOfPerson(MongoDBNode):
    def __init__(self, name="CheckNumOfPerson"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")
        self.declare_parameter("many_threshold", 5)
        self.many_threshold = self.get_parameter("many_threshold").value
        self.prev_num_person = -1
        self.PERSON_THRESHOLD = 3

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)
        self.physical_db_no_people = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "no_people"
        )
        self.physical_db_many_people = PhysicalDBWriter(
            mongo_uri, mongo_port, dbname, "many_people"
        )

        self.timer = self.create_timer(0.5, self.timer_callback)

    def timer_callback(self):
        num_person = self.dbmanager.tracking_db.count_documents({"class_id": 0})

        if self.prev_num_person != num_person:
            if (
                num_person > self.PERSON_THRESHOLD
                and self.prev_num_person <= self.PERSON_THRESHOLD
            ):
                self.update(
                    self.physical_db_many_people,
                    "many_people",
                    {"num_people": num_person},
                )
            elif num_person == 0:
                self.update(
                    self.physical_db_no_people, "no_people", {"num_people": num_person}
                )
            self.prev_num_person = num_person

    def update(self, db, event, contents):
        db.insert(contents)


def main():
    rclpy.init()
    node = CheckNumOfPerson()
    rclpy.spin(node)
    rclpy.shutdown()
