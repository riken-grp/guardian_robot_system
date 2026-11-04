#!/usr/bin/python3

# import rospy
import json
import subprocess
from collections import defaultdict

import rclpy

# from std_msgs.msg import String
from common_msgs.msg import StringStamped  # type: ignore
from human_tracker_msgs.msg import AudioInfoList  # type: ignore
from rclpy.node import Node
from recognition_msgs.msg import Persons  # type: ignore

sentence_s = "これはテストです。"
juman_command = 'echo "{}" | jumanpp'.format(sentence_s)

# port_sec_d        = defaultdict(lambda: 0)
# port_msec_d       = defaultdict(lambda: 0)
# port_frameid_d    = defaultdict(lambda: "")

port_tssec_d = defaultdict(lambda: 0)
port_tsmsec_d = defaultdict(lambda: 0)
port_humanid_d = defaultdict(lambda: -1)
port_vad_d = defaultdict(lambda: 0)
port_localx_d = defaultdict(lambda: -10000)
port_localy_d = defaultdict(lambda: -10000)
port_localz_d = defaultdict(lambda: -10000)
port_power_d = defaultdict(lambda: -1)
port_sepid_d = defaultdict(lambda: 0)
port_classid_d = defaultdict(lambda: -1)
port_instanceid_d = defaultdict(lambda: -1)
port_personname_d = defaultdict(lambda: "")

instanceid_yaw_d = defaultdict(lambda: 90.0)
instanceid_pitch_d = defaultdict(lambda: 90.0)
instanceid_roll_d = defaultdict(lambda: 90.0)


class ASRmetadata(Node):
    def __init__(self, *args, **kwargs):
        super().__init__(node_name="asr_meta", *args, **kwargs)
        self.create_subscription(
            StringStamped, "asr/raw_text", self.callback_asr, 10
        )
        self.create_subscription(
            AudioInfoList, "human_tracker/audio_info", self.callback_atr, 10
        )
        self.create_subscription(
            Persons, "recog/person/pose/associated", self.callback_person, 10
        )
        self.pub = self.create_publisher(StringStamped, "asr/meta_data", 10)

    def callback_asr(self, data):
        print("ASR recognition results are published")
        # asrheader = json.loads(data.header)
        # asrresult = json.loads(data.data)
        # asrheader = data.header
        try:
            asrresult = json.loads(data.data)
        except Exception as e:
            self.get_logger().error(
                f"Error loading recog data: {e}"
                + f"\nData contents:{data.data}"
            )
            return
        # print("asrresult",asrresult)
        port = int(asrresult["sep_port"])
        instanceid = int(port_instanceid_d[port])
        # print("asrport",port)

        # sec      = port_sec_d[port]
        # msec     = port_msec_d[port]
        # frame_id = port_frameid_d[port]

        asrresult["timestamp_sec"] = port_tssec_d[port]
        asrresult["timestamp_msec"] = port_tsmsec_d[port]
        asrresult["human_id"] = port_humanid_d[port]
        asrresult["vad"] = port_vad_d[port]
        asrresult["x"] = port_localx_d[port]
        asrresult["y"] = port_localy_d[port]
        asrresult["z"] = port_localz_d[port]
        asrresult["power"] = port_power_d[port]
        asrresult["sep_id"] = port_sepid_d[port]
        asrresult["class_id"] = port_classid_d[port]
        asrresult["instance_id"] = port_instanceid_d[port]
        asrresult["person_name"] = port_personname_d[port]

        yaw = instanceid_yaw_d[instanceid]
        pitch = instanceid_pitch_d[instanceid]
        # roll = instanceid_pitch_d[instanceid]

        asrresult["is_facing"] = abs(yaw) < 20 and abs(pitch) < 20

        # Add Juman analysis
        juman_words = []
        juman_genkei = []
        juman_yomi = []
        juman_pos = []
        juman_span = []

        prev_word = ""
        prev_pos = ""

        sentence = asrresult["words"]
        sentence_s = sentence
        juman_command = 'echo "{}" | jumanpp'.format(sentence_s)
        with subprocess.Popen(
            juman_command, text=True, stdout=subprocess.PIPE, shell=True
        ) as juman:
            for mrph in iter(juman.stdout.readline, ""):  # type: ignore
                if mrph == "EOS\n":
                    juman_span.append(prev_word)
                    break
                mrph_a = mrph.split(" ")
                if mrph_a[0] == "\n":
                    break
                juman_words.append(mrph_a[0])
                juman_yomi.append(mrph_a[1])
                juman_genkei.append(mrph_a[2])
                juman_pos.append(mrph_a[3] + "+" + mrph_a[5])
                if mrph_a[3] == prev_pos:
                    prev_pos = mrph_a[3]
                    prev_word = prev_word + mrph_a[0]
                else:
                    juman_span.append(prev_word)
                    prev_pos = mrph_a[3]
                    prev_word = mrph_a[0]

        asrresult["juman_words"] = juman_words
        asrresult["juman_genkei"] = juman_genkei
        asrresult["juman_yomi"] = juman_yomi
        asrresult["juman_pos"] = juman_pos
        asrresult["juman_span"] = juman_span

        # publish
        text = json.dumps(asrresult, ensure_ascii=False)
        msg = StringStamped()
        # ヘッダの情報は振り直す
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.data = text
        self.pub.publish(msg)
        print("publish", text)

    def callback_atr(self, data):

        atrresults = data

        for atrresult in atrresults.info:

            port = int(atrresult.port)
            # print("atrport",port)
            # print(atrresult)

            port_tssec_d[port] = atrresult.timestamp_sec
            port_tsmsec_d[port] = atrresult.timestamp_msec
            port_humanid_d[port] = atrresult.human_id
            port_vad_d[port] = atrresult.vad
            port_localx_d[port] = atrresult.x
            port_localy_d[port] = atrresult.y
            port_localz_d[port] = atrresult.z
            port_power_d[port] = atrresult.power
            port_sepid_d[port] = atrresult.sep_id
            port_classid_d[port] = atrresult.class_id
            port_instanceid_d[port] = atrresult.instance_id
            port_personname_d[port] = atrresult.person_name

    def callback_person(self, data):

        personsresults = data.persons

        for personresult in personsresults:
            instance_id = personresult.instance_id
            face_orientation = personresult.face_orientation

            # print("Person",instance_id, face_orientation)
            if len(face_orientation) == 3:
                instanceid_yaw_d[instance_id] = face_orientation[0]
                instanceid_pitch_d[instance_id] = face_orientation[1]
                instanceid_roll_d[instance_id] = face_orientation[2]


def main():
    rclpy.init()
    node = ASRmetadata()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
