#!/usr/bin/env python
# coding: utf-8 -*-

"""Short-Term Object Recognition Memory Module"""

import math
from dataclasses import dataclass, field
from typing import List, NamedTuple

from ..util import get_current_ts
from .sterm_memory_base import ShortTermMemoryBase


@dataclass
class ShortTermLocMemory(ShortTermMemoryBase):
    """Class for Short-Term Self-Localization Memory Module"""

    class DistanceTolData(NamedTuple):
        """Container for Distance Tolerance Data"""

        max_dist: float
        max_radians: float
        dist_tol: float

    # Originally stored in sensor_params
    dist_tolerance: DistanceTolData = field(init=False)

    def __post_init__(self):
        super().__post_init__()
        # If the info is in DB, load from it
        if "dist_tol" in self.forget_params:
            self.dist_tolerance = ShortTermLocMemory.DistanceTolData(
                **self.forget_params["dist_tol"]
            )
        else:
            # Default values
            self.dist_tolerance = ShortTermLocMemory.DistanceTolData(
                0.5, 0.5 / (6378.1 * 1e3), 1e-2
            )
        self.setup_index(self.stm_coll, "updated_at_ts", 1)
        self.setup_index(
            self.stm_coll, "position", "2d", min=-10000.0, max=10000.0
        )

    @property
    def max_dist(self) -> float:
        """Max distance"""
        return self.dist_tolerance.max_dist

    @property
    def dist_tol(self) -> float:
        """Error Tolerance"""
        return self.dist_tolerance.dist_tol

    def create_stm_from_sm(
        self, sensorcontents: List[dict], tstamp: float
    ) -> List[dict]:
        """Convert Sensor objects into Short-Term Memory Objects"""
        if not sensorcontents or self.stm_level == 0:
            return []
        stm_list = []
        step = sensorcontents[0]
        stm_list.append(
            {
                "position": step["position"],
                "orientation": step["orientation"],
                "updated_at_ts": {
                    "lb": step["created_at_ts"],
                    "ub": step["created_at_ts"],
                },
                "forgetting_curve": {
                    "mu": 0.3,
                    "a": self.a_decay,
                    "d": self.d_balance,
                    "f_line": self.forget_line,
                    "forget_time": self.estimate_forgetting_t(
                        mu=0.3,
                        a=self.a_decay,
                        t=tstamp,
                        d=self.d_balance,
                        fline=self.forget_line,
                    ),
                },
            }
        )

        for step in sensorcontents[1:]:
            prev = stm_list[-1]

            if (
                math.dist(step["position"][:2], prev["position"][:2]) < self.dist_tol
                and math.dist(step["orientation"], prev["orientation"])
                < self.dist_tol
            ):
                prev["updated_at_ts"]["ub"] = step["created_at_ts"]
                # Staying at a single place makes it less forgettable, but only a little
                prev["forgetting_curve"]["mu"] = 0.5
            else:
                stm_list.append(
                    {
                        "position": step["position"],
                        "orientation": step["orientation"],
                        "updated_at_ts": {
                            "lb": step["created_at_ts"],
                            "ub": step["created_at_ts"],
                        },
                        "forgetting_curve": {
                            "mu": 0.3,
                            "a": self.a_decay,
                            "d": self.d_balance,
                            "f_line": self.forget_line,
                            "forget_time": self.estimate_forgetting_t(
                                mu=0.3,
                                a=self.a_decay,
                                t=tstamp,
                                d=self.d_balance,
                                fline=self.forget_line,
                            ),
                        },
                    }
                )

        # estimate forgetting time
        for stm_obj in stm_list:
            init_mu = stm_obj["forgetting_curve"]["mu"]

            # Give more weight when there's objects and people nearby
            nearby_people = self.count_nearby_people(
                stm_obj["position"][:2],
                self.max_dist,
                stm_obj["updated_at_ts"]["lb"],
                tstamp,
            )
            nearby_objects = self.count_nearby_objects(
                stm_obj["position"][:2],
                self.max_dist,
                stm_obj["updated_at_ts"]["lb"],
                tstamp,
            )

            init_mu += (nearby_people / 10) + (nearby_objects / 20)

            init_mu = min(init_mu, 1.0)

            if stm_obj["forgetting_curve"]["mu"] != init_mu:
                stm_obj["forgetting_curve"]["mu"] = init_mu

            self.update_forget_time(stm_obj, tstamp)

        return stm_list

    def count_nearby_people(
        self, pos: List[float], dist: float, t0: float, tf: float
    ) -> int:
        return self.stm_coll.database.per.count_documents(
            filter={
                "$or": [
                    {
                        "$nor": [
                            {"last_recog.updated_at_ts.lb": {"$gt": t0}},
                            {"last_recog.updated_at_ts.ub": {"$lt": tf}},
                        ],
                        "last_recog.body_location": {
                            "$geoWithin": {"$center": [pos, dist]}
                        },
                    },
                    {
                        "$nor": [
                            {"prev_recogs.updated_at_ts.lb": {"$gt": t0}},
                            {"prev_recogs.updated_at_ts.ub": {"$lt": tf}},
                        ],
                        "prev_recogs.body_location": {
                            "$geoWithin": {"$center": [pos, dist]}
                        },
                    },
                ]
            }
        )

    def count_nearby_objects(
        self, pos: List[float], dist: float, t0: float, tf: float
    ) -> int:
        return self.stm_coll.database.obj.count_documents(
            filter={
                "$or": [
                    {
                        "$nor": [
                            {"last_recog.updated_at_ts.lb": {"$gt": t0}},
                            {"last_recog.updated_at_ts.ub": {"$lt": tf}},
                        ],
                        "last_recog.location_global": {
                            "$geoWithin": {"$center": [pos, dist]}
                        },
                    },
                    {
                        "$nor": [
                            {"prev_recogs.updated_at_ts.lb": {"$gt": t0}},
                            {"prev_recogs.updated_at_ts.ub": {"$lt": tf}},
                        ],
                        "prev_recogs.location_global": {
                            "$geoWithin": {"$center": [pos, dist]}
                        },
                    },
                ]
            }
        )

    def callback(self) -> None:
        tf = get_current_ts(self.node)

        sensormem_contents = list(
            self.sm_coll.find(
                filter={"created_at_ts": {"$gte": self.last_ts, "$lte": tf}},
                sort=[("created_at_ts", 1)],
            )
        )

        latest_stm = self.stm_coll.find_one(
            filter={}, sort=[("updated_at_ts.ub", -1)]
        )

        if latest_stm is None:
            latest_stm = {}

        # STM Memorizing (1)
        # timestamp, increasing -> decreasing
        to_insert = self.create_stm_from_sm(sensormem_contents, tf)
        to_insert.reverse()
        to_update = []

        # Integrate Sensor Memory if in same place as last Short-Term Memory
        # Latest Sensor Memory
        if latest_stm and to_insert:
            # Earliest sensor memory
            tail = to_insert.pop()

            if (
                math.dist(latest_stm["position"][:2], tail["position"][:2])
                > self.dist_tol
                or math.dist(latest_stm["orientation"], tail["orientation"])
                > self.dist_tol
            ):  # Too far to update STM
                to_insert.append(tail)
            else:
                latest_stm["updated_at_ts"]["ub"] = tail["updated_at_ts"]["ub"]
                self.update_forget_time(latest_stm, tf)
                to_update = [latest_stm]

        self.memorize(sensormem_contents, to_update, to_insert, tf)

        self.last_ts = tf

        self.logger.debug(
            f"[STM-{self.stm_coll.full_name.upper()}] "
            + f"Memorized ({len(sensormem_contents)})."
        )
