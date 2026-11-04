#!/usr/bin/env python
# coding: utf-8 -*-

"""Main Module for Sensor Memory"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, NamedTuple, Type

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from pymongo import GEO2D
from rclpy.callback_groups import CallbackGroup, ReentrantCallbackGroup
from rclpy.exceptions import NameValidationException
from rclpy.impl.rcutils_logger import RcutilsLogger
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_system_default

from ..util import get_current_ts
from ..util.memory_func import MemoryFunction, ValidIndex


class TopicInfo(NamedTuple):
    name: str
    t_type: Type
    cbg: CallbackGroup
    qos: QoSProfile


@dataclass
class SensorMemoryBase(ABC, MemoryFunction):
    node: Node
    sm_coll: Collection
    topic_info: TopicInfo
    eval_coll: Collection | None = field(default=None)

    def __post_init__(self):
        self.setup_index(self.sm_coll, "created_at_ts", 1)
        try:
            target_cb = (
                self.callback_wrapper
                if self.eval_coll is not None
                else self.callback
            )
            self.subscriber = self.node.create_subscription(
                self.topic_info.t_type,
                self.topic_info.name,
                target_cb,
                self.topic_info.qos,
                callback_group=self.topic_info.cbg,
            )
        except NameValidationException as e:
            self.logger.error(
                "[SENSOR] Could not Subscribe to Topic "
                + f"'{self.topic_info.name}'. REASON: '{str(e)}'. "
                + "Related functionality will not be included inthis session."
            )

    @property
    def logger(self) -> RcutilsLogger:
        return self.node.get_logger()

    def __insertdoc__(self, data: dict):
        try:
            self.sm_coll.insert_one(data)
        except PyMongoError as e:
            self.logger.error(
                f"[SENSOR] Error Inserting into '{self.sm_coll.full_name}'. "
                + f'REASON: "{str(e)}"'
            )

    def callback_wrapper(self, event) -> None:
        """Callback Wrapper, to evaluate execution info."""
        # 1. Record Starting Time
        start_ts = get_current_ts(self.node)
        # 2. Call original Callback
        self.callback(event)
        # 3. Record Ending Time
        end_ts = get_current_ts(self.node)
        # 4. Get DB Storage Size

        db_info = self.sm_coll.database.command(
            {"dbStats": 1, "freeStorage": 1}
        )
        db_size = (db_info["storageSize"] - db_info["freeStorageSize"]) / 1024
        # 5. Save to different database
        db_doc = {
            "process": f"sm_{self.sm_coll.name}",
            "start": start_ts,
            "end": end_ts,
            "size": db_size,
        }
        if self.eval_coll is not None:
            self.eval_coll.insert_one(db_doc)

    @abstractmethod
    def callback(self, data: str) -> None:
        """Method called by ROS subscription"""
        pass

    @classmethod
    def gen_partial(
        cls: Type[SensorMemoryBase],
        sm_coll: str,
        topic_name: str,
        topic_type: Type,
    ) -> PartialSensorMemory:

        # This one will be called by the main Node
        def inner_partial(
            node: Node, db: Database, db_eval: Database | None
        ) -> SensorMemoryBase:
            tinfo = TopicInfo(
                topic_name,
                topic_type,
                ReentrantCallbackGroup(),
                qos_profile_system_default,
            )
            new_memory: SensorMemoryBase = cls(
                node,
                db[sm_coll],
                tinfo,
                db_eval["sensor"] if db_eval is not None else None,
            )
            node.get_logger().info(
                f"[SM-{sm_coll.upper()}] Subbed to '{topic_name}' "
            )
            return new_memory

        return inner_partial

    def setup_index(
        self,
        coll: Collection,
        fieldname: str,
        indextype: ValidIndex,
        dropifexists=False,
        min=-180.0,
        max=180.0,
    ):
        if indextype != GEO2D:
            super().setup_index(coll, fieldname, indextype, dropifexists)
            return

        indices = dict(coll.index_information())
        index_name = f"{fieldname}_{indextype}"

        if index_name in indices:
            if dropifexists:
                coll.drop_index(index_name)
            else:
                return

        coll.create_index([(fieldname, GEO2D)], min=min, max=max)


PartialSensorMemory = Callable[
    [Node, Database, Database | None], SensorMemoryBase
]
