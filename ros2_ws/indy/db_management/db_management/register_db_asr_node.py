#!/usr/bin/env python
# coding: utf-8 -*-

import json

import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from .mongo_node_base import MongoDBNode
from std_msgs.msg import String

from .dbmanager import TopicDBManager

# ASR source port classification
WHISPER_HT_PORTS = list(range(5562, 5568))   # Whisper + Human Tracker (5562-5567)
WHISPER_NAIVE_PORT = 5568                      # Whisper + standard microphone


class RegisterDBASRNode(MongoDBNode):
    def __init__(self, name="RegisterDBASRNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.vap_status = False
        self.sub_dbg = self.create_subscription(
            String,
            "in_asr_dbg_topic",
            self.callback_asr_dbg,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub = self.create_subscription(
            StringStamped,
            "in_asr_topic",
            self.callback_asr,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_vap = self.create_subscription(
            StringStamped,
            "in_filtered_vap_topic",
            self.callback_vap,
            qos_profile=qos.qos_profile_system_default,
        )
        # Timer
        self.timer = self.create_timer(0.1, self.timer_callback)
        self.whisper_ht_interval = 600
        self.whisper_naive_interval = 300

    def timer_callback(self):
        if self.whisper_ht_interval >= 0:
            self.whisper_ht_interval = self.whisper_ht_interval - 1
        if self.whisper_ht_interval < 0:
            self.get_logger().debug(
                "ros asr: whisper and human tracker does not respond for 60 sec"
            )
        if self.whisper_naive_interval >= 0:
            self.whisper_naive_interval = self.whisper_naive_interval - 1
        if self.whisper_naive_interval < 0:
            self.get_logger().debug(
                "ros asr: whisper using an usual microphone does not respond for 30 sec"
            )

    def callback_asr_dbg(self, asr):
        self.dbmanager.update_asr_dbg(asr)

    def callback_asr(self, asr):
        self.get_logger().warn(f"asr: {asr}")
        d = json.loads(asr.data)
        if int(d["sep_port"]) in WHISPER_HT_PORTS:
            self.whisper_ht_interval = 600
            # ここで，looking_at情報を取得
            ret = self.dbmanager.tracking_db.find_one(
                {"instance_id": d["instance_id"], "looking_at.target": 1}
            )
            config = self.dbmanager.client["rism_configs"].rism_config.find_one()
            # looking_atがFalseの場合は，asrの情報をDBに登録しない
            if ret is not None or not config["ignore_non_looking"]:
                self.dbmanager.update_asr(asr, vap_status=self.vap_status)
            return True
        if int(d["sep_port"]) == WHISPER_NAIVE_PORT:
            self.whisper_naive_interval = 300
            if self.whisper_ht_interval < 0:
                self.dbmanager.update_asr(asr, vap_status=self.vap_status)
            return True
        elif int(d["sep_port"]) < 0:
            if self.whisper_ht_interval < 0:
                if self.whisper_naive_interval < 0:
                    self.dbmanager.update_asr(asr, vap_status=self.vap_status)
        else:
            self.get_logger().debug(f"Unknown sep_port: {d['sep_port']}")
            return

    def callback_vap(self, vap):
        self.get_logger().warn(f"vap: {vap}")
        self.vap_status = json.loads(vap.data)["status"]


def main():
    rclpy.init()
    node = RegisterDBASRNode()
    rclpy.spin(node)
    rclpy.shutdown()
