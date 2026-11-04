#!/usr/bin/env python
# coding: utf-8 -*-

import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from .mongo_node_base import MongoDBNode
from recognition_msgs.msg import Objects, Persons, Pointings, Relations

from .dbmanager import TopicDBManager


class RegisterDBNode(MongoDBNode):
    def __init__(self, name="RegisterDBNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")
        self.declare_parameter("distance_threshold", 2.0)
        self.distance_threshold = self.get_parameter("distance_threshold").value

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.sub_track = self.create_subscription(
            Objects,
            "in_track_topic",
            self.callback_obj,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_pose = self.create_subscription(
            Persons,
            "in_associated_person_topic",
            self.callback_pose,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_face = self.create_subscription(
            Persons,
            "in_associated_face_topic",
            self.callback_face,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_attr = self.create_subscription(
            Persons,
            "in_attributes_topic",
            self.callback_attr,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_sg = self.create_subscription(
            Relations,
            "in_associated_scenegraph_topic",
            self.callback_sg,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_hand = self.create_subscription(
            Pointings,
            "in_hand_topic",
            self.callback_hand,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_hand_waving = self.create_subscription(
            StringStamped,
            "in_hand_waving_topic",
            self.callback_hand_waving,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_lookingat = self.create_subscription(
            StringStamped,
            "in_lookingat_topic",
            self.callback_lookingat,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_wheelchair = self.create_subscription(
            StringStamped,
            "in_wheelchair_topic",
            self.callback_wheelchair,
            qos_profile=qos.qos_profile_system_default,
        )

    def callback_obj(self, tracklets):
        self.dbmanager.update_objects(tracklets, self.distance_threshold)

    def callback_pose(self, poses):
        self.dbmanager.update_poses(poses)

    def callback_face(self, faces):
        self.dbmanager.update_faces(faces)

    def callback_attr(self, attributes):
        self.dbmanager.update_attributes(attributes)

    def callback_sg(self, relations):
        self.dbmanager.update_scenegraph(relations)

    def callback_hand(self, pointings):
        self.dbmanager.update_hand_state(pointings)

    def callback_hand_waving(self, pointings):
        self.dbmanager.update_hand_waving(pointings)

    def callback_lookingat(self, lookingats):
        self.dbmanager.update_lookingat(lookingats)

    def callback_wheelchair(self, wheelchairs):
        self.dbmanager.update_wheelchair(wheelchairs)


def main():
    rclpy.init()
    node = RegisterDBNode()
    rclpy.spin(node)
    rclpy.shutdown()
