#!/usr/bin/env python
# coding: utf-8 -*-

"""Main Node for Indy's Memory System."""
import subprocess
from pathlib import Path

import pymongo
import rclpy
from .util import ParamManager
from rclpy.logging import LoggingSeverity as LS
from rclpy.node import Node

from .long_term_memory import get_ltm_expo_modules
from .sensor_memory import get_sm_expo_modules
from .short_term_memory import get_stm_expo_modules
from .util import MemoryLevel, ParamDesc, get_default_params, get_ros_param
from .util.llm.embed_db import OpenAiEmbedDB
from .util.llm.llm_base import LlmManager


class MemoryNode(Node):
    """ROS Node that launches Indy's Memory System.
    Different parameters allow running each store with different settings:

    - `node_name`: Name of the ROS node. Preferably unique.
    - `uri`: The URI for the MongoDB in which the memory will be stored.
    - `port`: The Port for the MongoDB.
    - `sm_lvl`: Sensor Memory Level. Possible values are:
        - `0` to disable sensor memory
        - `1` for working sensor memory without forgetting; or
        - `2` for working sensor memory with forgetting every five minutes.
        - `3` to disable sensor memory but still let stm clear it(i.e. simulate sm)
    - `stm_lvl`: Short-Term Memory Level. Possible values are:
        - `0` to disable short-term memory;
        - `1` for working short-term memory without forgetting; or
        - `2` for working short-term memory with forgetting based on each module's
          forgetting curve and heuristics.
    - `ltm_lvl`: Long-Term Memory Level. Possible values are:
        - `0` to disable long-term memory;
        - `1` to enable long-term memory, no forgetting.
        - `2` to enable long-term memory with forgetting.
    - `eval`: enable evaluation logging, which records various execution data
      to a separate database (`memory_eval`). Default value is `False`.
    """

    def __init__(self, node_name: str = "memory_store") -> None:

        super().__init__(node_name=node_name)  # type: ignore

        # LOGGER LEVEL

        self.get_logger().info("Initializing Memory Store.")

        robot_name = self.get_namespace()
        ns = robot_name + "."

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

        self.get_logger().info(f"Connecting to {mongo_uri}:{mongo_port}...")
        self.db_server = pymongo.MongoClient(mongo_uri, mongo_port)

        self.get_logger().info(f"Connected to {mongo_uri}:{mongo_port}.")

        pm = ParamManager(self.db_server)
        params = pm.get_param("memory")

        if not params:
            self.get_logger().warning(
                "Parameters for Memory not in Params DB. "
                + "Using Default Values (This may cause unexpected behavior/errors)."
            )

        # Load all memory settings from DB
        self.mem_params = get_default_params(params)

        debug_msgs = self.mem_params["debug_msgs"]
        self.get_logger().set_level(LS.DEBUG if debug_msgs else LS.INFO)

        # Memory params
        sm_level = self.mem_params["memory_level"]["sm_lvl"]
        stm_level = self.mem_params["memory_level"]["stm_lvl"]
        ltm_level = self.mem_params["memory_level"]["ltm_lvl"]

        mem_lvl = MemoryLevel(sm_level, stm_level, ltm_level)

        mem_eval = self.mem_params["mem_eval"]

        # LLM params
        llm_data = self.mem_params["llm"]
        llm_data["robot_name"] = self.mem_params["robot_name"]
        llm_data["robot_alias"] = self.mem_params["robot_alias"]

        embeddb_loc = str(
            Path(self.mem_params["embed_api"]["embed_db"])
            .expanduser()
            .absolute()
            .resolve()
        )

        if "embed_api" in self.mem_params and self.mem_params["embed_api"]:

            emb_settings = self.mem_params["embed_api"]

            if (
                "db_url" in self.mem_params["embed_api"]
                and "db_port" in self.mem_params["embed_api"]
            ):
                # This means we are using the database.
                # So we need to bring up the database first.

                self.get_logger().info(
                    "ChromaDB CLI Server needed. Launching."
                )
                self.chromadb_api = subprocess.Popen(
                    [
                        "chroma",
                        "run",
                        "--path",
                        embeddb_loc,
                        "--host",
                        self.mem_params["embed_api"]["db_url"],
                        "--port",
                        self.mem_params["embed_api"]["db_port"],
                    ],
                    stdout=subprocess.DEVNULL,
                )

                rclpy.get_default_context().on_shutdown(self.shutdown_chroma)

                self.mem_params["embed_db"] = OpenAiEmbedDB.createFromHttps(
                    self.mem_params["embed_api"]["db_url"],
                    self.mem_params["embed_api"]["db_port"],
                    emb_settings["url"],
                    emb_settings["api_key"],
                    emb_settings["model"],
                    emb_settings["dimensions"],
                )
            else:
                self.mem_params["embed_db"] = OpenAiEmbedDB.createFromPath(
                    embeddb_loc,
                    emb_settings["url"],
                    emb_settings["api_key"],
                    emb_settings["model"],
                    emb_settings["dimensions"],
                )
        else:
            emb_settings = None

        self.mem_params["llm"] = LlmManager(
            self, self.db_server.memory_settings, llm_data, emb_settings
        )

        # LOAD SENSOR MEMORY MODULES
        if 0 < sm_level <= 2:
            self.get_logger().info("Initializing Sensor Memory Modules...")
            self.sm_modules = [
                load_module(
                    self,
                    self.db_server.sensor_memory,
                    self.db_server.memory_eval if mem_eval else None,
                )
                for load_module in get_sm_expo_modules()
            ]
            self.get_logger().info("Sensor Memory Modules Initialized.")

        # LOAD SHORT-TERM MEMORY MODULES
        if stm_level > 0:
            self.get_logger().info("Initializing Short-Term Memory Modules...")
            self.stm_modules = [
                load_module(
                    self,
                    self.db_server.sensor_memory,
                    self.db_server.short_term_memory,
                    self.db_server.memory_settings,
                    mem_lvl,
                    self.db_server.memory_eval if mem_eval else None,
                    self.mem_params,
                )
                for load_module in get_stm_expo_modules()
            ]
            self.get_logger().info("Short-Term Memory Modules Initialized.")

        if ltm_level > 0:
            self.get_logger().info("Initializing Long-Term Memory Modules...")
            self.ltm_modules = [
                load_module(
                    self,
                    self.db_server.short_term_memory,
                    self.db_server.long_term_memory,
                    self.db_server.memory_settings,
                    mem_lvl,
                    self.db_server.memory_eval if mem_eval else None,
                    self.mem_params,
                )
                for load_module in get_ltm_expo_modules()
            ]
            self.get_logger().info("Long-Term Memory Modules Initialized.")

        self.get_logger().debug(
            f"Memory Type: SM{sm_level}-STM{stm_level}-LTM{ltm_level}."
        )

        self.get_logger().info("Memory System (v2.0.1.20260618) has started.")

    def shutdown_chroma(self):
        if self.chromadb_api and self.chromadb_api.poll() is None:
            self.get_logger().info("Shutting Down Chroma CLI Server.")
            self.chromadb_api.terminate()
            try:
                self.chromadb_api.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.get_logger().warn(
                    "Chroma CLI Server did not Shutdown. Killing..."
                )
                self.chromadb_api.kill()


def main():
    """Main function that creates and runs Indy's Memory Node."""
    rclpy.init()
    node = MemoryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            "Keyboard Interrupt, Shutting Down Memory Node..."
        )
