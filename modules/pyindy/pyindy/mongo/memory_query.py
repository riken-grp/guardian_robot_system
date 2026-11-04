#!/usr/bin/env python
# coding: utf-8 -*-

"""Indy's Memory System Query API Module (ver 0.1)"""
from __future__ import annotations

import traceback
from collections import Counter
from datetime import datetime, timedelta
from heapq import merge
from typing import Any, List, Tuple, Union

from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

from ..llm.embed_db import OpenAiEmbedDB
from .memory_func import MemoryFunction

Duration = Union[float, timedelta]


def get_duration(t: Union[float, timedelta]) -> Tuple[float, float]:
    """Returns timestamps between now and a time in the past"""
    now = datetime.now().timestamp()
    if isinstance(t, timedelta):
        t = t.total_seconds()
    return now, now - t


def weighted_score(
    time_diff: float,
    time_d_max: float,
    dist: float,
    weight_age: float,
    weight_dist: float,
) -> float:
    """Weight function.
    Lower is better.
    """
    return 1 - (
        weight_age * (1 - time_diff / time_d_max)
        + weight_dist * (1 - dist / 2)
    )


class IndyMemoryRecall(MemoryFunction):
    """API Class for the Memory System. This interface can be used to make queries."""

    db_sm: Database
    db_stm: Database
    db_ltm: Database
    embed_db: OpenAiEmbedDB | None = None

    def __init__(
        self, db_uri: str, db_port: int, embed_db: OpenAiEmbedDB | None = None
    ) -> None:
        client = MongoClient(db_uri, db_port)
        self.db_sm = client.sensor_memory
        self.db_stm = client.short_term_memory
        self.db_ltm = client.long_term_memory
        if embed_db:
            self.embed_db = embed_db

        db_dic = self.db_sm.client.dictionary

        self.obj_names = {
            i["class_id"]: i["name_alias"]
            for i in db_dic.object_names.find({})
        }

        self.locations = {
            i["class_id"]: i["name_alias"]
            for i in db_dic.person_names.find({})
        }

        self.loc_names = {
            i["name"]: i["location"] for i in db_dic.location_names.find({})
        }

    # Scene Graph Functions
    def get_latest_scenegraph(self) -> Any:
        return self.db_sm.sce.find_one(filter={}, sort=[("created_at_ts", -1)])

    # Speech Functions
    def get_speech_by_person(
        self, human_id: int, t: Duration = 5, only_latest: bool = False
    ) -> list:
        return self.get_speech_by("human_id", human_id, t, only_latest)

    def get_speech_by_instance(
        self, instance_id: int, t: Duration = 5, onlylatest: bool = False
    ) -> list:
        """Returns the latest thing a person with instance ID `instance_id` has said."""
        return self.get_speech_by("instance_id", instance_id, t, onlylatest)

    def get_speech_by(
        self,
        query_type: str,
        query_id: int,
        t: Duration = 5,
        only_latest_one: bool = False,
    ) -> list:
        """Returns the latest thing a person has said, based on a given query type
        Updates the Impression of the Short-Term Memory forgetting curve."""
        duration_t = get_duration(t)

        if only_latest_one:
            # Query Sensor Memory
            sm_results = self.db_sm.dia.find_one(
                filter={
                    "origin": "asr",
                    f"metadata.{query_type}": query_id,
                    "metadata.recog_time": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                },
                sort=[("created_at_ts", -1)],
            )

            if sm_results:
                return [
                    {
                        "uttr": sm_results["utterance"],
                        "tstamp": sm_results["created_at_ts"],
                    }
                ]

            # Query Short-Term Memory
            stm_results = self.db_stm.dia.find_one(
                filter={
                    "type": "chat",
                    "convo_start_ts": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                    f"participants.{query_type}": query_id,
                },
                sort=[("convo_start_ts", -1)],
            )

            if stm_results:
                stm_results["forgetting_curve"]["mu"] *= 1.05
                self.update_forget_time(stm_results, duration_t[0])
                self.db_stm.dia.replace_one(
                    filter={"_id": stm_results["_id"]},
                    replacement=stm_results,
                )
                return [
                    {
                        "uttr": stm_results["memory"],
                        "tstamp": stm_results["created_at_ts"],
                    }
                ]

            return []

        # Return multiple
        sm_results = list(
            self.db_sm.dia.find(
                filter={
                    "origin": "asr",
                    f"metadata.{query_type}": query_id,
                    "metadata.recog_time": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                },
                sort=[("created_at_ts", -1)],
            )
        )

        stm_results = list(
            self.db_stm.dia.find(
                filter={
                    "type": "chat",
                    "convo_start_ts": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                    f"participants.{query_type}": query_id,
                },
                sort=[("convo_start_ts", -1)],
            )
        )

        ret_set = []

        for res in stm_results:
            res["forgetting_curve"]["mu"] *= 1.05
            self.update_forget_time(res, duration_t[0])
            self.db_stm.dia.replace_one(
                filter={"_id": res["_id"]}, replacement=res
            )
            ret_set.append(
                {"uttr": res["memory"], "tstamp": res["created_at_ts"]}
            )

        ret_set.extend(
            [
                {"uttr": res["utterance"], "tstamp": res["created_at_ts"]}
                for res in sm_results
            ]
        )

        return ret_set

    def get_asr_range(self, t: Duration = 5) -> list:
        """Returns all speech reacognized by Indy within the last `t` seconds.
        Does not update Forgetting Curve at the moment."""
        duration_t = get_duration(t)

        # Sensor Memory
        sm_results = list(
            self.db_sm.dia.find(
                filter={
                    "origin": "asr",
                    "metadata.recog_time": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                },
                sort=[("created_at_ts", -1)],
            )
        )

        # Short-term Memory
        stm_results = list(
            self.db_stm.dia.find(
                filter={
                    "type": "chat",
                    "convo_start_ts": {
                        "$gte": duration_t[1],
                        "$lt": duration_t[0],
                    },
                },
                sort=[("convo_start_ts", -1)],
            )
        )

        ret_set = []

        for res in stm_results:
            res["forgetting_curve"]["mu"] *= 1.05
            self.update_forget_time(res, duration_t[0])
            self.db_stm.dia.replace_one(
                filter={"_id": res["_id"]}, replacement=res
            )
            ret_set.append(
                {"uttr": res["memory"], "tstamp": res["created_at_ts"]}
            )

        ret_set.extend(
            [
                {"uttr": res["utterance"], "tstamp": res["created_at_ts"]}
                for res in sm_results
            ]
        )

        return ret_set

    # Persons Functions
    def get_persons_by_location(
        self,
        location_id: str,
        distance: float,
        t: Duration = 3600,
        reacquire: bool = True,
    ) -> dict:
        """Returns the Class IDs of all people within `distance` of `location_id`
        within the last `t` seconds."""

        if location_id not in self.locations:
            return {}

        instances = Counter()
        duration_t = get_duration(t)

        if not reacquire:
            # 1: Get instance_id within duration
            # 1.1: Get instance_id from Sensor Memory
            all_ids = set(
                p["instance_id"]
                for p in self.db_sm.per.find(
                    filter={
                        "created_at_ts": {
                            "$gte": duration_t[1],
                            "$lte": duration_t[0],
                        },
                        "body_location": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 1.2: Get instance_id from Short-Term Memory
            stm_ptr = self.db_stm.per.find(
                filter={
                    "$or": [
                        {
                            "$nor": [
                                {
                                    "last_recog.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ],
                            "last_recog.body_location": {
                                "$geoWithin": {
                                    "$center": [
                                        self.locations[location_id],
                                        distance,
                                    ]
                                }
                            },
                        },
                        {
                            "$nor": [
                                {
                                    "prev_recogs.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ],
                            "prev_recogs.body_location": {
                                "$geoWithin": {
                                    "$center": [
                                        self.locations[location_id],
                                        distance,
                                    ]
                                }
                            },
                        },
                    ]
                },
                projection={
                    "_id": False,
                    "instance_id": True,
                    "alt_instance_ids": True,
                },
            )

            for doc in stm_ptr:
                all_ids.update(doc["alt_instance_ids"] + [doc["instance_id"]])

            # PART 2: From those get all the instances IDs that were not BEFORE
            # 2.1: Get instance_id from Sensor Memory
            prev_instances = set(
                p["instance_id"]
                for p in self.db_sm.per.find(
                    filter={
                        "created_at_ts": {"$lt": duration_t[1]},
                        "instance_id": {"$in": list(all_ids)},
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 2.2: Get instance_id from Short-Term Memory
            stm_prev_res = self.db_stm.per.find(
                filter={
                    "$and": [
                        {
                            "$or": [
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$or": [
                                {"instance_id": {"$in": list(all_ids)}},
                                {"alt_instance_ids": {"$in": list(all_ids)}},
                            ]
                        },
                    ]
                },
                projection={
                    "instance_id": True,
                    "alt_instance_ids": True,
                    "_id": False,
                },
            )

            for doc in stm_prev_res:
                prev_instances.update(
                    doc["alt_instance_ids"] + [doc["instance_id"]]
                )

            current_ids = all_ids - prev_instances

            # PART 3: Create Queries to fetch only the new Instance IDs
            sm_filter = {"instance_id": {"$in": list(current_ids)}}

            stm_filter = {
                "$or": [
                    {"instance_id": {"$in": list(current_ids)}},
                    {"alt_instance_ids": {"$in": list(current_ids)}},
                ]
            }

        else:
            sm_filter = {
                "created_at_ts": {
                    "$gte": duration_t[1],
                    "$lte": duration_t[0],
                },
                "body_location": {
                    "$geoWithin": {
                        "$center": [
                            self.locations[location_id],
                            distance,
                        ]
                    }
                },
            }

            stm_filter = {
                "$or": [
                    {
                        "$nor": [
                            {
                                "last_recog.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "last_recog.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                        "last_recog.body_location": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                    {
                        "$nor": [
                            {
                                "prev_recogs.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "prev_recogs.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                        "prev_recogs.body_location": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                ]
            }

        instances.update(
            p["class_id"]
            for p in self.db_sm.per.find(
                filter=sm_filter,
                projection={
                    "instance_id": True,
                    "class_id": True,
                    "_id": False,
                },
            )
        )
        for p in self.db_stm.per.find(filter=stm_filter):
            # add  to instances, update forgetfulness in database
            instances.update([p["class_id"]])
            self.update_forget_time(p, duration_t[0])
            self.db_stm.per.replace_one(filter={"id": p["_id"]}, replacement=p)

        if not instances:
            return {}
        return dict(instances)

    # Persons Objects Functions
    def get_persons_recent(
        self, t: Duration = 600, reacquire: bool = False, recall: bool = True
    ) -> list:
        """Return all the Instance IDs of all objects perceived
        in the last `t` seconds."""

        duration_t = get_duration(t)

        if not reacquire:
            # 1: Get instance_ids within duration
            # 1.1 Get instance_id from Sensor Memory
            all_ids = set(
                p["instance_id"]
                for p in self.db_sm.per.find(
                    filter={
                        "created_at_ts": {
                            "$gte": duration_t[1],
                            "$lte": duration_t[0],
                        }
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 1.2: Get instance_id from Short-Term Memory
            stm_ptr = self.db_stm.per.find(
                filter={
                    "$or": [
                        {
                            "$nor": [
                                {
                                    "last_recog.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$nor": [
                                {
                                    "prev_recogs.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                    ]
                },
                projection={
                    "_id": False,
                    "instance_id": True,
                    "alt_instance_ids": True,
                },
            )

            for doc in stm_ptr:
                all_ids.update(doc["alt_instance_ids"] + [doc["instance_id"]])

            # PART 2: From those get all the instances IDs that were not BEFORE
            # 2.1: Get instance_id from Sensor Memory
            prev_instances = set(
                p["instance_id"]
                for p in self.db_sm.per.find(
                    filter={
                        "created_at_ts": {"$lt": duration_t[1]},
                        "instance_id": {"$in": list(all_ids)},
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 2.2: Get instance_id from Short-Term Memory
            stm_prev_res = self.db_stm.per.find(
                filter={
                    "$and": [
                        {
                            "$or": [
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$or": [
                                {"instance_id": {"$in": list(all_ids)}},
                                {"alt_instance_ids": {"$in": list(all_ids)}},
                            ]
                        },
                    ]
                },
                projection={
                    "instance_id": True,
                    "alt_instance_ids": True,
                    "_id": False,
                },
            )

            for doc in stm_prev_res:
                prev_instances.update(
                    doc["alt_instance_ids"] + [doc["instance_id"]]
                )

            current_ids = all_ids - prev_instances

            # PART 3: Create Query to fetch only the new Instance IDs
            sm_filter = {"instance_id": {"$in": list(current_ids)}}

            stm_filter = {
                "$or": [
                    {"instance_id": {"$in": list(current_ids)}},
                    {"alt_instance_ids": {"$in": list(current_ids)}},
                ]
            }

        else:
            sm_filter = {
                "created_at_ts": {
                    "$gte": duration_t[1],
                    "$lte": duration_t[0],
                }
            }

            stm_filter = {
                "$or": [
                    {
                        "$nor": [
                            {
                                "last_recog.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "last_recog.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                    },
                    {
                        "$nor": [
                            {
                                "prev_recogs.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "prev_recogs.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                    },
                ]
            }

        all_results = {
            p["instance_id"]
            for p in self.db_sm.per.find(
                filter=sm_filter,
                projection={
                    "instance_id": True,
                    "class_id": True,
                    "_id": False,
                },
            )
        }
        for p in self.db_stm.per.find(filter=stm_filter):
            # add  to instances, update forgetfulness in database
            all_results.update(p["alt_instance_ids"] + [p["instance_id"]])
            if recall:
                self.update_forget_time(p, duration_t[0])
                self.db_stm.per.replace_one(
                    filter={"id": p["_id"]}, replacement=p
                )

        return list(all_results)

    def get_objects_recent(
        self, t: Duration = 600, reacquire: bool = False, recall: bool = True
    ) -> list:
        """Return all the Instance IDs of all objects perceived
        in the last `t` seconds."""

        duration_t = get_duration(t)

        if not reacquire:
            # 1: Get instance_ids within duration
            # 1.1 Get instance_id from Sensor Memory
            all_ids = set(
                p["instance_id"]
                for p in self.db_sm.obj.find(
                    filter={
                        "created_at_ts": {
                            "$gte": duration_t[1],
                            "$lte": duration_t[0],
                        }
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 1.2: Get instance_id from Short-Term Memory
            stm_ptr = self.db_stm.obj.find(
                filter={
                    "$or": [
                        {
                            "$nor": [
                                {
                                    "last_recog.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$nor": [
                                {
                                    "prev_recogs.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                    ]
                },
                projection={
                    "_id": False,
                    "instance_id": True,
                    "alt_instance_ids": True,
                },
            )

            for doc in stm_ptr:
                all_ids.update(doc["alt_instance_ids"] + [doc["instance_id"]])

            # PART 2: From those get all the instances IDs that were not BEFORE
            # 2.1: Get instance_id from Sensor Memory
            prev_instances = set(
                p["instance_id"]
                for p in self.db_sm.obj.find(
                    filter={
                        "created_at_ts": {"$lt": duration_t[1]},
                        "instance_id": {"$in": list(all_ids)},
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 2.2: Get instance_id from Short-Term Memory
            stm_prev_res = self.db_stm.obj.find(
                filter={
                    "$and": [
                        {
                            "$or": [
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$or": [
                                {"instance_id": {"$in": list(all_ids)}},
                                {"alt_instance_ids": {"$in": list(all_ids)}},
                            ]
                        },
                    ]
                },
                projection={
                    "instance_id": True,
                    "alt_instance_ids": True,
                    "_id": False,
                },
            )

            for doc in stm_prev_res:
                prev_instances.update(
                    doc["alt_instance_ids"] + [doc["instance_id"]]
                )

            current_ids = all_ids - prev_instances

            # PART 3: Create Query to fetch only the new Instance IDs
            sm_filter = {"instance_id": {"$in": list(current_ids)}}

            stm_filter = {
                "$or": [
                    {"instance_id": {"$in": list(current_ids)}},
                    {"alt_instance_ids": {"$in": list(current_ids)}},
                ]
            }

        else:
            sm_filter = {
                "created_at_ts": {
                    "$gte": duration_t[1],
                    "$lte": duration_t[0],
                }
            }

            stm_filter = {
                "$or": [
                    {
                        "$nor": [
                            {
                                "last_recog.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "last_recog.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                    },
                    {
                        "$nor": [
                            {
                                "prev_recogs.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "prev_recogs.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                    },
                ]
            }

        all_results = {
            p["instance_id"]
            for p in self.db_sm.obj.find(
                filter=sm_filter,
                projection={
                    "instance_id": True,
                    "class_id": True,
                    "_id": False,
                },
            )
        }

        for p in self.db_stm.obj.find(filter=stm_filter):
            # add  to instances, update forgetfulness in database
            all_results.update(p["alt_instance_ids"] + [p["instance_id"]])
            if recall:
                self.update_forget_time(p, duration_t[0])
                self.db_stm.obj.replace_one(
                    filter={"id": p["_id"]}, replacement=p
                )

        return list(all_results)

    def get_objects_k_recent(self, k: int) -> List[dict]:
        """Return the Instance IDs of the latest k objects perceived."""

        # tf = datetime.now().timestamp()

        sm_objs = []
        found_ids = set()

        for o in self.db_sm.obj.find(filter={}, sort=[("created_at_ts", -1)]):
            if o["instance_id"] not in found_ids:
                ret_obj = {"instance_ids": [o["instance_id"]]}
                ret_obj.update(
                    {
                        k: o[k]
                        for k in [
                            "name",
                            "class_id",
                            "attributes",
                            "name_alias",
                        ]
                    }
                )
                sm_objs.append(ret_obj)
                found_ids.add(o["instance_id"])
            if len(sm_objs) >= k:
                break

        # If we need to get more objects from STM
        rem = k - len(sm_objs)
        if rem > 0:
            for o in self.db_stm.obj.find(
                filter={
                    "instance_id": {"$nin": list(found_ids)},
                    "alt_instance_ids": {"$nin": list(found_ids)},
                },
                limit=rem,
                sort=[("last_recog.updated_at_ts.ub", -1)],
            ):
                ret_obj = {
                    "instance_ids": [o["instance_id"]] + o["alt_instance_ids"]
                }
                ret_obj.update(
                    {
                        k: o[k]
                        for k in [
                            "name",
                            "class_id",
                            "attributes",
                            "name_alias",
                        ]
                    }
                )
                sm_objs.append(ret_obj)

        return sm_objs

    def get_objects_by_location(
        self,
        location_id: str,
        distance: float,
        t: Duration = 3600,
        reacquire: bool = False,
    ) -> list:
        """Return all the Instance IDs of all objects perceived
        in the last `t` seconds near `location_id`."""

        duration_t = get_duration(t)

        if location_id not in self.locations:
            return []

        if not reacquire:
            # 1: Get instance_id within duration
            # 1.1: Get instance_id from Sensor Memory
            all_ids = set(
                p["instance_id"]
                for p in self.db_sm.obj.find(
                    filter={
                        "created_at_ts": {
                            "$gte": duration_t[1],
                            "$lte": duration_t[0],
                        },
                        "location_global": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 1.2: Get instance_id from Short-Term Memory
            stm_ptr = self.db_stm.obj.find(
                filter={
                    "$or": [
                        {
                            "$nor": [
                                {
                                    "last_recog.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ],
                            "last_recog.location_global": {
                                "$geoWithin": {
                                    "$center": [
                                        self.locations[location_id],
                                        distance,
                                    ]
                                }
                            },
                        },
                        {
                            "$nor": [
                                {
                                    "prev_recogs.updated_at_ts.lb": {
                                        "$gt": duration_t[0]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ],
                            "prev_recogs.location_global": {
                                "$geoWithin": {
                                    "$center": [
                                        self.locations[location_id],
                                        distance,
                                    ]
                                }
                            },
                        },
                    ]
                },
                projection={
                    "_id": False,
                    "instance_id": True,
                    "alt_instance_ids": True,
                },
            )
            for doc in stm_ptr:
                all_ids.update(doc["alt_instance_ids"] + [doc["instance_id"]])

            # PART 2: From those get all the instances IDs that were not BEFORE
            # 2.1: Get instance_id from Sensor Memory
            prev_instances = set(
                p["instance_id"]
                for p in self.db_sm.obj.find(
                    filter={
                        "created_at_ts": {"$lt": duration_t[1]},
                        "instance_id": {"$in": list(all_ids)},
                    },
                    projection={"_id": False, "instance_id": True},
                )
            )

            # 2.2: Get instance_id from Short-Term Memory
            stm_prev_res = self.db_stm.obj.find(
                filter={
                    "$and": [
                        {
                            "$or": [
                                {
                                    "last_recog.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                                {
                                    "prev_recogs.updated_at_ts.ub": {
                                        "$lt": duration_t[1]
                                    }
                                },
                            ]
                        },
                        {
                            "$or": [
                                {"instance_id": {"$in": list(all_ids)}},
                                {"alt_instance_ids": {"$in": list(all_ids)}},
                            ]
                        },
                    ]
                },
                projection={
                    "instance_id": True,
                    "alt_instance_ids": True,
                    "_id": False,
                },
            )

            for doc in stm_prev_res:
                prev_instances.update(
                    doc["alt_instance_ids"] + [doc["instance_id"]]
                )

            current_ids = all_ids - prev_instances

            # PART 3: Create Queries to fetch only the new Instance IDs
            sm_filter = {"instance_id": {"$in": list(current_ids)}}

            stm_filter = {
                "$or": [
                    {"instance_id": {"$in": list(current_ids)}},
                    {"alt_instance_ids": {"$in": list(current_ids)}},
                ]
            }

        else:
            sm_filter = {
                "created_at_ts": {
                    "$gte": duration_t[1],
                    "$lte": duration_t[0],
                },
                "location_global": {
                    "$geoWithin": {
                        "$center": [self.locations[location_id], distance]
                    }
                },
            }

            stm_filter = {
                "$or": [
                    {
                        "$nor": [
                            {
                                "last_recog.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "last_recog.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                        "last_recog.location_global": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                    {
                        "$nor": [
                            {
                                "prev_recogs.updated_at_ts.lb": {
                                    "$gt": duration_t[0]
                                }
                            },
                            {
                                "prev_recogs.updated_at_ts.ub": {
                                    "$lt": duration_t[1]
                                }
                            },
                        ],
                        "prev_recogs.location_global": {
                            "$geoWithin": {
                                "$center": [
                                    self.locations[location_id],
                                    distance,
                                ]
                            }
                        },
                    },
                ]
            }

        all_results = {
            p["instance_id"]
            for p in self.db_sm.obj.find(
                filter=sm_filter,
                projection={
                    "instance_id": True,
                    "name": True,
                    "_id": False,
                },
            )
        }

        for p in self.db_stm.obj.find(filter=stm_filter):
            # add  to instances, update forgetfulness in database
            all_results.update(p["alt_instance_ids"] + [p["instance_id"]])
            self.update_forget_time(p, duration_t[0])
            self.db_stm.obj.replace_one(filter={"id": p["_id"]}, replacement=p)

        return list(all_results)

    def get_nearest_landmark(self, location: Tuple[float, float]) -> dict:
        """Find the nearest landmark to `location` [x, y]"""

        res = self.db_sm.client.dictionary.location_names.find_one(
            {"location": {"$near": list(location)}}
        )

        return res if res is not None else {}

    def get_entity_last_seen(
        self, collection: str, entity_class_id: int
    ) -> dict:
        """Get the last entity seen with ID `entity_class_id` of type `collection`"""

        entity = self.db_sm[collection].find_one(
            filter={"class_id": entity_class_id}, sort=[("created_at_ts", -1)]
        )

        if entity:
            return entity

        entity = self.db_stm[collection].find_one(
            filter={"class_id": entity_class_id},
            sort=[("last_recog.updated_at_ts.ub", -1)],
        )

        if entity:
            self.update_forget_time(entity, datetime.now().timestamp())
            self.db_stm[collection].replace_one(
                filter={"_id": entity}, replacement=entity
            )
            return entity

        return {}

    def get_object_last_seen(self, object_class_id: int) -> dict:
        """Get the last object seen with ID `object_class_id`"""
        return self.get_entity_last_seen("obj", object_class_id)

    def get_person_last_seen(self, person_class_id: int) -> dict:
        """Get the last person seen with ID `person_class_id`"""
        return self.get_entity_last_seen("per", person_class_id)

    def get_n_related_narratives(
        self, texts: List[str], n: int, limit: float = 1.0
    ) -> List[Tuple[float, str]]:
        if self.embed_db is None:
            return []
        """Find n entries in narrative memory,
        that are most closely related to the text"""

        embeds = sorted(
            self.embed_db.requestdoclist_text(
                "narrative", query_texts=texts, n=n
            )
            + self.embed_db.requestdoclist_text(
                "longterm", query_texts=texts, n=n
            ),
            key=lambda res: res[2],  # Sorted by distance
        )

        embeds = [em for em in embeds if em[2] <= limit]

        # Fetch full docs from MongoDB
        dia_cursor = self.db_stm.dia.find(
            filter={"_id": {"$in": [ObjectId(str(t[0])) for t in embeds]}},
            sort=[("created_at_ts", -1)],
        )

        ltm_cursor = self.db_ltm.longterm.find(
            filter={"_id": {"$in": [ObjectId(str(t[0])) for t in embeds]}},
            sort=[("created_at_ts", -1)],
        )

        merged = [
            (
                mgd["created_at_ts"],
                (mgd["memory"] if "memory" in mgd else mgd["today_summ"]),
            )
            for mgd in merge(
                dia_cursor, ltm_cursor, key=lambda o: o["created_at_ts"]
            )
        ]

        # Merge
        return merged

    def get_update_n_related_narratives(
        self, texts: List[str], n: int, ts: float, limit: float = 1.0
    ) -> List[Tuple[float, str]]:
        if self.embed_db is None:
            return []
        """Find n entries in narrative memory,
        that are most closely related to the text"""

        embeds = sorted(
            self.embed_db.requestdoclist_text(
                "narrative", query_texts=texts, n=n
            )
            + self.embed_db.requestdoclist_text(
                "longterm", query_texts=texts, n=n
            ),
            key=lambda res: res[2],  # Sorted by distance
        )

        embeds = [em for em in embeds if em[2] <= limit]

        # Fetch full docs from MongoDB
        dia_list = list(
            self.db_stm.dia.find(
                filter={"_id": {"$in": [ObjectId(str(t[0])) for t in embeds]}},
                sort=[("created_at_ts", -1)],
            )
        )
        ltm_list = list(
            self.db_ltm.narrative.find(
                filter={"_id": {"$in": [ObjectId(str(t[0])) for t in embeds]}},
                sort=[("created_at_ts", -1)],
            )
        )

        merged = [
            (
                mgd["created_at_ts"],
                (mgd["memory"] if "memory" in mgd else mgd["today_summ"]),
            )
            for mgd in merge(
                dia_list, ltm_list, key=lambda o: o["created_at_ts"]
            )
        ]

        if len(merged) > n:
            merged = merged[:n]

        # memorize
        for stm in dia_list:
            stm["updated_at_ts"] = ts
            self.update_forget_time(stm, ts)
            self.db_stm.dia.replace_one(
                filter={"_id": stm["_id"]}, replacement=stm
            )

        for ltm in ltm_list:
            ltm["updated_at_ts"] = ts
            self.update_forget_time(ltm, ts)
            self.db_ltm.narrative.replace_one(
                filter={"_id": ltm["_id"]}, replacement=ltm
            )

        # Merge
        return merged

    def get_yesterday_conversations(self) -> List[Tuple[float, str]]:
        today = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        yesterday = today - timedelta(days=1)
        today, yesterday = today.timestamp(), yesterday.timestamp()

        memories: List[Tuple[float, str]] = []

        # Get Short-Term Narrative Memory
        stm_narr_crsr = self.db_stm.dia.find(
            filter={
                "created_at_ts": {"$lt": today, "$gte": yesterday},
                "type": "chat",
            },
            projection={"memory": 1, "created_at_ts": 1},
            sort=[("created_at_ts", 1)],
        )

        # Get Long-Term Memory
        ltm_crsr = self.db_ltm.longterm.find(
            filter={
                "created_at_ts": {"$lt": today, "$gte": yesterday},
            },
            projection={"today_summ": 1, "created_at_ts": 1},
            sort=[("created_at_ts", 1)],
        )

        # cycle through the pointers
        for mem in merge(
            stm_narr_crsr,
            ltm_crsr,
            key=lambda x: x["created_at_ts"],
        ):
            if "memory" in mem:
                memories.append((mem["created_at_ts"], mem["memory"]))
            elif "today_summ" in mem:
                memories.append((mem["created_at_ts"], mem["today_summ"]))

        return memories

    def get_previous_conversations_mmm(
        self, tf: float, n: int
    ) -> List[Tuple[float, str]]:
        memories: List[Tuple[float, str]] = []

        # Get Short-Term Memory
        stm_narr_crsr = self.db_stm.dia.find(
            filter={"created_at_ts": {"$lte": tf}, "type": "chat"},
            sort=[("created_at_ts", 1), ("type", 1)],
        )

        stm_narrs = {}
        for m in stm_narr_crsr:
            if m["created_at_ts"] in stm_narrs:
                stm_narrs[m["created_at_ts"]]["memory"] += " " + m["memory"]
            else:
                stm_narrs[m["created_at_ts"]] = m

        # Get Long-Term Memory
        ltm_crsr = self.db_ltm.longterm.find(
            filter={"created_at_ts": {"$lte": tf}},
            # projection={"today_summ": 1, "created_at_ts": 1},
            sort=[("created_at_ts", 1), ("type", 1)],
        )

        for mem in merge(
            stm_narrs.values(),
            ltm_crsr,
            key=lambda x: x["created_at_ts"],
        ):
            if "memory" in mem:
                memories.append((mem["created_at_ts"], mem["memory"]))
            elif "today_summ" in mem:
                memories.append((mem["created_at_ts"], mem["today_summ"]))

        return memories[-n:]

    def recall_narratives(
        self,
        text: List[str],
        n: int,
        ts: float,
        dist_limit: float = 1.0,
        weight_age=1.0,
        weight_dist=1.0,
    ) -> List[Tuple[float, str, float, float]]:
        if self.embed_db is None:
            return []

        weight_t = weight_age + weight_dist
        weight_age = weight_age / weight_t
        weight_dist = weight_dist / weight_t

        # Get all embeds that have data
        embeds = list(
            filter(
                lambda x: x[1] is not None
                and x[3] is not None
                and x[1]
                and x[3],
                self.embed_db.requestdoclist_text(
                    "narrative", query_texts=text, n=n
                )
                + self.embed_db.requestdoclist_text(
                    "longterm", query_texts=text, n=n
                ),
            )
        )
        try:
            max_time = max(embeds, key=lambda e: e[3]["ts"])[3]["ts"]
            min_time = min(embeds, key=lambda e: e[3]["ts"])[3]["ts"]
        except Exception as e:
            txt = f"traceback: {traceback.format_exc()} - {str(embeds)}"
            raise Exception(txt) from e

        time_range = (
            max_time - min_time if max_time != min_time else ts - min_time
        )
        # Sort based on weighted function
        embeds = sorted(
            [
                e
                + (
                    weighted_score(
                        ts - e[3]["ts"],
                        time_range,
                        e[2],
                        weight_age,
                        weight_dist,
                    ),
                )
                for e in embeds
            ],
            key=lambda x: x[-1],
        )

        embeds_dict = {em[0]: em for em in embeds if em[2] <= dist_limit}

        # Fetch full docs from MongoDB
        dia_list = list(
            self.db_stm.dia.find(
                filter={
                    "_id": {
                        "$in": [ObjectId(str(t)) for t in embeds_dict.keys()]
                    },
                    "memory": {"$nin": ["", " "]},
                },
                sort=[("created_at_ts", -1)],
            ),
        )

        ltm_list = list(
            self.db_ltm.narrative.find(
                filter={
                    "_id": {
                        "$in": [ObjectId(str(t)) for t in embeds_dict.keys()]
                    },
                    "today_summ": {"$nin": ["", " "]},
                },
                sort=[("created_at_ts", -1)],
            )
        )

        merged = [
            doc
            for doc in merge(
                dia_list, ltm_list, key=lambda o: o["created_at_ts"]
            )
            if ("memory" in doc and doc["memory"].strip())
            or ("today_summ" in doc and doc["today_summ"].strip())
        ]

        if len(merged) > n:
            merged = merged[:n]

        return [
            self.__reinforce_doc(doc, ts)
            + (
                embeds_dict[str(doc["_id"])][2],
                embeds_dict[str(doc["_id"])][-1],
            )
            for doc in merged
        ]

    def __reinforce_doc(self, doc: dict, ts: float) -> Tuple[float, str]:
        doc["updated_at_ts"] = ts
        self.update_forget_time(doc, ts)
        if self.db_stm.dia.count_documents(filter={"_id": doc["_id"]}):
            self.db_stm.dia.replace_one(
                filter={"_id": doc["_id"]}, replacement=doc
            )
        if self.db_ltm.narrative.count_documents(filter={"_id": doc["_id"]}):
            self.db_ltm.narrative.replace_one(
                filter={"_id": doc["_id"]}, replacement=doc
            )
        return (
            doc["created_at_ts"],
            (
                doc["memory"].strip()
                if "memory" in doc
                else doc["today_summ"].strip()
            ),
        )
