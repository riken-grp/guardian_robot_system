# -*- coding: utf-8 -*-
import random
import time
from logging import getLogger
from typing import Dict, List

from pyindy.mongo import PhysicalDBReader

from .action_executor import ActionManager


class QuickDemoManager:
    def __init__(self, config: dict, robotA: str, robotB: str) -> None:
        self._logger = getLogger(__name__)
        config["robots"] = {"robot1": robotA, "robot2": robotB}

        self.databases = self.setup_databases(config)
        self.robots = [robotA, robotB]

        # Sceneario Manager
        self.action_manager = ActionManager(config)
        self.is_finished: bool = False

    def setup_databases(self, config: dict) -> list:
        # Config for physical DB
        p_host: str = config["db_config"]["physical_db"]["host"]
        p_port: int = config["db_config"]["physical_db"]["port"]
        p_dbname: str = config["db_config"]["physical_db"]["dbname"]
        physical_db = PhysicalDBReader(p_host, p_port, p_dbname)

        # Database
        databases = {}
        databases["physical"] = physical_db

        self.robot_names = {"robot1": "Deejay Lee", "robot2": "Deejay Ken"}
        self.target_triggers = [
            "person_appear",
            "raising_hand",
            "someone call",
            "asr",
        ]

        return databases

    def run(self) -> None:
        save_obs = None
        while not self.is_finished:
            observations = self._get_observations()

            actions = None

            ret = {}
            ret["actor"] = random.choice(["robot1", "robot2"])
            ret["name"] = self.robot_names[ret["actor"]]
            ret["gesture"] = {}

            for obs in observations["physical"]:
                if obs["event"] in self.target_triggers:
                    ret["gesture"]["type"] = "normal"
                    ret["gesture"]["command"] = "Waving_hands"
                    actions = [ret]
                    save_obs = obs
                    # 参照に応じてquick_mentionedをついかすｒ
                    break

            # execute action
            if actions:
                self._output(actions)

            time.sleep(1)

    def _get_observations(self, n=20) -> List[Dict]:
        observations = {}
        observations["physical"] = self.databases["physical"].get_latest_N(n)
        return observations

    def _output(self, actions: List[dict]) -> None:
        for action in actions:
            if action is None:
                self._logger.info("a scenario is finished")
            elif "command" in action:
                # コマンドだった場合の処理
                if action["command"] == "wait":
                    self._logger.info("Wait")
                elif action["command"] in ["speak", "gesture"]:
                    self.action_manager.immediate_execute(action)
            else:
                # action execute
                self.action_manager.immediate_execute(action)
