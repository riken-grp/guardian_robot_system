#!/usr/bin/env python
# coding: utf-8 -*-

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import cast

import rclpy
from pyindy.llm.embed_db import OpenAiEmbedDB
from pyindy.mongo import ActionManager, CyberDBWriter
from pymongo import MongoClient, ReturnDocument
from rclpy import qos
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.logging import LoggingSeverity as LS
from rclpy.node import Node
from std_msgs.msg import String

from .llm_mic_watchdog_node import LlmMicWatchdogNode
from .llm_response_handler import LlmResponseHandler

# from .scenario_start_tracker import ScenarioStartTracker
from .util import (
    ParamDesc,
    ParamManager,
    cleanup_action_manager,
    cleanup_database_manager,
    get_current_ts,
    get_default_params,
    get_ros_param,
    jst_ts,
)
from .util.episode_tracker import EpisodeState, EpisodeStateTracker
from .util.llm.llm_api_wrapper import LlmRequestManager
from .util.memory_query import IndyMemoryRecall


class LlmResponderNode(Node):
    def __init__(self, node_name: str = "llm_responder_node") -> None:
        super().__init__(node_name=node_name)  # type: ignore

        self.logger.info("Initializing LLM Response Observer.")
        self.robot_name = self.get_namespace()
        ns = self.robot_name + "."
        while self.robot_name[0] == "/":
            self.robot_name = self.robot_name[1:]

        self.logger.info(f"Node Namespace: {ns}")

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

        self.logger.info(f"Connecting to {mongo_uri}:{mongo_port}...")

        db_server = MongoClient(mongo_uri, mongo_port)
        self.logger.info(f"Connected to {mongo_uri}:{mongo_port}.")

        pm = ParamManager(db_server)
        params = pm.get_param("llm_responder")

        if not params:
            self.logger.warning(
                "Parameters for LLM Responder not in Params DB. "
                + "Using Default Values (This may cause unexpected behavior/errors)."
            )
        # Load all memory settings from DB
        self.mem_params = get_default_params(params)
        debug_msgs = self.mem_params["debug_msgs"]
        self.logger.set_level(LS.DEBUG if debug_msgs else LS.INFO)

        # Load all memory settings from DB
        self.msg_pub = self.create_publisher(
            msg_type=String,
            topic="robot/action_ctl",
            qos_profile=qos.qos_profile_system_default,
        )

        self.timer = self.create_timer(
            timer_period_sec=0.5,
            callback=self.timer_callback,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

        # LLM params
        llm_data = self.mem_params["llm"]
        llm_data["robot_name"] = self.mem_params["robot_name"]
        llm_data["robot_alias"] = self.mem_params["robot_alias"]

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

        self.mem_params["llm"] = LlmRequestManager(
            self, db_server.memory_settings, llm_data, emb_settings
        )

        self.recaller = IndyMemoryRecall(
            db_server, self.mem_params["embed_db"]
        )

        self.action_manager = cast(
            ActionManager,
            cleanup_action_manager(
                ActionManager(mongo_uri, mongo_port, self.robot_name),
                db_server,
            ),
        )

        self.obs_handler = LlmResponseHandler(
            self,
            self.robot_name,
            db_server,
            self.mem_params["llm"],
            self.mem_params["embed_db"],
            self.mem_params["default_scenario_stop"],
        )

        # self.switch_checker = ScenarioStartTracker(
        #     self, self.recaller.db_sm.client
        # )

        self.prev_scenario = self.current_scenario = 0

        self.cdb_writer = cast(
            CyberDBWriter,
            cleanup_database_manager(
                CyberDBWriter(mongo_uri, mongo_port, "tBlackBoard", "event"),
                db_server,
            ),
        )
        self.state_tracker = EpisodeStateTracker()

        # Episode State stuff
        if "initial_mode" not in self.mem_params:
            self.ep_state = EpisodeState.LOOPING
        else:
            if self.mem_params["initial_mode"] == "LOOPING":
                self.ep_state = EpisodeState.LOOPING
            elif self.mem_params["initial_mode"] == "WAITING":
                self.ep_state = EpisodeState.WAITING

        # Episode State Checking
        self.ep_start_ts = 0
        self.ctl_detector = self.create_subscription(
            String,
            "memory/episode_ctl",
            self.episode_ctl_callback,
            10,
            callback_group=MutuallyExclusiveCallbackGroup(),
        )

        self.logger.info("LLM Responder (v2.1.20260616) Initialized.")

        self.total_asr_timeout = self.mem_params["total_asr_timeout"]
        self.current_asr_timeout = self.total_asr_timeout
        self.asr_timeout_scenario = self.mem_params["asr_timeout_scenario"]

        # NOTE For Experiment
        self.experiment_log = db_server.memory_settings.experiment_log

    # def get_scenario_checker(self) -> ScenarioStartTracker:
    #     return self.switch_checker

    @property
    def logger(self):
        return self.get_logger()

    @property
    def ep_state(self):
        return self.state_tracker.ep_state

    @ep_state.setter
    def ep_state(self, v):
        self.state_tracker.ep_state = v

    def timer_callback(self):
        if (
            self.ep_state == EpisodeState.OFF
            or self.ep_state == EpisodeState.WAITING
        ):
            return

        obs = self.action_manager.get_next(
            {
                "status": "waiting",
                "command": "observation",
                "actor": self.robot_name,
                "option.trigger.llm-kd": {"$exists": True},
            }  # type: ignore
        )
        if not obs:
            return

        scenario_ts = self.ep_start_ts

        t = get_current_ts(self)
        self.logger.debug(f"## {jst_ts(t)} ##")

        opt = obs["option"]

        trigger = opt["trigger"][0]["llm-kd"]

        mode = list(trigger.keys())[0]
        prompt_id = trigger[mode]
        self.logger.info(f"Mode: {mode} | Prompt ID: {prompt_id}")

        timeout = opt["timeout"] if "timeout" in opt else 30
        task_key = opt["task"] if "task" in opt else ""
        temperature = opt["temperature"] if "temperature" in opt else 1.0
        history = opt["history"] if "history" in opt else 30
        history_in_prompt = (
            opt["history_in_prompt"] if "history_in_prompt" in opt else False
        )

        keyword_validation = (
            opt["keyword_validation"] if "keyword_validation" in opt else {}
        )

        stop_phrase = (
            opt["stop_phrase"]
            if "stop_phrase" in opt
            else self.obs_handler.default_stop_phrase
        )

        hist_to_prompt = (
            opt["hist_to_prompt"] if "hist_to_prompt" in opt else False
        )

        # Memory Recall Function Params, Partial
        max_n, limit, weight_age, weight_dist = [
            (
                opt[k]
                if k in opt
                else self.mem_params["default_recall_params"][k]
            )
            for k in ["max_n", "limit", "weight_age", "weight_dist"]
        ]

        # recall_fn = partial(
        #     self.recaller.recall_narratives,
        #     n=max_n,
        #     dist_limit=limit,
        #     weight_age=weight_age,
        #     weight_dist=weight_dist,
        # )

        recall_fn = partial(
            self.recaller.recall_narrative_exp,
            n=max_n
        )  # NOTE Changed for Experiment

        # self.logger.debug(f"{t} | {timeout} | {t+timeout}")
        start_ts = get_current_ts(self)
        if mode == "reply":
            status = (
                "timeout"
                if self.obs_handler.get_reply(
                    prompt_id,
                    t + timeout,
                    recall_fn,
                    task_key,
                    scenario_ts,
                    temperature=temperature,
                    history=history,
                    keyword_validation=keyword_validation,
                    stop_phrase=stop_phrase,
                    hist_to_prompt=hist_to_prompt,
                )
                else "done"
            )
        elif mode == "prompt":
            status = (
                "timeout"
                if self.obs_handler.get_prompt(
                    prompt_id,
                    scenario_ts,
                    temperature=temperature,
                    history=history,
                    history_in_prompt=history_in_prompt,
                    keyword_validation=keyword_validation,
                    hist_to_prompt=hist_to_prompt,
                )
                else "done"
            )
        else:  # Unknown mode
            status = (
                "timeout"
                if self.obs_handler.get_default(
                    mode,
                    scenario_ts,
                    temperature=temperature,
                    history=history,
                    hist_to_prompt=hist_to_prompt,
                )
                else "done"
            )

        elapsed_ts = get_current_ts(self) - start_ts
        self.logger.debug(f"{mode} >> Response Status: {status}")
        self.action_manager.set_status(obs["_id"], status)

        if status == "timeout":
            self.cdb_writer.insert({"_id": "6961ce5627f4b5b137d872dc"})  # type: ignore
            self.current_asr_timeout -= elapsed_ts

            self.logger.debug(
                f"Global Timeout Remaining: {self.current_asr_timeout}"
            )

            # Full Scenario Time-out
            if self.current_asr_timeout <= 0:
                self.cdb_writer.insert({"_id": self.asr_timeout_scenario})
                self.current_asr_timeout = self.total_asr_timeout

        else:
            self.current_asr_timeout = self.total_asr_timeout

    def episode_ctl_callback(self, msg: String):
        if msg.data == "memory start episode":
            # Check Status
            if not self.ep_state.can_start_episode():
                # Invalid Start Status
                self.logger.debug(
                    "[RESPONDER] "
                    + "Cannot Start Memory Episode: Incompatible Initial State "
                    + f"({self.ep_state})"
                )
                return
            if self.ep_state == EpisodeState.IN_EPISODE:
                # No need to start episode
                return
            # Change Status
            self.logger.debug(
                "[RESPONDER] " + "Starting Memory Episode via episode_ctl"
            )

            # Because this starts the episode, we mark it as such.
            self.ep_start_ts = get_current_ts(self)
            self.current_asr_timeout = self.total_asr_timeout

            # Change Status
            self.ep_state = EpisodeState.IN_EPISODE
        elif msg.data == "memory end episode":
            # Check Status
            if self.ep_state != EpisodeState.IN_EPISODE:
                # Invalid Start Status
                self.logger.debug(
                    "[RESPONDER] "
                    + "Cannot End Memory Episode: Incompatible Initial State "
                    + f"({self.ep_state})"
                )
                return
            self.current_asr_timeout = self.total_asr_timeout
            # Change Status
            self.ep_state = EpisodeState.WAITING

            # NOTE For Experiment
            # Find Experiment log where end_ts is 0
            ts = get_current_ts(self)
            _log = self.experiment_log.find_one_and_update(
                filter={"end_ts": 0},
                update={"$set": {"end_ts": ts}},
                return_document=ReturnDocument.AFTER,
            )
            if _log:
                self.logger.debug("[EXP] Finished Experiment.")
                self.logger.debug(f"[EXP] UserID: {_log['user_id']}")
                self.logger.debug(f"[EXP] Sess. Type: {_log['session_type']}")
                self.logger.debug(
                    "[EXP] Time Range: "
                    + f"{_log['start_ts']} - {_log['end_ts']}"
                )

        elif msg.data == "memory loop episode":
            # Check Status
            if self.ep_state == EpisodeState.LOOPING:
                # No need to change anything
                return
            # Start Episode Loop
            self.ep_start_ts = get_current_ts(self)
            # Change Status
            self.ep_state = EpisodeState.LOOPING
        elif msg.data == "stop" or msg.data == "stop memory episodic":
            # Change Status
            self.ep_state = EpisodeState.OFF


def main():
    """Main function that creates and runs Indy's LLM Response Node."""
    rclpy.init()
    llmNode = LlmResponderNode()
    micWatchdogNode = LlmMicWatchdogNode(llmNode.state_tracker)
    executor = MultiThreadedExecutor()
    executor.add_node(llmNode)
    executor.add_node(micWatchdogNode)
    try:
        executor.spin()
    except KeyboardInterrupt:
        llmNode.logger.info(
            "Keyboard Interrupt, Shutting Down Response Node..."
        )
        rclpy.try_shutdown()
