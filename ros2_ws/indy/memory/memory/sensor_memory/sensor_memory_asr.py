#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Automatic Speech Recognition"""

import json
import re

from common_msgs.msg import StringStamped  # type:ignore

from ..util import get_time_from_header
from .sensor_memory_base import SensorMemoryBase


class SensorMemoryASR(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()
        self.re_patt = re.compile(r"(\S+)\1\1\1", re.I)

    def __repl(self, matchobj: re.Match) -> str:
        return matchobj.group(1)

    def __is_yt_hallu(self, words: str) -> bool:
        m = re.match(".*視聴してくださって.*ありがとう.*", words, re.I)
        return True if m is not None else False

    def callback(self, data: StringStamped) -> None:
        tstamp = get_time_from_header(data.header)
        asr_data = json.loads(data.data)

        # Silence? Error? No ASR output.
        if (
            not asr_data["words"]
            or float(asr_data["scores"]) < 0.7
            or self.__is_yt_hallu(asr_data["words"])
        ):
            return

        # Attempt to remove excessive repetitions
        words = asr_data["words"]
        matchTrap = self.re_patt.sub(self.__repl, words)
        while words != matchTrap:
            words = matchTrap
            matchTrap = self.re_patt.sub(self.__repl, words)

        out = {
            "origin": "asr",
            "actor": (
                asr_data["person_name"]
                if asr_data["person_name"]
                else f'User#{asr_data["instance_id"]}'
            ),
            "utterance": words,
            "metadata": asr_data,
            "created_at_ts": tstamp,
        }

        self.__insertdoc__(out)


class SensorMemoryASR_MmmDemo(SensorMemoryASR):
    def callback(self, data: StringStamped) -> None:
        metadata = json.loads(data.data)
        try:
            sep_port = int(metadata["sep_port"])
            # self.logger.info(f"SEP PORT: {sep_port}")
        except Exception as e:
            self.logger.error(str(e))
            return
        if sep_port == 55660:
            super().callback(data)

    def callback_wrapper(self, data: StringStamped) -> None:
        metadata = json.loads(data.data)
        try:
            sep_port = int(metadata["sep_port"])
        except Exception as e:
            self.logger.error(str(e))
            return
        if sep_port == 55660:
            super().callback_wrapper(data)
