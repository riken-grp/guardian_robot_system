#!/usr/bin/env python
# coding: utf-8 -*-

import json
from pathlib import Path
from typing import List, cast

from common_msgs.msg import StringStamped  # type: ignore

from pyindy.llm.embed_db import OpenAiEmbedDB
from pyindy.mongo import DialogueHistoryManager, UtteranceManager
from pyindy.mongo.database_manager import PhysicalDBWriter
from .util import ParamManager
from pymongo import MongoClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.logging import LoggingSeverity as LS
from rclpy.node import Node

from .util import (
    ParamDesc,
    get_current_ts,
    get_default_params,
    get_ros_param,
    cleanup_action_manager,
    cleanup_database_manager,
)
from .util.llm.llm_api_wrapper import LlmRequestManager
from .util.llm_output_helper import create_diag_turn
from .util.episode_tracker import EpisodeState, EpisodeStateTracker


class LlmMicWatchdogNode(Node):
    def __init__(
        self,
        # scenario_tracker: ScenarioStartTracker,
        state_tracker: EpisodeStateTracker,
        node_name: str = "llm_adintool_watchdog",
    ):
        super().__init__(node_name=node_name)  # type: ignore

        self.get_logger().info("Initializing LLM Response Observer.")
        self.robot_name = self.get_namespace()
        ns = self.robot_name + "."
        while self.robot_name[0] == "/":
            self.robot_name = self.robot_name[1:]

        self.get_logger().info(f"Node Namespace: {ns}")

        # Parameter declaration
        self.declare_parameters(
            namespace=self.get_namespace(),
            parameters=[
                ("mongo_uri", "localhost", ParamDesc.String.value),
                ("mongo_port", 6000, ParamDesc.Int.value),
            ],
        )

        # DB Params
        mongo_uri = get_ros_param(self, "mongo_uri", ParamDesc.String)
        mongo_port = get_ros_param(self, "mongo_port", ParamDesc.Int)

        self.dhm = DialogueHistoryManager(
            mongo_uri, mongo_port, self.robot_name
        )

        self.get_logger().info(f"Connecting to {mongo_uri}:{mongo_port}...")
        db_server = MongoClient(mongo_uri, mongo_port)
        self.get_logger().info(f"Connected to {mongo_uri}:{mongo_port}.")

        pm = ParamManager(db_server)
        params = pm.get_param("llm_responder")

        if not params:
            self.get_logger().warning(
                "Parameters for Memory not in Params DB. "
                + "Using Default Values (This may cause unexpected behavior/errors)."
            )

        # Load all memory settings from DB
        mem_params = get_default_params(params)
        debug_msgs = mem_params["debug_msgs"]
        self.get_logger().set_level(LS.DEBUG if debug_msgs else LS.INFO)

        # Load all memory settings from DB
        self.mem_params = get_default_params(params)

        # LLM params
        llm_data = self.mem_params["llm"]
        llm_data["robot_name"] = self.mem_params["robot_name"]
        llm_data["robot_alias"] = self.mem_params["robot_alias"]

        main_prompt = db_server.memory_settings.llm_prompts.find_one(
            {"name": "wake up keyword"}
        )

        llm_data["system_prompt"] = (
            main_prompt["ja"]
            if main_prompt
            else "来客の発話が与えられます。来客の発話の意図に応じて、"
            + "以下のいずれかの出力を書いてください。"
            + "\n- 来客があなた話したがっている場合は、「OKITE」と書いてください。\n"
            + "- そうでなければ、「NEMASU」と書いてください。"
            + "\n出力は「OKITE」か「NEMASU」のどちらかだけで、他には何も書きません。"
        )  # Default Value

        if "embed_api" in self.mem_params and self.mem_params["embed_api"]:

            emb_settings = self.mem_params["embed_api"]

            if (
                "db_url" in self.mem_params["embed_api"]
                and "db_port" in self.mem_params["embed_api"]
            ):
                self.mem_params["embed_db"] = OpenAiEmbedDB.createFromHttps(
                    self.mem_params["embed_api"]["db_url"],
                    self.mem_params["embed_api"]["db_port"],
                    emb_settings["url"],
                    emb_settings["api_key"],
                    emb_settings["model"],
                    emb_settings["dimensions"],
                )
            else:
                embeddb_loc = str(
                    Path(self.mem_params["embed_api"]["embed_db"])
                    .expanduser()
                    .absolute()
                    .resolve()
                )

                self.mem_params["embed_db"] = OpenAiEmbedDB.createFromPath(
                    embeddb_loc,
                    emb_settings["url"],
                    emb_settings["api_key"],
                    emb_settings["model"],
                    emb_settings["dimensions"],
                )
        else:
            emb_settings = None

        self.mem_params["llm"] = LlmRequestManager(
            self, db_server.memory_settings, llm_data, emb_settings
        )
        self.trigger_asr = cast(
            PhysicalDBWriter,
            cleanup_database_manager(
                PhysicalDBWriter(mongo_uri, mongo_port, "tBlackBoard", "asr"),
                db_server,
            ),
        )

        self.subtitle_asr = cast(
            UtteranceManager,
            cleanup_action_manager(
                UtteranceManager(
                    mongo_uri, mongo_port, "asr", "subtitle_indy"
                ),
                db_server,
            ),
        )
        self.subtitle_rob = cast(
            UtteranceManager,
            cleanup_action_manager(
                UtteranceManager(
                    mongo_uri, mongo_port, "indy1e", "subtitle_indy"
                ),
                db_server,
            ),
        )

        self.phy_dbw = cast(
            PhysicalDBWriter,
            cleanup_database_manager(
                PhysicalDBWriter(
                    mongo_uri, mongo_port, "tBlackBoard", "keyword-wake"
                ),
                db_server,
            ),
        )

        self.sub_asr_kaiwa = self.create_subscription(
            StringStamped,
            "asr/meta_data",
            self.asr_callback,
            10,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

        self.sub_asr_keyword = self.create_subscription(
            StringStamped,
            "asr/meta_data",
            self.asr_kw_callback,
            10,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

        # self.switch_checker = scenario_tracker
        self.state_tracker = state_tracker

        self.interruptables: List[str] = (
            params["kw_interruptable_scenarios"] if params else ["Standby"]
        )
        self.adintool_ports: List[int] = (
            params["adintool_ports"] if params else [5580]
        )

        self.get_logger().debug(
            f"Interruptable Scenarios: {str(self.interruptables)}"
        )
        self.get_logger().debug(f"Adintool Ports: {str(self.adintool_ports)}")

        self.get_logger().debug(f"State: {str(self.state_tracker.ep_state)}")

    @property
    def llm(self) -> LlmRequestManager:
        return self.mem_params["llm"]

    def asr_callback(self, msg):
        d = json.loads(msg.data)
        if d["sep_port"] in self.adintool_ports:
            self.get_logger().info(
                f"Mic ASR [{d['sep_port']}]: `{d['words']}`"
            )
            self.dhm.insert("asr", d["words"], d["sep_port"])

            item = self.subtitle_asr.insert({"text": d["words"]})
            self.subtitle_asr.set_status(item.inserted_id, "done")
            d["confidence"] = float(d["scores"])
            d["text"] = "".join(d["words"])
            # q['turn_end'] = vap_status
            d["turn_end"] = True
            self.trigger_asr.insert(d, priority=100)

    def asr_kw_callback(self, msg):
        start_ts = get_current_ts(self)
        self.get_logger().debug(f"State: {str(self.state_tracker.ep_state)}")

        if (
            self.state_tracker.ep_state == EpisodeState.LOOPING
            or self.state_tracker.ep_state == EpisodeState.IN_EPISODE
        ):
            return

        # if self.switch_checker.status_str != "idling" and not any(
        #     sce == self.switch_checker.scenario for sce in self.interruptables
        # ):
        #     return

        d = json.loads(msg.data)
        said = d["words"]
        hist = [create_diag_turn("user", said)]
        llm_opts = {"temperature": 0.0, "stop": ["\n"]}

        for _ in range(5):
            # self.llm.llm.get_n_responses("", hist, n=5, **llm_opts)
            res = self.llm.sanitize_response(
                self.llm.llm.get_response("", hist, **llm_opts)  # type: ignore
            )
            if "OKITE" in res or "NEMASU" in res:
                break

        conn = "├" if "OKITE" in res else "└"

        self.get_logger().debug(f"┌ Utterance:「{said}」")
        self.get_logger().debug(f"{conn} Intent:「{res}」")

        triggered = "OKITE" in res

        if triggered:
            content = {"activate": True}
            self.phy_dbw.insert(content, priority=100)
            self.get_logger().debug("└─→ Inserted into Physical DB.")
        end_ts = get_current_ts(self)
        self.get_logger().debug(
            f"> Processing time: {end_ts - start_ts} sec "
            + f"({'ACCEPT' if triggered else 'REJECT'}　←　「{said}」)"
        )
