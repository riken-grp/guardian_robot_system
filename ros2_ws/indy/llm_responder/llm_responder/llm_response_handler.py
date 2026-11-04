#!/usr/bin/env python
# coding: utf-8 -*-

import random
import traceback
from typing import Callable, List, cast

from pyindy.llm.embed_db import OpenAiEmbedDB
from pyindy.mongo import (
    CyberDBWriter,
    EyeManager,
    GestureManager,
    ROSCommandManager,
    UtteranceManager,
)
from pyindy.mongo.database_manager import PhysicalDBWriter
from pymongo import MongoClient
from rclpy.node import Node
from std_msgs.msg import String

from .asr_input_tracker import AsrInputTracker
from .util import (
    cleanup_action_manager,
    cleanup_database_manager,
    get_current_ts,
    ts_to_str_jst,
)
from .util.llm.llm_api_wrapper import LlmRequestManager

# from .util.llm_output_helper import choose_ask
from .util.llm_output_helper import DEFAULT_EYES_DICT  # create_diag_turn,
from .util.llm_output_helper import (
    LlmChatHistory,
    choose_filler,
    create_eye,
    create_gesture,
    parse_llm_response_hashtags,
    sanitize_llm_response,
)
from .util.memory_query import IndyMemoryRecall


class LlmResponseHandler:
    def __init__(
        self,
        node: Node,
        robot_name: str,
        client: MongoClient,
        llm: LlmRequestManager,
        emb_db: OpenAiEmbedDB,
        default_stop_phrase: dict,
    ):
        if client.address is None:
            raise ConnectionError("No connection to Database.")

        self.node = node
        self.llm = llm
        self.prompt = llm.system_prompt

        self.obs = AsrInputTracker(client["sensor_memory"])
        host, port = client.address

        # Utteranace manager speaks but is not registered
        # (ActionManager does register it)
        self.ut_man = cast(
            UtteranceManager,
            cleanup_action_manager(
                UtteranceManager(host, port, robot_name), client
            ),
        )
        self.gt_man = cast(
            GestureManager,
            cleanup_action_manager(
                GestureManager(host, port, robot_name), client
            ),
        )
        self.eye_man = cast(
            EyeManager,
            cleanup_action_manager(EyeManager(host, port, robot_name), client),
        )

        # PhysicalDB is used to continue the scenario
        self.phy_dbw = cast(
            PhysicalDBWriter,
            cleanup_database_manager(
                PhysicalDBWriter(host, port, "tBlackBoard", "llm-kd"), client
            ),
        )

        # For retrieval of data
        self.db_client = client
        self.emb_db = emb_db
        self.mem_rec = IndyMemoryRecall(client, emb_db)

        # Clear focus in EmbedDB, then transfer focus from MongoDB
        # focus_coll = self.emb_db.client.get_or_create_collection(
        #     "robot_persona", embedding_function=self.emb_db.embedFn
        # )
        # focus_coll.delete(where={"type": "focus"})

        self.emb_db.clear_collection("robot_persona")

        mdb_focus = self.db_client.memory_settings.robot_persona.find(
            {"type": "focus"}
        )

        for foc in mdb_focus:
            self.emb_db.upsert(
                "robot_persona",
                str(foc["_id"]),
                foc["content"],
                {"type": "focus", "key": foc["key"]},
            )
        self.cdb_writer = CyberDBWriter(host, port, "tBlackBoard", "event")
        self.ros_cmd = ROSCommandManager(host, port, robot_name)
        self.act_ctl = self.node.create_publisher(
            String, "robot/action_ctl", 10
        )
        self.robot_name = robot_name

        self.default_stop_phrase = default_stop_phrase

    @property
    def nlogger(self):
        return self.node.get_logger()

    def get_reply(
        self,
        prompt_id: str,
        stop_time: float,
        recall_fn: Callable,
        task_key: str,
        scenario_ts: float = 0,
        retry: int = 1,
        temperature: float = 1.0,
        history=30,
        keyword_validation={},
        stop_phrase={},
        hist_to_prompt=False,
    ) -> bool:
        is_timeout = False
        t = get_current_ts(self.node)
        reply_start = t
        self.nlogger.debug("Waiting for ASR...")
        # send command to do LISTENING eyes for stop_time - 10 secs
        self.eye_man.insert(create_eye("listen.jpg", (stop_time - 10) - t))
        while t < stop_time - 10:
            if self.obs.has_new_asr(t_f=reply_start):
                remaining = (stop_time - 10) - t
                # command to stop eyes
                self.ros_stop_eyes()
                # send command to do THINKING eyes for remaining time in secs
                self.eye_man.insert(create_eye("thinking.jpg", remaining))
                self.nlogger.debug("ASR received.")
                hist = self.obs.get_history(N=history, t0=scenario_ts)
                latest = hist[-1]["content"] if hist else ""
                self.nlogger.debug(
                    f'ASR: "{latest}"' + f"(Event: {self.obs.asr_id})"
                )

                if self.is_scenario_stop(latest, stop_phrase):
                    # Hijack the regular flow of the interaction.
                    # command to stop eyes
                    self.ros_stop_eyes()
                    # Check if we need to call a new scenario.
                    if (
                        "sp_next_scenario" in stop_phrase
                        and stop_phrase["sp_next_scenario"]
                    ):
                        self.cdb_writer.insert(
                            {"_id": stop_phrase["sp_next_scenario"]}
                        )
                    elif (
                        "sp_next_scenario" in self.default_stop_phrase
                        and self.default_stop_phrase["sp_next_scenario"]
                    ):
                        self.cdb_writer.insert(
                            {
                                "_id": self.default_stop_phrase[
                                    "sp_next_scenario"
                                ]
                            }
                        )
                    return False

                # Here is where *the magic* happens.
                focus_pts = self.retrieve_focus(latest, task_key, n=1)
                memories = self.retrieve_memories(latest, t, recall_fn)

                # TODO adjust memory retrieval

                if not memories:
                    memories = focus_pts

                if not keyword_validation:
                    res = self.llm.generate(
                        prompt_id,
                        {"memories": memories},
                        hist,
                        llm_opts={
                            "temperature": temperature,
                            "stop": ["\n"],
                            "timeout": remaining,
                        },
                        date_to_add=t,
                        hist_to_prompt=hist_to_prompt,
                    )
                else:
                    keywords = keyword_validation["keywords"]
                    n_responses = (
                        keyword_validation["n_responses"]
                        if "n_responses" in keyword_validation
                        else 3
                    )
                    kw_retries = (
                        keyword_validation["retries"]
                        if "retries" in keyword_validation
                        else 1
                    )

                    res = self.llm.generate_n_validate(
                        prompt_id,
                        {"memories": memories},
                        hist,
                        keywords,
                        n_responses,
                        llm_opts={
                            "temperature": temperature,
                            "stop": ["\n"],
                            "retries": kw_retries,
                            "timeout": remaining,
                        },
                        date_to_add=t,
                    )
                # self.nlogger.debug(f"llm resp: {res}")

                # Extract hashtags
                cmd, res, tags = parse_llm_response_hashtags(res)
                res = sanitize_llm_response(res)

                self.nlogger.debug(f"Sanitized Response: {res}")

                if res != "False":
                    if cmd:
                        # Process commands
                        self.nlogger.debug(
                            f"Received Command: [{cmd}]. Ignoring ASR."
                        )
                        must_continue = self.process_cmd(cmd, tags)
                        if must_continue:
                            t = get_current_ts(self.node)
                            continue
                        return is_timeout

                    # command to stop eyes
                    self.ros_stop_eyes()
                    content = {
                        "latest": hist[-1] if hist else "",
                        "words": res,
                        "text": res,
                        "reply": prompt_id,
                    }
                    self.phy_dbw.insert(content, priority=30)
                    self.insert_eye(tags)
                    self.nlogger.debug("Inserted into Physical DB.")
                    return is_timeout
                else:
                    if retry <= 0:
                        t = stop_time
                        is_timeout = True
                        continue
                retry -= 1

            t = get_current_ts(self.node)
            is_timeout = not (t < stop_time - 10)

        self.nlogger.debug("Timeout.")

        # command to stop eyes
        self.ros_stop_eyes()
        return is_timeout

    def get_prompt(
        self,
        prompt_id: str,
        scenario_ts: float,
        temperature: float = 1.0,
        history: int = 0,
        history_in_prompt: bool = False,
        keyword_validation: dict = {},
        hist_to_prompt=False,
    ) -> bool:
        self.nlogger.debug(
            "Generating from Prompt"
            + ("(history in prompt)" if history_in_prompt else "")
        )

        # self.gt_man.insert(create_gesture("look_down_s", 0.5))
        # self.ut_man.insert({"text": choose_filler()})

        hist = self.obs.get_history(N=history, t0=scenario_ts)
        latest = hist[-1]["content"] if hist else ""
        self.nlogger.debug(f'Latest: "{latest}"')

        if keyword_validation:
            keywords = keyword_validation["keywords"]
            n_responses = (
                keyword_validation["n_responses"]
                if "n_responses" in keyword_validation
                else 3
            )
            kw_retries = (
                keyword_validation["retries"]
                if "retries" in keyword_validation
                else 1
            )
            if history and history_in_prompt:
                res = self.llm.generate_n_validate(
                    prompt_id,
                    substitutions={"history": self.history_to_text(hist)},
                    keywords=keywords,
                    n=n_responses,
                    llm_opts={
                        "temperature": temperature,
                        "stop": ["\n"],
                        "retries": kw_retries,
                    },
                    hist_to_prompt=hist_to_prompt,
                )
            else:
                res = self.llm.generate_n_validate(
                    prompt_id,
                    substitutions={},
                    chat_history=hist,
                    keywords=keywords,
                    n=n_responses,
                    llm_opts={
                        "temperature": temperature,
                        "stop": ["\n"],
                        "retries": kw_retries,
                    },
                    hist_to_prompt=hist_to_prompt,
                )
        else:
            if history and history_in_prompt:
                res = self.llm.generate(
                    prompt_id,
                    substitutions={"history": self.history_to_text(hist)},
                    llm_opts={"temperature": temperature, "stop": ["\n"]},
                    hist_to_prompt=hist_to_prompt,
                )
            else:
                res = self.llm.generate(
                    prompt_id,
                    substitutions={},
                    chat_history=hist,
                    llm_opts={"temperature": temperature, "stop": ["\n"]},
                    hist_to_prompt=hist_to_prompt,
                )

        _, res, tags = parse_llm_response_hashtags(res)

        res = self.insert_observation("prompt", prompt_id, res, tags, [])

        return not res

    def get_default(
        self,
        mode: str,
        scenario_ts: float,
        temperature: float = 1.0,
        history: int = 0,
        hist_to_prompt=False,
    ) -> bool:
        self.nlogger.debug(f"Unknown mode ({mode}). Using default prompt.")

        # self.gt_man.insert(create_gesture("look_down_s", 0.5))
        # self.ut_man.insert({"text": choose_filler()})

        hist = self.obs.get_history(N=history, t0=scenario_ts)
        latest = hist[-1]["content"] if hist else ""
        self.nlogger.debug(f'Latest: "{latest}"')

        res = self.llm.generate(
            "default",
            substitutions={},
            chat_history=hist,
            llm_opts={"temperature": temperature, "stop": ["\n"]},
            hist_to_prompt=hist_to_prompt,
        )

        _, res, tags = parse_llm_response_hashtags(res)

        res = self.insert_observation(mode, "default", res, tags, [])

        return not res

    def ros_stop_eyes(self):
        msg = String()
        msg.data = "stop eye"
        self.act_ctl.publish(msg)

    def insert_observation(
        self,
        mode: str,
        prompt_id: str,
        res: str,
        tags: List[str],
        hist: list = [],
    ) -> str:
        res = sanitize_llm_response(res)
        self.nlogger.debug(f"Sanitized Response: {res}")
        content = {
            "latest": hist[-1] if hist else "",
            "words": res,
            "text": res,
            mode: prompt_id,
        }
        self.phy_dbw.insert(content, priority=30)  # type: ignore
        self.insert_eye(tags)
        self.nlogger.debug("Inserted into Physical DB.")

        return res

    def process_cmd(self, cmd: str, tags: List[str]) -> bool:
        # Commands
        if "待つ" in cmd:
            # Wait... how long?
            wait_t = 5 + random.triangular(-0.5, 0.5)
            self.node.create_rate(1.0 / wait_t).sleep()
            # Then, re-do the event?
            return True

        elif "それから" in cmd:
            self.ut_man.insert({"text": choose_filler()})
            self.gt_man.insert(create_gesture("nodding"))
            self.insert_eye(tags)
            return True

        elif "聞き返し" in cmd:
            # Get the last utterance.
            last_utt = self.ut_man.col.find_one(
                filter={"command": "speak", "status": "done"},
                sort=[("inserted", -1)],
            )
            # Repeat the last utterance.
            if last_utt is not None:
                self.ut_man.insert(last_utt["option"])
                self.insert_eye(tags)
            return True
        elif "無視" in cmd:
            # This will cause the utterance to be recorded, but cancelled.
            self.ut_man.insert(
                {"text": choose_filler()}, {"type": "ignored", "runAfter": ""}
            )
            return True

        return False

    def insert_eye(self, tags: List[str]):
        if tags:
            if len(tags) > 1:
                self.nlogger.warn(
                    f"Found Hashtags: {tags}."
                    + "Only one will be used in Gestures."
                )
            for i, tag in enumerate(tags):
                if tag in DEFAULT_EYES_DICT:
                    break
            gest_tag = DEFAULT_EYES_DICT[i]
            self.eye_man.insert(create_eye(gest_tag, 5.0))

    def retrieve_focus(
        self, last_utterance: str, task_key: str, n: int = 3
    ) -> str:
        # Retrieve Relevant Focus
        # Reminder: [id, doc, dist, metadata, embedding]
        focus_embs = self.emb_db.requestdoclist_text(
            "robot_persona",
            [last_utterance],
            query={"$and": [{"type": "focus"}, {"key": task_key}]},
            n=n,
        )
        focus_txt = "" + "、".join(f"「{foc[1]}」" for foc in focus_embs)

        return (
            focus_txt
            if focus_txt and task_key
            else "「インディーは、この件について興味があるかもしれません。」"
        )

    def retrieve_memories(
        self, latest: str, t: float, recall_fn: Callable
    ) -> str:
        try:
            memories = recall_fn(text=[latest], ts=t)
        except Exception as e:
            self.nlogger.error(f"DB Retrieval Error: {e}")
            self.nlogger.debug(traceback.format_exc())
            return ""

        if not latest or not memories:
            return ""

        # NOTE changed for experiment
        return "\n".join(
            f'- {ts_to_str_jst(m[0], "%Y年%m月%d日%H時%M分")}: "{m[1]}"'
            for m in memories
        )

    def history_to_text(self, hist: LlmChatHistory) -> str:
        assistant = "ロボット"
        user = "ユーザー"
        return "\n".join(
            (f"{user}: " if "user" in ct["role"] else assistant)
            + f"「{ct['content']}」"
            for ct in hist
        )

    def is_scenario_stop(self, utt: str, custom_stop: dict) -> bool:
        keywords = (
            custom_stop["keywords"]
            if "keywords" in custom_stop
            else self.default_stop_phrase["keywords"]
        )
        stop_len = (
            custom_stop["stop_phrase_length"]
            if "stop_phrase_length" in custom_stop
            else self.default_stop_phrase["stop_phrase_length"]
        )

        return len(utt) < stop_len and any(kw in utt for kw in keywords)
