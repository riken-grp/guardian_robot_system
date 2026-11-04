#!/usr/bin/env python
# coding: utf-8 -*-

"""Short-Term ASR + TTS (Dialogue) Memory Module"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sys import float_info
from typing import Any, List
from zoneinfo import ZoneInfo

import numpy as np
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from std_msgs.msg import String

from ..util import get_current_ts

# from ..util.scenario_change_tracker import ScenarioChangeTracker
from ..util.episode_tracker import EpisodeState
from ..util.llm.embed_db import OpenAiEmbedDB
from ..util.llm.llm_base import LlmManager

# from ..util.llm.llm_base_old import LLMError
# from ..util.llm_genmem_gpt import ExpoLLMMemoryFunctions
from .sterm_memory_base import PyMongoError, ShortTermMemoryBase

# from pyindy.mongo import get_internal_state_logger
# from pyindy.mongo.internal_state_logger import _InternalStateLogger
# from pymongo import MongoClient

# NARR_INTERVAL = timedelta(minutes=5).total_seconds()
# NARR_TIMESCALE = timedelta(hours=1).total_seconds()  # Timescale minutes -> hours?

JPN_TZINFO = ZoneInfo("Asia/Tokyo")


@dataclass
class ShortTermDiaMemory(ShortTermMemoryBase):
    """Class for Short-Term ASR + TTS (Dialogue) Memory Module"""

    # last_reflect_ts: float = field(init=False)
    last_day_record: int = field(init=False)
    llm: LlmManager = field(init=False)
    embed_db: OpenAiEmbedDB | None = field(default=None, init=False)
    # last_scenario_ts: float = field(default=0, init=False)  # ts for last ep
    ep_state: EpisodeState = field(default=EpisodeState.OFF, init=False)
    narr_timescale: float = field(
        init=False, default=timedelta(days=1).total_seconds()
    )

    def __post_init__(self):
        super().__post_init__()
        # STOP timer -- we'll recreate it later if needed

        self.stop_timer()

        mecbg = MutuallyExclusiveCallbackGroup()

        if "initial_mode" not in self.forget_params:
            self.ep_state = EpisodeState.LOOPING
        else:
            if self.forget_params["initial_mode"] == "LOOPING":
                self.ep_state = EpisodeState.LOOPING
            elif self.forget_params["initial_mode"] == "WAITING":
                self.ep_state = EpisodeState.WAITING
            else:
                self.ep_state = EpisodeState.OFF

        # Create callback that reads ROS Commands
        self.ctl_detector = self.node.create_subscription(
            String,
            "memory/episode_ctl",
            self.episode_ctl_callback,
            10,
            callback_group=mecbg,
        )
        self.setup_index(self.stm_coll, "created_at_ts", 1)
        self.setup_index(self.stm_coll, "memory", "text")

        # self.last_reflect_ts = self.last_ts - NARR_INTERVAL
        self.last_day_record = datetime.fromtimestamp(
            self.last_ts, tz=JPN_TZINFO
        ).day

        # If Memorizing, then load memorization data
        if self.stm_level >= 1:

            self.llm = self.sensor_params["llm"]
            self.embed_db = (
                self.sensor_params["embed_db"]
                if "embed_db" in self.sensor_params
                else None
            )
            # Default Value
            if "sentence_base" not in self.forget_params:
                self.forget_params["sentence_base"] = 6

            if "summ_lengths" not in self.forget_params:
                self.forget_params["summ_lengths"] = [6]

            # Call for memorization if there are any leftover dialogue turns.
            # self.last_ts = 0
            if self.eval_colls is None:
                self.callback()
            else:
                self.callback_wrapper()

        n_timescale = (
            self.forget_params["narrative_timescale"]
            if "narrative_timescale" in self.forget_params
            else {"hours": 1}
        )

        self.narr_timescale = timedelta(**n_timescale).total_seconds()

        self.ros_timer = self.node.create_timer(
            timer_period_sec=self.freq,
            callback_group=mecbg,
            callback=(
                self.callback_forgetting
                if self.eval_colls is None
                else self.callback_forgetting_w
            ),
        )

        self.logger.debug(
            f"[STM-{self.stm_coll.full_name.upper()}] "
            f"Initialized with timescale: {str(n_timescale)}"
        )

    def set_embed_db(self, embeddb: OpenAiEmbedDB | None) -> None:
        self.embed_db = embeddb

    def callback(self) -> None:
        # This is always called by the Timer.
        # Also triggered by the episode_ctl message.
        # If the status is OFF it should return right away.

        if self.stm_level == 0 or self.ep_state == EpisodeState.OFF:
            return

        tf = get_current_ts(self.node)

        # Get all dialogues since the last episode until now.
        dialogue = list(
            self.sm_coll.find(
                {"created_at_ts": {"$gte": self.last_ts, "$lte": tf}},
                sort=[("created_at_ts", 1)],
            )
        )
        convo_summary = ""

        if dialogue:
            self.logger.debug(
                f"[STM-{self.stm_coll.full_name.upper()}] "
                + f"{len(dialogue)} dialogue turns found. "
                + "Generating Summary..."
            )
            try:
                convo_summary = self.narrate_into_memory(dialogue)
            except Exception:
                import traceback

                self.logger.error(
                    f"[STM-{self.stm_coll.full_name.upper()}] Unable to "
                    + "Generate/Save Chat Summmary: "
                    + f"\n{traceback.format_exc()}."
                )
                return

        # to_update = self.get_updated(tf)

        if convo_summary:
            self.memorize(dialogue, [], tf)

            self.logger.info(
                f"[STM-{self.stm_coll.full_name.upper()}] "
                + f"Summarized {len(dialogue)} dialogue turns."
            )
            self.last_ts = tf

    def callback_forgetting(self) -> None:
        if self.stm_level == 0:
            return

        tf = get_current_ts(self.node)

        to_update = self.get_updated(tf)

        self.logger.debug(
            f"[STM-{self.stm_coll.full_name.upper()}] To Update: "
            + f"{len(to_update)}."
        )

        self.memorize([], to_update, tf)

    def callback_forgetting_w(self) -> None:
        self.wrap_call(self.callback_forgetting)

    def memorize(
        self,
        sensormem_contents: list,
        to_update: list,
        tstamp: float,
    ) -> None:
        updated = deleted = 0
        if self.stm_level > 0:
            updated = self.memory_update(self.stm_coll, to_update)
            if self.embed_db is not None:
                try:
                    for d in to_update:
                        self.update_embed(
                            str(d["_id"]), d["memory"], d["created_at_ts"]
                        )
                except Exception as e:
                    self.logger.error(
                        f"[STM-{self.stm_coll.full_name.upper()}] "
                        + f"Error updating. REASON: {str(e)}"
                    )

        # SM Forgetting
        if self.sm_level >= 2:
            deleted += self.memory_forget_list(
                self.sm_coll, sensormem_contents
            )

        self.logger.debug(
            f"[STM-{self.stm_coll.full_name.upper()}] "
            + f"UPD {updated} | DEL {deleted}"
        )

    def check_timespan(self, sensor_contents: list) -> float:
        return abs(
            sensor_contents[-1]["created_at_ts"]
            - sensor_contents[0]["created_at_ts"]
        )

    def split_contents(self, sensor_contents: list, min_span: float) -> list:
        timespan = self.check_timespan(sensor_contents)

        if timespan < min_span:
            return [sensor_contents]

        ret_list = []
        temp = []

        while sensor_contents:
            doc = sensor_contents.pop()
            if not temp:
                temp = [doc]
                continue
            temp.append(doc)
            timespan = self.check_timespan(temp)
            if timespan > min_span:
                temp.pop()
                ret_list.append(temp[::-1])
                temp = [doc]
        if temp:
            ret_list.append(temp[::-1])

        return ret_list

    def narrate_into_memory(self, sensor_contents: list) -> Any:
        """Add a summary of the conversation into memory.
        Includes some reflective thoughts and memorability.
        """
        if not sensor_contents:
            return ""

        # tokens = self.llm.count_tokens(convo)
        # self.logger.debug(
        #     f"[STM-{self.stm_coll.full_name.upper()}] Token Count: {tokens}"
        # )

        # If Dialogue Data is longer than 10 mins, split
        sensor_splits = self.split_contents(sensor_contents, 600)

        summaries = []
        for ssplit in sensor_splits:
            convo = self.llm.format_chat_history_append(ssplit)

            # Fields: summary, memorability, thoughts?
            convo_summ = self.format_summary(
                self.llm.generate(
                    prompt_name="new_summarize_conversation",
                    substitutions={
                        "conversation": convo,
                    },
                )
            )
            if not convo_summ:
                continue

            summaries.append(convo_summ)

            participants = set()

            for turn in ssplit:
                if turn["origin"] == "asr":
                    participants.add(
                        (
                            turn["metadata"]["instance_id"],
                            turn["metadata"]["human_id"],
                        )
                    )

            # NOTE For now, let's base memorability on reduction:
            # A larger ratio between original and summary means it is more memorable.
            mu = self.f_logistic(
                sum(len(d["utterance"]) for d in ssplit) / len(convo_summ),
                0.3,
                1,
                13,
            )

            embeddings = self.llm.get_embeddings(convo_summ)

            forgetfulness = {
                "mu": mu,
                "a": self.a_decay,
                "d": self.d_balance,
                "f_line": self.forget_line,
                "summ_lengths": self.forget_params["summ_lengths"],
            }
            base_time = datetime.fromtimestamp(
                ssplit[-1]["created_at_ts"], tz=JPN_TZINFO
            ) + timedelta(days=1)
            past_midnight = datetime(
                base_time.year,
                base_time.month,
                base_time.day,
                0,
                1,
                tzinfo=JPN_TZINFO,
            )
            # Insert Associative Data Object
            convo_inserted = self.stm_coll.insert_one(
                {
                    "type": "chat",
                    "memory": convo_summ,
                    # "source": sensor_contents,
                    # "embedding": embedding,
                    "convo_start_ts": ssplit[0]["created_at_ts"],
                    "created_at_ts": ssplit[-1]["created_at_ts"],
                    "updated_at_ts": ssplit[-1]["created_at_ts"],
                    "participants": list(participants),
                    "forgetting_curve": {
                        "mu": mu,
                        "a": self.a_decay,
                        "d": self.d_balance,
                        "f_line": self.forget_line,
                        "summ_lengths": self.forget_params["summ_lengths"],
                        "forget_time": self.estimate_forgetting_t(
                            mu=mu,
                            a=forgetfulness["a"],
                            #  NOTE changed for experiment
                            # t=ssplit[-1]["created_at_ts"]
                            t=past_midnight.timestamp() / self.narr_timescale,
                            d=forgetfulness["d"],
                            fline=forgetfulness["f_line"],
                        )
                        * self.narr_timescale,
                    },
                }
            )

            convo_inserted_id = convo_inserted.inserted_id

            # Insert embedding
            self.insert_embed(
                str(convo_inserted_id),
                convo_summ,
                embeddings,
                ssplit[-1]["created_at_ts"],
            )

        final_summ = "\n".join(summaries)

        self.logger.debug(
            f"[STM-{self.stm_coll.full_name.upper()}] Summaries: {final_summ}"
        )

        return convo_summ

    def insert_embed(
        self, id: str, text: str, embedding: List[float], ts: float
    ) -> None:
        if self.embed_db is None:
            return
        self.embed_db.upsert(
            collection="narrative",
            doc_ids=[id],
            doc_contents=[text],
            doc_metadatas=[{"type": "chat", "ts": ts}],
            doc_embeddings=None if not embedding else [np.array(embedding)],
        )

    def update_embed(self, id: str, text: str, ts: float):
        if self.embed_db is None:
            return
        if self.embed_db.has_id(collection="narrative", doc_id=id):
            # If ID exists, update doc contents
            self.embed_db.upsert(
                collection="narrative", doc_ids=[id], doc_contents=[text]
            )
        else:
            # If ID is missing -- create a new entry.
            # (meaning, new metadata)
            self.embed_db.upsert(
                collection="narrative",
                doc_ids=[id],
                doc_contents=[text],
                doc_metadatas=[{"type": "chat", "ts": ts}],
            )

    def get_updated(self, tf: float) -> list:
        try:
            to_forget = self.stm_coll.find(
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
                # {
                #     "forgetting_curve.forget_time": {"$lte": tf},
                #     # "forgetting_curve.sentence_base": {"$gt": 1},
                # }
            )
        except PyMongoError as e:
            self.logger.error(
                "[STM-NARR] Error retrieving memories to forget "
                + f"(Details: {str(e)}). Skipping Forgetting cycle."
            )
            return []

        to_update = []
        # For each candidate...
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

            # Update forgetting_curve
            curve["d"] *= 2
            curve["a"] /= 2
            n_sentences = curve["summ_lengths"].pop(0)

            try:
                curve["forget_time"] = (
                    self.estimate_forgetting_t(
                        mu=curve["mu"],
                        a=curve["a"],
                        t=tf / self.narr_timescale,
                        d=curve["d"],
                        fline=curve["f_line"],
                    )
                    * self.narr_timescale
                )
            except OverflowError as e:
                self.logger.error(
                    f"[STM-NARR] FP Overflow in forgetting ({str(e)}). "
                    + "Assigning large FP value."
                )
                curve["forget_time"] = float_info.max / 2

            try:
                summ_memory = self.format_summary(
                    self.llm.generate_n_select(
                        prompt_name="new_summarize_limited",
                        substitutions={
                            "sentences": n_sentences,
                            "text": d["memory"],
                        },
                        n=5,
                        sort_key=len,
                    )
                )

            except Exception as e:
                self.logger.error(
                    f"[STM-NARR] Unable to Forget/Summarize: {e}."
                )
                summ_memory = ""

            if summ_memory:
                d["memory"] = summ_memory
                d["updated_at_ts"] = tf
                to_update.append(d)

        return to_update

    def format_summary(self, s: str) -> str:

        while "###" in s:
            s = s.replace("###", "")

        while ":\n" in s:
            s = s.replace(":\n", ": ")

        while "\n\n" in s:
            s = s.replace("\n\n", "\n")

        while "  " in s:
            s = s.replace("  ", " ")

        return s.strip()

    def episode_ctl_callback(self, msg: String):
        if msg.data == "memory start episode":
            # Check Status
            if (
                self.ep_state != EpisodeState.WAITING
                and self.ep_state != EpisodeState.OFF
                and self.ep_state != EpisodeState.LOOPING
            ):
                # Invalid Start Status
                self.logger.error(
                    f"[STM-{self.stm_coll.full_name.upper()}] "
                    + "Cannot Start Memory Episode: Incompatible Initial State "
                    + f"({self.ep_state})"
                )
                return
            # Change Status
            self.logger.debug(
                f"[STM-{self.stm_coll.full_name.upper()}] "
                + "Starting Memory Episode via episode_ctl"
            )

            # (opt) Stop Loop
            # If status was LOOPING, run the episodic memory one time.
            if self.ep_state == EpisodeState.LOOPING:
                self.stop_timer()
                if self.eval_colls is None:
                    self.callback()
                else:
                    self.callback_wrapper()
            else:
                self.last_ts = get_current_ts(self.node)

            # Change Status
            self.ep_state = EpisodeState.IN_EPISODE
        elif msg.data == "memory end episode":
            # Check Status
            if self.ep_state != EpisodeState.IN_EPISODE:
                # Invalid Start Status
                self.logger.error(
                    f"[STM-{self.stm_coll.full_name.upper()}] "
                    + "Cannot End Memory Episode: Incompatible Initial State "
                    + f"({self.ep_state})"
                )
                return
            # Run Memorization
            if self.eval_colls is None:
                self.callback()
            else:
                self.callback_wrapper()
            # Change Status
            self.ep_state = EpisodeState.WAITING
        elif msg.data == "memory loop episode":
            # Check Status
            if self.ep_state == EpisodeState.LOOPING:
                return
            if self.ep_state == EpisodeState.IN_EPISODE:
                # We are in the middle of an episode.
                # Finish the episode.
                if self.eval_colls is None:
                    self.callback()
                else:
                    self.callback_wrapper()
            # Start Loop
            self.start_timer()
            # Change Status
            self.ep_state = EpisodeState.LOOPING
        elif msg.data == "stop" or msg.data == "stop memory episodic":
            # Check Status
            if self.ep_state == EpisodeState.OFF:
                return
            # (opt) Stop Loop
            if self.ep_state == EpisodeState.LOOPING:
                self.stop_timer()

            # If prior state requires memorization...
            if (
                self.ep_state == EpisodeState.IN_EPISODE
                or self.ep_state == EpisodeState.LOOPING
            ):
                # Memorize.
                if self.eval_colls is None:
                    self.callback()
                else:
                    self.callback_wrapper()

            # Change Status
            self.ep_state = EpisodeState.OFF
