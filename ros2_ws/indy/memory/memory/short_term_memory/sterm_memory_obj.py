#!/usr/bin/env python
# coding: utf-8 -*-

"""Short-Term Object Recognition Memory Module"""

import math
from dataclasses import dataclass
from typing import List

from ..util import get_current_ts
from .sterm_memory_base import ShortTermMemoryBase


@dataclass
class ShortTermObjMemory(ShortTermMemoryBase):
    """Class for Short-Term Object Recognition Memory Module"""

    def __post_init__(self):
        super().__post_init__()
        self.setup_index(self.stm_coll, "last_recog.updated_at_ts", 1)
        self.setup_index(
            self.stm_coll,
            "last_recog.location_global",
            "2d",
            min=-10000.0,
            max=10000.0,
        )
        self.setup_index(self.stm_coll, "prev_recogs.updated_at_ts", 1)
        self.setup_index(
            self.stm_coll,
            "prev_recogs.location_global",
            "2d",
            min=-10000.0,
            max=10000.0,
        )

        # Process existing memory (leftovers)
        self.last_ts = 0
        self.callback()

    def create_stm_obj_from_sm(self, sm_obj: dict, tstamp: float) -> dict:
        """Convert Sensor objects into Short-Term Memory Objects"""
        stm_obj = {}

        # Fields that remain the same
        for k in [
            "instance_id",
            "name",
            "class_id",
            "attributes",
            "name_alias",
            "camera_res",
        ]:
            if k in sm_obj:
                stm_obj[k] = sm_obj[k]
        # Fields that we are not saving (YET):
        # "attributes", "recog_results"

        stm_obj["last_recog"] = {
            k: sm_obj[k]
            for k in [
                "location_global",
                "location_sensor",
                "location_img",
                "confidence",
            ]
        }

        stm_obj["last_recog"]["updated_at_ts"] = {
            "lb": sm_obj["created_at_ts"],
            "ub": tstamp,
        }

        stm_obj["prev_recogs"] = []

        stm_obj["location_box"] = dict(
            zip(["x", "y", "z"], sm_obj["location_box"])
        )

        # New Fields
        stm_obj["alt_instance_ids"] = [sm_obj["instance_id"]]

        mu = 0.0

        # We use logistic equation to adjust impression values
        # Distance between Centroid and Screen Center -- 1=center
        center_point = [
            sm_obj["camera_res"][0] / 2,
            sm_obj["camera_res"][1] / 2,
        ]
        max_dist = math.dist(center_point, [0, 0])
        dist_to_center = math.dist(center_point, sm_obj["location_img"][:2])
        mu += self.f_logistic(dist_to_center / max_dist, 0.5, 1, -8)

        # Ratio of space occupied by location_img within the camera_res area
        # self.f_logistic(x, 0.4, 1, 12)
        area_obj = sm_obj["location_img"][2] * sm_obj["location_img"][3]
        area_camera = sm_obj["camera_res"][0] * sm_obj["camera_res"][1]
        mu += self.f_logistic(area_obj / area_camera, 0.5, 1, 12)

        mu += sm_obj["confidence"]

        stm_obj["forgetting_curve"] = {
            # This one changes on every re-perception
            "mu": mu,
            "a": self.a_decay,
            "d": self.d_balance,
            "f_line": self.forget_line,
            "forget_time": self.estimate_forgetting_t(
                mu=mu,
                a=self.a_decay,
                t=tstamp,
                d=self.d_balance,
                fline=self.forget_line,
            ),
        }

        return stm_obj

    def compare_objects(self, old_obj: dict, new_obj: dict) -> bool:
        """Attempt to identify if a new Object Recog Memory is the same as an old one"""
        if old_obj["class_id"] != new_obj["class_id"]:
            return False

        # Check if instance_id is known
        if (
            old_obj["instance_id"] == new_obj["instance_id"]
            or new_obj["instance_id"] in old_obj["alt_instance_ids"]
        ):
            return True

        # Try to re-id
        # 1. Check if centroid of new_obj is inside db_obj's box
        if self.check_point_in_box(
            old_obj["location_box"], new_obj["last_recog"]["location_global"]
        ):
            return True

        # 2. If not, is the centroid close enough to db_obj?
        # (Very naive approach)
        centroid_dist = math.dist(
            new_obj["last_recog"]["location_global"],
            old_obj["last_recog"]["location_global"],
        )

        # box_diam = (
        #     (db_obj["location_box"][0][-1] + db_obj["location_box"][0][0])/2 +
        #     (db_obj["location_box"][1][-1] + db_obj["location_box"][1][0])/2
        # )/2

        # if centroid_dist < estimated diameter of db_obj:
        if centroid_dist < 1e-2:
            return True
        return False

    def compare_recogs(self, old_rec: dict, new_rec: dict) -> bool:
        """Attempt to identify if a new recognition data is close to an old one"""
        return all(
            math.dist(old_rec[k], new_rec[k]) < 1e-2
            for k in ["location_sensor", "location_img", "location_global"]
        )

    def merge_stm_objs(
        self, old_obj: dict, new_obj: dict, tstamp: float
    ) -> dict:
        """Incorporate a new recognition into an existing short-term memory"""
        stm_obj = {}

        if "_id" in new_obj:
            stm_obj["_id"] = new_obj["_id"]
        elif "_id" in old_obj:
            stm_obj["_id"] = old_obj["_id"]

        old_instance_id = old_obj["instance_id"]

        # Fields that remain the same
        for k in ["instance_id", "name", "class_id", "name_alias"]:
            if k in new_obj:
                stm_obj[k] = new_obj[k]

        stm_obj["last_recog"] = new_obj["last_recog"]
        if not self.compare_recogs(
            old_obj["last_recog"], new_obj["last_recog"]
        ):
            stm_obj["prev_recogs"] = self.memory_list_add(
                old_obj["prev_recogs"], old_obj["last_recog"]
            )
        else:
            stm_obj["last_recog"]["updated_at_ts"]["lb"] = old_obj[
                "last_recog"
            ]["updated_at_ts"]["lb"]
            stm_obj["prev_recogs"] = old_obj["prev_recogs"]

        stm_obj["last_recog"]["updated_at_ts"]["ub"] = tstamp

        # Box Update
        # Shift old box
        old_box_shift = self.shift_box(
            old_obj["last_recog"]["location_global"],
            new_obj["last_recog"]["location_global"],
            old_obj["location_box"],
            new_obj["location_box"],
        )
        stm_obj["location_box"] = self.join_boxes(
            old_box_shift, new_obj["location_box"]
        )

        stm_obj["alt_instance_ids"] = old_obj["alt_instance_ids"]
        for alt_instance_id in new_obj["alt_instance_ids"]:
            if alt_instance_id not in stm_obj["alt_instance_ids"]:
                stm_obj["alt_instance_ids"].append(alt_instance_id)

        stm_obj["attributes"] = old_obj["attributes"][:] + [
            attr
            for attr in new_obj["attributes"]
            if attr not in old_obj["attributes"]
        ]

        # New instance_id of a previously-recognized object
        if (
            old_instance_id != new_obj["instance_id"]
            and old_instance_id not in stm_obj["alt_instance_ids"]
        ):
            stm_obj["alt_instance_ids"].append(old_instance_id)

        stm_obj["camera_res"] = new_obj["camera_res"]

        stm_obj["forgetting_curve"] = old_obj["forgetting_curve"].copy()
        curr_mu = 0.0

        # Compute
        # We use logistic equation to adjust impression values
        # Distance between Centroid and Screen Center -- 1=center
        latest_img = new_obj["last_recog"]["location_img"]
        center_point = [
            new_obj["camera_res"][0] / 2,
            new_obj["camera_res"][1] / 2,
        ]
        curr_mu += self.f_logistic(
            math.dist(center_point, latest_img[:2])
            / math.dist(center_point, [0, 0]),
            0.6,
            1,
            -8,
        )

        # Ratio of space occupied by location_img within the camera_res area
        curr_mu += self.f_logistic(
            (latest_img[2] * latest_img[3])
            / (new_obj["camera_res"][0] * new_obj["camera_res"][1]),
            0.4,
            1,
            12,
        )

        curr_mu += new_obj["last_recog"]["confidence"]

        # Adjust confidence / memorability
        new_mu = (
            curr_mu
            if stm_obj["forgetting_curve"]["mu"] <= curr_mu
            else (stm_obj["forgetting_curve"]["mu"] + curr_mu) / 2
        )

        stm_obj["forgetting_curve"]["mu"] = new_mu
        self.update_forget_time(stm_obj, tstamp)

        return stm_obj

    def convert_lists_sm_to_stm(
        self, sm_obj_list: List[dict], tstamp: float
    ) -> List[dict]:
        """Converts a list of Sensor Memory objects into Short-term Memory objects"""
        stm_objs = []

        for sm_obj in sm_obj_list:

            # 0. Ignore negative instance_id <-- these are not "recognized"
            if sm_obj["instance_id"] <= 0:
                continue

            # 1. Convert sm_obj to stm_obj
            new_stm_obj = self.create_stm_obj_from_sm(sm_obj, tstamp)

            # 2. If ID already in stm_objs (compare), merge
            is_memorized = False
            i = 0
            for i, old_stm_obj in enumerate(stm_objs):
                if self.compare_objects(old_stm_obj, new_stm_obj):
                    is_memorized = True
                    break
            if is_memorized:
                stm_objs[i] = self.merge_stm_objs(
                    stm_objs[i], new_stm_obj, tstamp
                )
            else:
                # 3. If not, add new stm obj to stm_objs
                stm_objs.append(new_stm_obj)

        return stm_objs

    def callback(self) -> None:
        tf = get_current_ts(self.node)

        sensormem_contents = list(
            self.sm_coll.find(
                # filter={"created_at_ts": {"$gte": self.last_ts, "$lte": tf}},
                filter={"created_at_ts": {"$lte": tf}},  # fetch all the past
                sort=[
                    ("created_at_ts", 1),
                    ("class_id", 1),
                    ("instance_id", 1),
                ],
            )
        )

        # STM Memorizing (1)
        shorttermmem_contents = (
            list(
                self.stm_coll.find(
                    filter={
                        "$nor": [
                            {"last_recog.updated_at_ts.lb": {"$gt": tf}},
                            {
                                "last_recog.updated_at_ts.ub": {
                                    "$lt": self.last_ts
                                }
                            },
                        ]
                    },
                    sort=[
                        ("last_recog.updated_at_ts.lb", 1),
                        ("class_id", 1),
                        ("instance_id", 1),
                    ],
                )
            )
            if self.stm_level > 0
            else []
        )

        sensormem_as_stm = (
            self.convert_lists_sm_to_stm(sensormem_contents, tf)
            if self.stm_level > 0
            else []
        )

        to_insert = set(range(len(sensormem_as_stm)))
        to_update = set()

        for i, sm_doc in enumerate(sensormem_as_stm):
            updated_mem = None
            j, stm_doc = 0, {}
            for j, stm_doc in enumerate(shorttermmem_contents):
                if self.compare_objects(stm_doc, sm_doc):
                    updated_mem = self.merge_stm_objs(stm_doc, sm_doc, tf)
                    break
            if updated_mem is not None:
                shorttermmem_contents[j] = updated_mem
                to_insert.remove(i)
                to_update.add(j)

        self.memorize(
            sensormem_contents,
            [shorttermmem_contents[i] for i in to_update],
            [sensormem_as_stm[i] for i in to_insert],
            tf,
        )

        self.last_ts = tf

        self.logger.info(
            f"[STM_{self.stm_coll.name.upper()}] Memorized "
            + f"({len(sensormem_contents)})."
        )
