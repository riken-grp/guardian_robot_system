#!/usr/bin/env python
# -*- coding: utf-8 -*-
import message_filters
import rclpy
from dateutil import tz
from rclpy import qos
from recognition_msgs.msg import Labels, OmronEnvSensor

from .dbmanager import TopicDBManager
from .mongo_node_base import MongoDBNode


class RegisterDBEnvironNode(MongoDBNode):
    def __init__(self, name="RegisterDBEnvironNode"):
        super().__init__(name)
        mongo_uri, mongo_port, dbname = self._init_mongo_params("")
        self.declare_parameter("check_interval", 60)
        check_interval = self.get_parameter("check_interval").value

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        sub_env = message_filters.Subscriber(
            self,
            OmronEnvSensor,
            "in_environ_raw_topic",
            qos_profile=qos.qos_profile_system_default,
        )
        sub_labels = message_filters.Subscriber(
            self,
            Labels,
            "in_environ_labels_topic",
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_env_label = message_filters.ApproximateTimeSynchronizer(
            [sub_env, sub_labels], 100, 0.2
        )
        self.sub_env_label.registerCallback(self.callback_env)
        self.timer = self.create_timer(check_interval, self.timer_callback)
        self.latest = None

    def callback_env(self, envmsg, labels):
        self.latest = (envmsg, labels)

    def timer_callback(self):
        if self.latest is None:
            return
        envmsg, labels = self.latest

        data = {}
        data["sensor_name"] = envmsg.sensor_name
        data["temperature"] = envmsg.temperature
        data["humidity"] = envmsg.humidity
        data["light"] = envmsg.light
        data["pressure"] = envmsg.pressure
        data["noise"] = envmsg.noise
        data["etvoc"] = envmsg.etvoc
        data["eco2"] = envmsg.eco2
        data["disconfort_index"] = envmsg.disconfort_index
        data["labels"] = labels.labels

        self.dbmanager.insert_environment(data, priority=60)


def main():
    rclpy.init()
    node = RegisterDBEnvironNode()
    rclpy.spin(node)
    rclpy.shutdown()
