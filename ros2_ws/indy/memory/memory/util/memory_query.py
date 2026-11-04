#!/usr/bin/env python
# coding: utf-8 -*-

"""Indy's Memory System Query API Module.
Modifications to avoid excessive changes to PyIndy's code base."""

from heapq import merge
from typing import List, Tuple

from bson import ObjectId
from pyindy.llm.embed_db import OpenAiEmbedDB
from pyindy.mongo.memory_query import IndyMemoryRecall as PyIndyMemoryRecall
import traceback


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


class IndyMemoryRecall(PyIndyMemoryRecall):
    def __init__(
        self, db_uri: str, db_port: int, embed_db: OpenAiEmbedDB | None = None
    ) -> None:
        super().__init__(db_uri, db_port, embed_db)

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
