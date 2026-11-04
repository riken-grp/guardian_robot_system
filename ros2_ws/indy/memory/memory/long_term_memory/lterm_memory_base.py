"""Base Classes for Long-Term Memory Modules"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, Literal, Tuple, Type

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.impl.rcutils_logger import RcutilsLogger
from rclpy.node import Node
from rclpy.timer import Timer

from ..util import ForgettingSettings, MemoryLevel, get_current_ts
from ..util.intv_box import IntvBoxer
from ..util.memory_func import MemoryFunction

ValidIndex = Literal[1, -1, "2d", "text"]


@dataclass
class LongTermMemoryBase(ABC, IntvBoxer, MemoryFunction):
    """Base class for Long-Term Memory modules"""

    node: Node
    stm_coll: Collection
    ltm_coll: Collection
    mem_lvl: MemoryLevel
    forget_params: ForgettingSettings
    module_params: dict = field(default_factory=dict)
    eval_colls: Tuple[Collection, Collection] | None = field(default=None)
    ros_timer: Timer = field(init=False)
    last_ts: float = field(init=False)

    def __post_init__(self):
        self.last_ts = get_current_ts(self.node)
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
    def ltm_level(self) -> int:
        return self.mem_lvl.ltm_lvl

    @property
    def logger(self) -> RcutilsLogger:
        return self.node.get_logger()

    @abstractmethod
    def callback(self) -> None:
        """Callback for Timer"""

    def callback_wrapper(self) -> None:
        """Wrapper for Callback, for Evaluation Data Gathering"""
        # 1. Record Starting Time
        start_ts = self.node.get_clock().now().nanoseconds * 1e-9
        # 2. Call original Callback
        self.callback()
        # 3. Record Ending Time
        end_ts = self.node.get_clock().now().nanoseconds * 1e-9

        if self.eval_colls is None:
            return
        try:
            # 4. Get DB Storage Size
            db_info = self.ltm_coll.database.command(
                {"dbStats": 1, "freeStorage": 1}
            )
            db_size = (
                db_info["storageSize"] - db_info["freeStorageSize"]
            ) / 1024
            # 5. Save to different database
            db_doc = {
                "process": f"ltm_{self.ltm_coll.name}",
                "start": start_ts,
                "end": end_ts,
                "size": db_size,
            }
            self.eval_colls[0].insert_one(db_doc)

            # 6. Do the same for long term memory
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
                f'[LONGT-EVAL] Error Inserting Eval Data. REASON: "{str(e)}"'
            )

    @classmethod
    def gen_partial(
        cls: Type[LongTermMemoryBase], stm_coll: str, ltm_coll: str
    ) -> PartialLongTermMemory:
        # Called by main Node
        def inner_partial(
            node: Node,
            stm_db: Database,
            ltm_db: Database,
            sett_db: Database,
            mem_lvl: MemoryLevel,
            db_eval: Database | None,
            module_params: dict = {},
        ) -> LongTermMemoryBase:

            f_settings = ForgettingSettings.load_from_db(
                sett_db, "long_term", ltm_coll
            )

            eval_colls = (
                None
                if db_eval is None
                else (db_eval[f"stm_{stm_coll}"], db_eval[f"ltm_{ltm_coll}"])
            )

            new_memory: LongTermMemoryBase = cls(
                node,
                stm_db[stm_coll],
                ltm_db[ltm_coll],
                mem_lvl,
                forget_params=f_settings,
                module_params=module_params,
                eval_colls=eval_colls,
            )

            node.get_logger().info(f"[LTM-{stm_coll.upper()}] Initialized. ")

            return new_memory

        return inner_partial


PartialLongTermMemory = Callable[
    [Node, Database, Database, Database, MemoryLevel, Database | None, Dict],
    LongTermMemoryBase,
]
