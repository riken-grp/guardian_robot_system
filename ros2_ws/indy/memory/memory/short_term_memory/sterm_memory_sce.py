#!/usr/bin/env python
# coding: utf-8 -*-

"""Short-Term Scene Graph Recognition Memory Module"""

from dataclasses import dataclass
from typing import Any, Dict, List

from ..util import get_current_ts
from .sterm_memory_base import ShortTermMemoryBase


@dataclass
class ShortTermSceMemory(ShortTermMemoryBase):
    """Class for Short-Term Scene Graph Recognition Memory Module"""

    def __post_init__(self):
        super().__post_init__()
        self.setup_index(self.stm_coll, "updated_at_ts", 1)
        self.setup_index(self.stm_coll, "scenegraph", "text")

    def create_stm_from_sm(
        self, stm_documents: List[Dict[str, Any]], tstamp: float
    ) -> dict:
        """Convert Sensor objects into Short-Term Memory Objects"""
        if not stm_documents:
            return {}

        stm_obj = {}
        basegraph = []

        for d in stm_documents:
            basegraph = self.join_sm_objs(basegraph, d["scenegraph"])

        stm_obj["scenegraph"] = basegraph

        stm_obj["updated_at_ts"] = {
            "lb": stm_documents[0]["created_at_ts"],
            "ub": stm_documents[-1]["created_at_ts"],
        }

        stm_obj["forgetting_curve"] = {
            "mu": 3.0,  # Temporary value
            "a": self.a_decay,
            "d": self.d_balance,
            "f_line": self.forget_line,
            "forget_time": self.estimate_forgetting_t(
                mu=3.0,
                a=self.a_decay,
                t=tstamp,
                d=self.d_balance,
                fline=self.forget_line,
            ),
        }

        return stm_obj

    def join_sm_objs(
        self, sgraph_base: List[list], sgraph_other: List[list]
    ) -> List[list]:
        """Joins Sensor Memory Objects into STM objects by compiling their statistics"""
        for triplet in sgraph_other:
            # if triplet not in sgraph_base:
            #     sgraph_base.append(triplet)
            found = False
            for triplet_other in sgraph_base:
                if triplet == triplet_other:
                    found = True
                    break
            if not found:
                sgraph_base.append(triplet)
        return sgraph_base

    def callback(self) -> None:
        tf = get_current_ts(self.node)

        sensormem_contents = list(
            self.sm_coll.find(
                filter={"created_at_ts": {"$gte": self.last_ts, "$lte": tf}},
                sotr=[("created_at_ts", 1)],
            )
        )

        # STM Memorizing
        stm_obj = (
            self.create_stm_from_sm(sensormem_contents, tf)
            if self.stm_level > 0
            else {}
        )

        self.memorize(sensormem_contents, [], [stm_obj] if stm_obj else [], tf)

        self.last_ts = tf

        self.logger.debug(
            f"[STM_{self.stm_coll.name.upper()}] Memorized "
            + f"({len(sensormem_contents)})."
        )
