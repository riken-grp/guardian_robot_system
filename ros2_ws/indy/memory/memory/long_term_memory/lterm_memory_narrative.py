"""Long-Term Narrative Memory Module"""

from dataclasses import dataclass, field
from datetime import datetime
from sys import float_info
from typing import List
from zoneinfo import ZoneInfo

import numpy as np
from pymongo.collection import Collection
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup

from ..util import get_current_ts
from ..util.llm.embed_db import OpenAiEmbedDB
from ..util.llm.llm_base import LlmManager
from ..util.memory_func import MemoryFunction
from .lterm_memory_base import LongTermMemoryBase

JPN_TZINFO = ZoneInfo("Asia/Tokyo")


@dataclass
class LongTermNarrative(LongTermMemoryBase, MemoryFunction):
    """Class for Long-Term Narrative Memory"""

    last_intv_record: int = field(init=False)
    llm: LlmManager = field(init=False)
    embed_db: OpenAiEmbedDB | None = field(default=None, init=False)

    def __post_init__(self):
        super().__post_init__()
        self.ros_timer.destroy()

        self.setup_index(self.stm_coll, "created_at_ts", 1)
        # Get Module Params

        if self.ltm_level < 1:
            return

        self.llm = self.module_params["llm"]
        self.embed_db = (
            self.module_params["embed_db"]
            if "embed_db" in self.module_params
            else None
        )

        self.last_intv_record = datetime.fromtimestamp(
            self.last_ts - self.time_intv, tz=JPN_TZINFO
        ).day
        self.ros_timer = self.node.create_timer(
            self.time_intv,
            self.callback,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

    @property
    def time_scale(self) -> int:
        return self.forget_params["time_scale"]

    @property
    def time_intv(self) -> int:
        return self.forget_params["time_intv"]

    def callback(self, data=None) -> None:
        now_ts = get_current_ts(self.node)

        now_ts_day = datetime.fromtimestamp(now_ts, tz=JPN_TZINFO).day

        if now_ts_day == self.last_intv_record:
            return

        self.logger.info("[LTM] Processing Long-Term Memory")

        participants = set()
        # Retrieve Recent STM Chat Summaries
        try:
            stm_summaries = list(
                self.stm_coll.find(
                    filter={
                        "type": "chat",
                        "created_at_ts": {
                            "$gte": self.last_ts,
                            "$lt": now_ts,
                        },
                    },
                    sort=[("created_at_ts", -1)],
                )
            )
        except Exception as e:
            self.logger.error(
                f"[LTM] Unable to retrieve short-term chats: {str(e)}. "
            )
            stm_summaries = []

        if not stm_summaries:
            self.logger.debug("[LTM] No Short-Term Summaries found.")
            p_ts = self.last_ts
            self.forget_stm_final(self.stm_coll, now_ts)
            self.forget_memories_by_summarizing(now_ts)
            self.last_ts = p_ts
            return

        recent_txt = self.format_summary(
            "\n".join("- " + s["memory"] for s in stm_summaries)
        )

        try:
            summary = self.format_summary(
                self.llm.generate_n_select(
                    prompt_name="new_summarize_long",
                    substitutions={
                        "recent": recent_txt,
                    },
                    llm_opts={"temperature": 1.0},
                    n=5,
                    sort_key=len,
                )
            )
        except Exception as e:
            self.logger.error(
                f"[LTM] Unable to summarize long-term chats: {str(e)}."
                + f"({self.last_ts}-{now_ts})"
            )
            summary = ""

        if not summary:
            self.logger.debug(
                "[LTM] No summary generated " + f"({self.last_ts}-{now_ts})"
            )
            p_ts = self.last_ts
            self.forget_stm_final(self.stm_coll, now_ts)
            self.forget_memories_by_summarizing(now_ts)
            self.last_ts = p_ts
            return

        # Retrieve participants
        participants = set()
        for s in stm_summaries:
            # Must convert to tuples
            participants.update(tuple(t) for t in s["participants"])

        # Base memorability based on lack of reduction:
        # A larger ratio between original and summary means it is more memorable.
        # We are also using logistic function to highly favor larger ratios,
        # and highly disfavor smaller ratios.
        avg_summary_length = len(recent_txt) / len(stm_summaries)
        memorability = self.f_logistic(
            avg_summary_length / len(summary),
            0.5,
            1,
            12,
        )

        self.logger.debug(f"avg len {avg_summary_length} / {len(summary)}")
        self.logger.debug(f"memorability = {memorability}")

        embedding = self.llm.get_embeddings(summary)

        try:
            inserted_obj = self.ltm_coll.insert_one(
                document={
                    "today_summ": summary,
                    # "thought_summ": thoughts_summary,
                    # "convo_summ": episodes_summary,
                    "embedding": embedding,
                    "interval_ts": [self.last_ts, now_ts],
                    "created_at_ts": now_ts,
                    "updated_at_ts": now_ts,
                    "participants": list(participants),
                    "forgetting_curve": {
                        "mu": memorability,
                        "a": self.a_decay,
                        "d": self.d_balance,
                        "f_line": self.forget_line,
                        "summ_lengths": self.forget_params["summ_lengths"],
                        "forget_time": self.estimate_forgetting_t(
                            mu=memorability,
                            a=self.a_decay,
                            t=now_ts / self.time_scale,
                            d=self.d_balance,
                            fline=self.forget_line,
                        )
                        * self.time_scale,
                    },
                }
            )

            inserted_id = inserted_obj.inserted_id

            # Insert embedding
            self.insert_embed(str(inserted_id), summary, embedding, now_ts)

            self.logger.debug(
                f"[LTM-{self.stm_coll.full_name.upper()}] {summary}"
            )
        except Exception as e:
            self.logger.error(
                f"[LTM] Unable to memorize-summarize long-term memory: '{str(e)}'. "
            )
            p_ts = self.last_ts
            self.forget_stm_final(self.stm_coll, now_ts)
            self.forget_memories_by_summarizing(now_ts)
            self.last_ts = p_ts
            return

        self.forget_stm_final(self.stm_coll, now_ts)
        self.forget_memories_by_summarizing(now_ts)

    def insert_embed(
        self, id: str, text: str, embedding: List[float], ts: float
    ) -> None:
        if self.embed_db is None:
            return
        self.embed_db.upsert(
            collection="longterm",
            doc_ids=[id],
            doc_contents=[text],
            doc_metadatas=[{"ts": ts}],
            doc_embeddings=None if not embedding else [np.array(embedding)],
        )

    def update_embed(self, id: str, text: str, ts: float):
        if self.embed_db is None:
            return
        if self.embed_db.has_id(collection="longterm", doc_id=id):
            # If ID exists, update doc contents
            self.embed_db.upsert(
                collection="longterm", doc_ids=[id], doc_contents=[text]
            )
        else:
            # If ID is missing -- create a new entry.
            # (meaning, new metadata)
            self.embed_db.upsert(
                collection="longterm",
                doc_ids=[id],
                doc_contents=[text],
                doc_metadatas=[{"ts": ts}],
            )

    def format_summary(self, s: str) -> str:
        while "###" in s:
            s = s.replace("###", "")

        while ":\n" in s:
            s = s.replace(":\n", ": ")

        while "\n\n" in s:
            s = s.replace("\n\n", "\n")

        while "\n" in s:
            s = s.replace("\n", " ")

        while "  " in s:
            s = s.replace("  ", " ")

        return s.strip()

    def forget_memories_by_summarizing(self, tf: float) -> None:
        # Ignore if LTM Level < 2 (2+ means forgetting)
        if self.ltm_level < 2:
            return

        try:
            to_forget = self.ltm_coll.find(
                filter={
                    # Fetch memories to forget
                    "forgetting_curve.forget_time": {"$lte": tf},
                    "$or": [
                        {
                            "forgetting_curve.sentence_base": {
                                "$exists": True,
                                "$gt": 1,
                            }
                        },
                        {
                            "forgetting_curve.summ_lengths": {
                                "$exists": True,
                                "$not": {"$size": 0},
                            }
                        },
                    ],
                }
            )
        except Exception as e:
            self.logger.error(
                "[LTM] Error retrieving long term memories to forget "
                + f"(Details: {str(e)}). Skipping Forgetting cycle."
            )
            return

        # For each candidate...
        excepts = 0
        summarized = 0
        for d in to_forget:
            curve = d["forgetting_curve"]

            if "sentence_base" in curve:
                b = curve["sentence_base"]
                summ_lengths = []
                while b > 1:
                    b = b // 2
                    summ_lengths.append(b)
                curve["summ_lengths"] = summ_lengths
                del curve["sentence_base"]

            if "summ_lengths" in curve and not curve["summ_lengths"]:
                continue

            # Update forgetting curve
            curve["d"] *= 2
            curve["a"] /= 2
            n_sentences = curve["summ_lengths"].pop(0)

            try:
                curve["forget_time"] = (
                    self.estimate_forgetting_t(
                        mu=curve["mu"],
                        a=curve["a"],
                        t=tf / self.time_scale,
                        d=curve["d"],
                        fline=curve["f_line"],
                    )
                    * self.time_scale
                )
            except OverflowError as e:
                self.logger.info(
                    f"[LTM] FP Overflow in forgetting ({str(e)}). "
                    + "Assigning large FP value."
                )
                curve["forget_time"] = float_info.max / 2

            d["forgetting_curve"] = curve
            d["updated_at_ts"] = tf
            # Summarize with new forgetting curve
            try:
                new_today_summ = self.format_summary(
                    self.llm.generate_n_select(
                        prompt_name="new_summarize_limited",
                        substitutions={
                            "sentences": n_sentences,
                            "text": d["today_summ"],
                        },
                        n=5,
                        sort_key=len,
                    )
                )
                if "convo_summ" in d:
                    del d["convo_summ"]

            except Exception as e:
                self.logger.error(
                    f"[LTM] Unable to forget-summarize: {str(e)}."
                )
                new_today_summ = ""

            if not new_today_summ:
                self.logger.error(
                    f"[LTM-{self.ltm_coll.full_name}] No summary for ID"
                    + f"{str(d['_id'])}"
                )
                excepts += 1
                continue

            d["today_summ"] = new_today_summ

            # Update in database
            try:
                self.ltm_coll.replace_one(
                    filter={"_id": d["_id"]}, replacement=d
                )
                self.update_embed(
                    str(d["_id"]), d["today_summ"], d["created_at_ts"]
                )

            except Exception as e:
                self.logger.error(
                    f"[LTM-{self.ltm_coll.full_name}] Error Updating "
                    + f"ID {str(d['_id'])}. "
                    + f"REASON: '{str(e)}'. "
                )
                excepts += 1
                continue
            summarized += 1

        if to_forget:
            self.logger.info(
                f"[LTM] Summarized {summarized}"
                + f"/{summarized + excepts} memories."
            )

        self.last_ts = tf
        self.last_intv_record = datetime.fromtimestamp(
            self.last_ts - self.time_intv, tz=JPN_TZINFO
        ).day

    def forget_stm_final(self, coll: Collection, tf: float):
        if self.stm_level < 2:
            return
        h = f"[LTM-{coll.full_name.upper()}] "
        try:
            to_del_count = coll.count_documents(
                filter={
                    # Fetch memories to forget
                    "forgetting_curve.forget_time": {"$lte": tf},
                    "created_at_ts": {
                        "$lte": self.last_ts
                    },  # Memories > 1 day
                    "$or": [
                        {
                            "forgetting_curve.sentence_base": {
                                "$exists": True,
                                "$eq": 1,
                            }
                        },
                        {
                            "forgetting_curve.summ_lengths": {
                                "$exists": True,
                                "$size": 0,
                            }
                        },
                    ],
                }
            )
            if not to_del_count:
                self.logger.debug(f"{h} No Documents to Delete.")
                return

            if self.embed_db is not None:
                # Delete from
                del_ids = [
                    str(d["_id"])
                    for d in coll.find(
                        filter={
                            # Fetch memories to forget
                            "forgetting_curve.forget_time": {"$lte": tf},
                            "created_at_ts": {
                                "$lte": self.last_ts
                            },  # Memories > 1 day
                            "$or": [
                                {
                                    "forgetting_curve.sentence_base": {
                                        "$exists": True,
                                        "$eq": 1,
                                    }
                                },
                                {
                                    "forgetting_curve.summ_lengths": {
                                        "$exists": True,
                                        "$size": 0,
                                    }
                                },
                            ],
                        },
                        projection={"_id": True},
                    )
                ]
                if del_ids:
                    self.embed_db.deletedocs("narrative", del_ids)
            deleted_count = coll.delete_many(
                filter={
                    # Fetch memories to forget
                    "forgetting_curve.forget_time": {"$lte": tf},
                    "created_at_ts": {
                        "$lte": self.last_ts
                    },  # Memories > 1 day
                    "$or": [
                        {
                            "forgetting_curve.sentence_base": {
                                "$exists": True,
                                "$eq": 1,
                            }
                        },
                        {
                            "forgetting_curve.summ_lengths": {
                                "$exists": True,
                                "$size": 0,
                            }
                        },
                    ],
                }
            ).deleted_count

        except Exception as e:
            self.logger.error(f"{h} Error in Forgetting: {str(e)}")
            return

        self.logger.debug(f"{h} Deleted {deleted_count}")
