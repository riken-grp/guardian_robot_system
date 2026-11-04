#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Scene Graph Recognition"""
from dataclasses import dataclass

from recognition_msgs.msg import Relations  # type: ignore

from ..util import get_time_from_header
from .sensor_memory_base import SensorMemoryBase


@dataclass
class SensorMemorySceGraph(SensorMemoryBase):
    """Sensor Memory Module for Scene Graph generation"""

    def callback(self, data: Relations) -> None:
        tstamp = get_time_from_header(data.header)
        out = {}

        out["scenegraph"] = [
            {
                "subject": {
                    "instanced_id": rel.subject.instance_id,
                    "class_id": rel.subject.class_id,
                    "name": rel.subject.name,
                },
                "object": {
                    "instanced_id": rel.object.instance_id,
                    "class_id": rel.object.class_id,
                    "name": rel.object.name,
                },
                "relation_id": rel.relation_id,
                "relation_name": rel.name,
                "confidence": rel.confidence,
            }
            for rel in data.relations
        ]
        out["created_at_ts"] = tstamp

        self.__insertdoc__(out)
