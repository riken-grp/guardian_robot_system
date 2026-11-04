#!/usr/bin/env python
# coding: utf-8 -*-

"""Base Classes for Short-Term Memory Modules"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, Tuple, Type

from pymongo import GEO2D
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.impl.rcutils_logger import RcutilsLogger
from rclpy.node import Node
from rclpy.timer import Timer

from ..util import ForgettingSettings, MemoryLevel, get_current_ts
from ..util.intv_box import IntvBoxer
from ..util.memory_func import MemoryFunction, ValidIndex


@dataclass
class ShortTermMemoryBase(ABC, IntvBoxer, MemoryFunction):
    """Base class for Short-Term Memory modules"""

    node: Node
    sm_coll: Collection
    stm_coll: Collection
    mem_lvl: MemoryLevel
    forget_params: ForgettingSettings
    sensor_params: dict = field(default_factory=dict)
    eval_colls: Tuple[Collection, Collection] | None = field(default=None)
    ros_timer: Timer = field(init=False)
    last_ts: float = field(init=False)

    def __post_init__(self):
        self.last_ts = get_current_ts(self.node)
        self.start_timer()
        # Every restart should begin with a clean memory.
        self.clear_sensor_memory()

    @property
    def freq(self) -> float:
        return self.forget_params.freq

    @property
    def a_decay(self) -> float:
        return self.forget_params.a

    @property
    def d_balance(self) -> float:
        return self.forget_params.d

    @property
    def forget_line(self) -> float:
        return self.forget_params.f_line

    @property
    def stm_level(self) -> int:
        return self.mem_lvl.stm_lvl

    @property
    def sm_level(self) -> int:
        return self.mem_lvl.sm_lvl

    @property
    def logger(self) -> RcutilsLogger:
        return self.node.get_logger()

    @abstractmethod
    def callback(self) -> None:
        """Callback for Timer"""

    def callback_wrapper(self) -> None:
        """Wrapper for Callback, for Evaluation Data Gathering"""
        self.wrap_call(self.callback)

    def wrap_call(self, fn: Callable):
        """Wrapper for any function, for Evaluation Data Gathering"""
        # 1. Record Starting Time
        start_ts = self.node.get_clock().now().nanoseconds * 1e-9
        # 2. Call original Callback
        fn()
        # 3. Record Ending Time
        end_ts = self.node.get_clock().now().nanoseconds * 1e-9

        if self.eval_colls is None:
            return
        try:
            # 4. Get DB Storage Size
            db_info = self.sm_coll.database.command(
                {"dbStats": 1, "freeStorage": 1}
            )
            db_size = (
                db_info["storageSize"] - db_info["freeStorageSize"]
            ) / 1024
            # 5. Save to different database
            db_doc = {
                "process": f"stm_{self.stm_coll.name}",
                "start": start_ts,
                "end": end_ts,
                "size": db_size,
            }
            self.eval_colls[0].insert_one(db_doc)

            # 6. Do the same for sensor memory
            db_info = self.stm_coll.database.command(
                {"dbStats": 1, "freeStorage": 1}
            )
            db_size = (
                db_info["storageSize"] - db_info["freeStorageSize"]
            ) / 1024
            db_doc["size"] = db_size
            self.eval_colls[1].insert_one(db_doc)
        except PyMongoError as e:
            self.logger.error(
                f"[STM-{self.stm_coll.full_name.upper()}-EVAL] "
                + f' Error Inserting Eval Data. REASON: "{str(e)}"'
            )

    def memory_update(self, coll: Collection, to_update: list) -> int:
        summ = 0
        for d in to_update:
            try:
                res = coll.replace_one(
                    filter={"_id": d["_id"]},
                    replacement=d,
                )
                summ += res.modified_count
            except PyMongoError as e:
                self.logger.error(
                    f"[STM-{coll.full_name.upper()}] Update Error: {str(e)}"
                )
        return summ

    def memory_add(self, coll: Collection, to_add: list) -> int:
        res = 0
        if not to_add:
            return res
        try:
            res += len(coll.insert_many(to_add).inserted_ids)
        except PyMongoError as e:
            self.logger.error(
                f"[STM-{coll.full_name.upper()}] Insert Error: {str(e)}"
            )
        return res

    def memory_forget_list(self, coll: Collection, to_forget: list) -> int:
        res = 0
        if not to_forget:
            return res
        try:
            res += coll.delete_many(
                {"_id": {"$in": [d["_id"] for d in to_forget]}}
            ).deleted_count
        except PyMongoError as e:
            self.logger.error(
                f"[STM-{coll.full_name.upper()}] " + f"Delete Error: {str(e)}"
            )
        return res

    def memory_forget_tstamp(self, coll: Collection, tstamp: float) -> int:
        res = 0
        try:
            res += coll.delete_many(
                filter={"forgetting_curve.forget_time": {"$lt": tstamp}}
            ).deleted_count
        except PyMongoError as e:
            self.logger.error(
                f"[STM-{coll.full_name.upper()}] Delete Error: {str(e)}"
            )
        return res

    def memorize(
        self,
        sensor_contents: list,
        to_update: list,
        to_add: list,
        tstamp: float,
    ) -> None:
        """Method called to carry out the Memorization process"""
        added = updated = deleted = 0
        # STM Memorizing (2)
        if self.stm_level > 0:
            added = self.memory_add(self.stm_coll, to_add)
            updated = self.memory_update(self.stm_coll, to_update)

        # STM Forgetting (2)
        if self.stm_level == 2:
            deleted += self.memory_forget_tstamp(self.stm_coll, tstamp)

        # SM Forgetting
        if self.sm_level >= 2:
            deleted += self.memory_forget_list(self.sm_coll, sensor_contents)

        h = f"[STM-{self.stm_coll.full_name.upper()}] "
        self.logger.debug(f"{h} ADD {added} | UPD {updated} | DEL {deleted}")

    def clear_sensor_memory(self) -> None:
        tf = get_current_ts(self.node)
        del_res = self.sm_coll.delete_many(
            filter={"created_at_ts": {"$lte": tf}}
        )
        h = f"[STM-{self.stm_coll.full_name.upper()}] "
        self.logger.debug(f"{h} DEL {del_res.deleted_count}")

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

    def start_timer(self):
        self.ros_timer = (
            self.node.create_timer(
                self.freq, self.callback, MutuallyExclusiveCallbackGroup()
            )
            if self.eval_colls is None
            else self.node.create_timer(
                self.freq,
                self.callback_wrapper,
                MutuallyExclusiveCallbackGroup(),
            )
        )

    def stop_timer(self):
        self.node.destroy_timer(self.ros_timer)

    @classmethod
    def gen_partial(
        cls: Type[ShortTermMemoryBase], sm_coll: str, stm_coll: str
    ) -> PartialShortTermMemory:
        # Called by main Node
        def inner_partial(
            node: Node,
            sm_db: Database,
            stm_db: Database,
            sett_db: Database,
            mem_lvl: MemoryLevel,
            db_eval: Database | None,
            module_settings: dict = {},
        ) -> ShortTermMemoryBase:
            f_settings = ForgettingSettings.load_from_db(
                sett_db, "short_term", stm_coll
            )

            eval_colls = (
                None
                if db_eval is None
                else (db_eval[f"sm_{sm_coll}"], db_eval[f"stm_{stm_coll}"])
            )

            new_memory: ShortTermMemoryBase = cls(
                node,
                sm_db[sm_coll],
                stm_db[stm_coll],
                mem_lvl,
                forget_params=f_settings,
                sensor_params=module_settings,
                eval_colls=eval_colls,
            )

            node.get_logger().info(f"[STM-{stm_coll.upper()}] Initialized. ")

            return new_memory

        return inner_partial

    @classmethod
    def get_default_forgetting_params(cls) -> ForgettingSettings:
        return ForgettingSettings(a=0.25, d=0.66, f_line=0.10, freq=180)


PartialShortTermMemory = Callable[
    [Node, Database, Database, Database, MemoryLevel, Database | None, Dict],
    ShortTermMemoryBase,
]
