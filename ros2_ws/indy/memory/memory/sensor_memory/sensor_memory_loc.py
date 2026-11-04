#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Self-Localization"""

from geometry_msgs.msg import PoseStamped
from pymongo import GEO2D

from ..util import get_time_from_header
from .sensor_memory_base import SensorMemoryBase


class SensorMemorySelfLoc(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()
        self.setup_index(
            self.sm_coll, "position", GEO2D, min=-10000.0, max=10000.0
        )

    def callback(self, data: PoseStamped) -> None:
        out = {}
        tstamp = get_time_from_header(data.header)  # type: ignore

        out["position"] = [
            data.pose.position.x,
            data.pose.position.y,
            # data.pose.position.z,
        ]
        out["orientation"] = [
            data.pose.orientation.x,
            data.pose.orientation.y,
            data.pose.orientation.z,
            data.pose.orientation.w,
        ]

        out["created_at_ts"] = tstamp

        self.__insertdoc__(out)
