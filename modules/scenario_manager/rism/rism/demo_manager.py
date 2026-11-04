# -*- coding: utf-8 -*-
import datetime
import time
from logging import getLogger
from queue import Empty, Queue
from threading import Event, Semaphore, Thread
from typing import List

from pyindy.mongo import (CyberDBReader, PhysicalDBReader,
                          get_internal_state_logger)

from .action_executor import ActionManager
from .scenario.scenario_manager import ScenarioManager


class DemoManager:
    def __init__(self, config: dict, robots: List[str], entry_point: str) -> None:
        self._logger = getLogger(__name__)
        config["robots"] = {f"robot{i+1}": robot for i, robot in enumerate(robots)}

        config_databases = self.setup_databases(config)

        # Robot info
        names = [config["robot_list"][robot]["name_alias"] for robot in robots]
        self._logger.info("と".join(names) + "が起動しました")
        self.internal_state_logger = get_internal_state_logger(config)

        # Sceneario Manager
        self.action_manager = ActionManager(config)
        self.scenario_manager = ScenarioManager(
            config, config_databases, self.action_manager, entry_point
        )
        self.is_finished: bool = False

        self.execute_semaphore = Semaphore(1)

        self.action_queue = Queue(maxsize=1)
        self.command_proc_semaphore = Semaphore(1)
        # set 状態 = 観測待ちなし。clear 状態 = 観測待ち中（run() がここで block する）
        self._observation_done = Event()
        self._observation_done.set()

        self._next_is_observation = False

        # Threads
        self.interruption_started = False
        self.interruption_out_wait = False
        self.backup_stack = []
        self.interruption_thread = Thread(target=self._interruption, daemon=True)
        self.output_thread = Thread(target=self._output, daemon=True)
        self.update_status_thread = Thread(target=self._update_status, daemon=True)

        self.interruption_thread.start()
        self.output_thread.start()
        self.update_status_thread.start()

    def setup_databases(self, config: dict) -> list:
        # Config for physical DB
        p_host: str = config["db_config"]["physical_db"]["host"]
        p_port: int = config["db_config"]["physical_db"]["port"]
        p_dbname: str = config["db_config"]["physical_db"]["dbname"]
        physical_db = PhysicalDBReader(p_host, p_port, p_dbname)

        # Config for cyber DB
        c_host: str = config["db_config"]["cyber_db"]["host"]
        c_port: int = config["db_config"]["cyber_db"]["port"]
        c_dbname: str = config["db_config"]["cyber_db"]["dbname"]
        cyber_db = CyberDBReader(c_host, c_port, c_dbname)

        # Database
        databases = {}
        databases["physical"] = physical_db
        databases["cyber"] = cyber_db

        return databases

    def _is_in(self, trigger: dict, observation: dict):
        items = list(trigger.items())
        if len(items) != 1:
            self._logger.warning(f"_is_in: trigger has {len(items)} keys, expected 1")
            return None, False
        key, value = items[0]
        if self.scenario_manager._is_in(trigger, observation):
            return observation, False
        mismatch = value is not None and key == observation["event"]
        return None, mismatch

    def _find_observation(self, triggers, observations):
        if len(triggers) > 1:
            self._logger.warning(
                "multiple trigger is not defined yet. only the first one is used"
            )
        trigger = triggers[0]
        mismatch = False
        for obs_db, obstype in observations.items():  # physical / cyber
            for obs in obstype:
                found, tmp_mismatch = self._is_in(trigger, obs)
                if tmp_mismatch:
                    mismatch = True
                if found is not None:
                    found["db_name"] = obs_db
                    return found, False
        return None, mismatch

    def run(self) -> None:
        """
        read event and generate action
        """
        while not self.is_finished:
            self.internal_state_logger.run_initialize()
            if not self.interruption_started:
                # generate action
                actions = self.scenario_manager.proc()

                if actions is not None and len(actions) == 1:
                    action = actions[0]
                    if "command" in action:
                        self.internal_state_logger.run_action(action)
                        if action["command"] == "observation":
                            # this should be outside of semaphore
                            self._next_is_observation = True
                            self._observation_done.clear()  # 観測待ち開始
                            self.action_queue.put(actions)
                            self._observation_done.wait()   # _output() が set() するまでブロック
                            continue
                        with self.command_proc_semaphore:
                            if action["command"] == "end_of_scenario":
                                self._logger.info(
                                    f"scenario {self.scenario_manager.scenario.name} finished"
                                )
                                self.scenario_manager.load_next_scenario_if_exist()
                                self._next_is_observation = False
                            elif action["command"] == "restore_scenario":
                                self._logger.info(
                                    f"scenario {self.scenario_manager.scenario.name} finished"
                                )
                                if len(self.backup_stack) > 0:
                                    restore_action = self.backup_stack.pop()
                                    if len(restore_action) > 0:
                                        actions = restore_action + actions
                                else:
                                    self._logger.warning(
                                        "backup_stack is empty, cannot restore"
                                    )
                                if self.scenario_manager.pop_scenario():
                                    self._logger.info(
                                        f"pushed scenario {self.scenario_manager.scenario.name} restored"
                                    )
                        self.action_queue.put(actions)
                    else:
                        self.action_queue.put(actions)
                else:
                    self.action_queue.put(actions)

            time.sleep(0.1)

    def _interruption(self) -> None:
        """
        check observation and make interruption
        """
        self.internal_state_logger.interruption_initialize()
        while not self.is_finished:
            if not self._observation_done.is_set():
                time.sleep(0.1)
                continue
            try:
                with self.command_proc_semaphore:
                    observations = self.scenario_manager.get_observations()
                    subscenario = self.scenario_manager.get_interruption(observations)
                    if subscenario:
                        self.internal_state_logger.interruption_subscenario(
                            observations, subscenario
                        )
                        self.interruption_started = True

                        if subscenario.get("force_interrupt", False):
                            self.action_manager.stop_all()

                        self.scenario_manager.start_subscenario(subscenario, observations)

                        # self.action_manager.execute([{"actor": "robot1", "name": "Indy1", "scenario": self.scenario_manager.scenario.name, "utterance": {"sentence": "割り込みあり．対処します．"}}])

                        if self.action_queue.empty():
                            self.backup_stack.append([])
                        else:
                            temp_queue = []
                            while True:
                                try:
                                    temp_queue.append(self.action_queue.get_nowait())
                                except Empty:
                                    break
                            self.internal_state_logger.interruption_temp_queue(temp_queue)
                            if self.scenario_manager.scenario.return_flag:
                                for g in temp_queue[::-1]:
                                    self.backup_stack.append(g)
                            else:
                                self.backup_stack.append([])
                        self._observation_done.set()
                        self._next_is_observation = False
                        self.interruption_started = False
            except Exception as e:
                self._logger.exception(f"_interruption: unexpected error: {e}")
                self.interruption_started = False

            time.sleep(0.1)

    def _wait_for_playing(self):
        while not self.is_finished:
            with self.execute_semaphore:
                if self._next_is_observation:
                    is_playing = self.action_manager.is_playing(
                        only_utterance=True,
                    )
                else:
                    is_playing = self.action_manager.is_playing()
            if not is_playing:
                break
            # self._logger.info("waiting")
            time.sleep(0.1)
        return

    def _output(self) -> None:
        while not self.is_finished:
            self.internal_state_logger.output_initialize()

            self._wait_for_playing()

            # self._logger.info("waiting finished")
            if self.is_finished:
                break
            actions = self.action_queue.get()
            self.internal_state_logger.output(actions)

            try:
                for action in actions:
                    if action is None:
                        self._logger.info("a scenario is finished")
                    elif "command" in action:
                        if action["command"] == "wait":
                            with self.command_proc_semaphore:
                                self._logger.info("Wait")
                                self._wait(action)
                        elif action["command"] == "print":
                            with self.command_proc_semaphore:
                                self._logger.info(self.dump())
                        elif action["command"] == "observation":
                            # observation_wait_flag により run() と _interruption() は停止済みのため
                            # command_proc_semaphore は不要
                            timeout = 5
                            if "timeout" in action:
                                timeout = action["timeout"]
                            found = None

                            if any(["asr" in a for a in action["trigger"]]):
                                self.scenario_manager._reset_specific_observations(
                                    ["asr"]
                                )
                                time.sleep(0.01)

                            if any(["gpt" in a for a in action["trigger"]]):
                                self.scenario_manager._reset_specific_observations(
                                    ["gpt"]
                                )
                                time.sleep(0.01)

                            observation_id = self.action_manager.observation_insert(
                                action
                            )
                            self._wait_for_playing()
                            self.scenario_manager.internal_state_logger.output_start_observation(
                                action
                            )
                            start_time = datetime.datetime.now()
                            while (
                                datetime.datetime.now() - start_time
                                < datetime.timedelta(seconds=timeout)
                                and not self.is_finished
                            ):
                                observations = self.scenario_manager.get_observations(
                                    ignore_register=True, observe_after=start_time
                                )

                                found, mismatch = self._find_observation(
                                    action["trigger"], observations
                                )
                                if (
                                    "failed_on_mismatch" in action
                                    and action["failed_on_mismatch"]
                                    and mismatch
                                ):
                                    break
                                if found is not None:
                                    break
                                time.sleep(0.1)
                            self.scenario_manager.internal_state_logger.output_end_observation()
                            if found:
                                self.action_manager.observation_update(
                                    observation_id,
                                    action["orig_name"],
                                    action["name"],
                                    found,
                                )
                                self._logger.info("observation found")
                                found["mentioned"] = True
                                self.scenario_manager._update_mentioned(observations)
                                self.scenario_manager.observation_register(
                                    action["_id"], found
                                )
                                if found["event"] == "asr":
                                    self.scenario_manager.internal_state_logger.output_talking_person(
                                        found["contents"]["instance_id"]
                                    )
                                    self.scenario_manager.add_asr_to_history(found)
                                if "success" in action:
                                    with self.scenario_manager.scenario_lock:
                                        self.scenario_manager.scenario.event_list = (
                                            action["success"]
                                            + self.scenario_manager.scenario.event_list
                                        )
                            elif mismatch:
                                self._logger.info("observation mismatch")
                                self.action_manager.observation_mismatch(
                                    observation_id,
                                    action["orig_name"],
                                    action["name"],
                                    action["trigger"],
                                )
                                if "mismatch" in action:
                                    with self.scenario_manager.scenario_lock:
                                        self.scenario_manager.scenario.event_list = (
                                            action["mismatch"]
                                            + self.scenario_manager.scenario.event_list
                                        )
                            else:
                                self._logger.info("observation timeout")
                                self.action_manager.observation_timeout(
                                    observation_id,
                                    action["orig_name"],
                                    action["name"],
                                    action["trigger"],
                                )
                                if "failure" in action:
                                    with self.scenario_manager.scenario_lock:
                                        self.scenario_manager.scenario.event_list = (
                                            action["failure"]
                                            + self.scenario_manager.scenario.event_list
                                        )
                            self._observation_done.set()
                            self._next_is_observation = False

                # action execute
                with self.execute_semaphore:
                    self.action_manager.execute(actions)
            except Exception as e:
                self._logger.exception(f"_output: unexpected error: {e}")
                self._observation_done.set()
                self._next_is_observation = False

    def kill_all(self):
        self.is_finished = True
        self._observation_done.set()  # wait() でブロック中の run() を解除

    def _update_status(self):
        while not self.is_finished:
            self.scenario_manager.update_sleep_scenarios()
            self.scenario_manager.update_ignore_triggers()
            time.sleep(0.1)

    def dump(self):
        d = ""

        d += self.scenario_manager.dump()
        d += self.action_manager.dump()

        return d

    def _wait(self, action):
        if "trigger" in action:
            if "timeout" in action:
                stime = time.time()
            loop = True
            while loop and not self.is_finished:
                observations = self.scenario_manager.get_observations()
                finished = self._is_observation_finished(action, observations)
                loop = not finished
                if "timeout" in action:
                    etime = time.time()
                    if etime - stime > float(action["timeout"]):
                        loop = False
                time.sleep(0.1)
        elif "timeout" in action:
            time.sleep(float(action["timeout"]))

    def _is_observation_finished(self, action, observations):
        for obs_key, obs_val in observations.items():
            for observation in sorted(
                obs_val, key=lambda x: x["inserted"], reverse=True
            ):
                if self.scenario_manager.is_trigger_contained(
                    action["trigger"], observation
                ):
                    self.scenario_manager.observation_register(
                        action["_id"], observation
                    )
                    observation["mentioned"] = True

                    self.scenario_manager._update_mentioned(observations)
                    return True
        return False
