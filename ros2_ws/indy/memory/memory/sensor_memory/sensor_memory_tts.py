#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Text-To-Speech Utterance Info"""

import json
import re

from common_msgs.msg import StringStamped  # type:ignore
from std_msgs.msg import String

from ..util import ROBOT_NAME, get_current_ts, get_time_from_header
from .sensor_memory_base import SensorMemoryBase


class SensorMemoryTTS_FromBTKS(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()
        self.tag_re = re.compile(r"<.*?>")

    def callback(self, data: StringStamped) -> None:
        tstamp = get_time_from_header(data.header)
        if tstamp == 0:
            tstamp = self.node.get_clock().now().nanoseconds * 1e-9
        tts = json.loads(data.data)

        if "tts_command" in tts and tts["tts_command"] not in (
            "ttsSSMLText",
            "ttsPlainText",
        ):
            return

        out = {
            "origin": "tts",
            "actor": ROBOT_NAME,
            "utterance": (
                tts["utterance"]
                if "utterance" in tts
                else (
                    re.sub(self.tag_re, "", tts["utterance_sml"])
                    if "utterance_sml" in tts
                    else ""
                )
            ),
            "created_at_ts": (
                tts["timestamp"][1] * 1e-9 if "timestamp" in tts else tstamp
            ),
        }

        self.__insertdoc__(out)


class SensorMemoryTTS_FromActCtrl(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()

    def callback(self, data: String) -> None:
        try:
            tts = json.loads(data.data)
        except Exception:
            # If exception, JSON is malformed (so not TTS)
            return

        if "speak" not in tts or (
            "status" in tts and tts["status"] == "error"
        ):
            return
        tstamp = get_current_ts(self.node)

        # tts --> speak, duration, status
        out = {
            "origin": "tts",
            "actor": ROBOT_NAME,
            "utterance": tts["speak"],
            "metadata": tts,
            "created_at_ts": tstamp,
        }

        self.__insertdoc__(out)
