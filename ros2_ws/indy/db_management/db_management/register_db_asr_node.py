#!/usr/bin/env python
# coding: utf-8 -*-

import json
import time

import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from .mongo_node_base import MongoDBNode

from .dbmanager import TopicDBManager

# ASR source port classification (kad/asr)
WHISPER_HT_PORTS = list(range(5562, 5568))   # Whisper + Human Tracker (5562-5567)
WHISPER_NAIVE_PORT = 5568                      # Whisper + standard microphone

# このソースが黙っているとみなすまでの時間 [s]
WHISPER_HT_TIMEOUT = 60.0
WHISPER_NAIVE_TIMEOUT = 30.0


class RegisterDBASRNode(MongoDBNode):
    """ASR の結果を physical_topic に登録する．

    ソースは互いに独立に扱う:
      - ssl_asr (in_ssl_asr_topic): 話者 (person_id = instance_id) 付き．常に登録する
      - kad/asr (in_asr_topic): sep_port で Human Tracker / 通常マイク / その他を区別し，
        通常マイクとその他は Human Tracker が応答していない間だけ登録する

    ignore_non_looking のときは，話者が分かる結果 (ssl と Human Tracker) は
    ロボットを見ている人の発話だけ登録する．
    """

    def __init__(self, name="RegisterDBASRNode"):
        super().__init__(name)

        mongo_uri, mongo_port, dbname = self._init_mongo_params("")

        self.dbmanager = TopicDBManager(mongo_uri, mongo_port, dbname)

        self.vap_status = False
        self.sub = self.create_subscription(
            StringStamped,
            "in_asr_topic",
            self.callback_asr,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_ssl = self.create_subscription(
            StringStamped,
            "in_ssl_asr_topic",
            self.callback_ssl_asr,
            qos_profile=qos.qos_profile_system_default,
        )
        self.sub_vap = self.create_subscription(
            StringStamped,
            "in_filtered_vap_topic",
            self.callback_vap,
            qos_profile=qos.qos_profile_system_default,
        )
        # 各ソースが最後に結果を出した時刻 (起動直後は応答しているとみなす)
        now = time.monotonic()
        self.last_ht = now
        self.last_naive = now

    @staticmethod
    def _silent(last, timeout):
        return time.monotonic() - last > timeout

    def is_accepted_speaker(self, instance_id):
        """ignore_non_looking のとき，ロボットを見ている人の発話だけ受け付ける."""
        # 設定 (起動時に dbmanager が読んだもの) が未登録，
        # または ignore_non_looking が無い場合は無視しない
        if not bool(self.dbmanager.config.get("ignore_non_looking", False)):
            return True
        ret = self.dbmanager.tracking_db.find_one(
            {"instance_id": instance_id, "looking_at.target": 1}
        )
        return ret is not None

    def callback_ssl_asr(self, asr):
        self.get_logger().debug(f"ssl asr: {asr.data}")
        d = json.loads(asr.data)
        if self.is_accepted_speaker(int(d.get("person_id", -1))):
            self.dbmanager.update_ssl_asr(asr, vap_status=self.vap_status)

    def callback_asr(self, asr):
        self.get_logger().debug(f"asr: {asr.data}")
        d = json.loads(asr.data)
        port = int(d["sep_port"])
        ht_silent = self._silent(self.last_ht, WHISPER_HT_TIMEOUT)
        naive_silent = self._silent(self.last_naive, WHISPER_NAIVE_TIMEOUT)
        if port in WHISPER_HT_PORTS:
            self.last_ht = time.monotonic()
            if self.is_accepted_speaker(d["instance_id"]):
                self.dbmanager.update_asr(asr, vap_status=self.vap_status)
        elif port == WHISPER_NAIVE_PORT:
            # 通常マイク: Human Tracker が応答していない間だけ
            self.last_naive = time.monotonic()
            if ht_silent:
                self.dbmanager.update_asr(asr, vap_status=self.vap_status)
        elif port < 0:
            # その他: Human Tracker も通常マイクも応答していない間だけ
            if ht_silent and naive_silent:
                self.dbmanager.update_asr(asr, vap_status=self.vap_status)
        else:
            self.get_logger().debug(f"Unknown sep_port: {port}")

    def callback_vap(self, vap):
        self.get_logger().debug(f"vap: {vap.data}")
        self.vap_status = json.loads(vap.data)["status"]


def main():
    rclpy.init()
    node = RegisterDBASRNode()
    rclpy.spin(node)
    rclpy.shutdown()
