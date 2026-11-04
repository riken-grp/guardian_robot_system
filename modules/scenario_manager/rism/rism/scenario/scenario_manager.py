import random
import threading
import time
from collections import deque
from logging import getLogger
from typing import Dict, List, Tuple

from bson import ObjectId
from pyindy.mongo import get_internal_state_logger
from pymongo import MongoClient

from . import scenario_generators
from .scenario import Scenario


class ScenarioManager:
    def __init__(self, config: dict, databases: list, action_manager, entry_point):
        self._logger = getLogger(__name__)
        self.config = config
        self.databases = databases
        self.action_manager = action_manager
        self.is_idling = False
        self.internal_state_logger = get_internal_state_logger(config)

        # Scenario Database
        dbconf = config["db_config"]["scenario_db"]
        client = MongoClient(dbconf["host"], dbconf["port"])
        self.db = client[dbconf["dbname"]][dbconf["col_name"]]
        self.interruption_db = client[dbconf["dbname"]][dbconf["interruption_col_name"]]
        self.interaction_db = client[dbconf["dbname"]][dbconf["interaction_col_name"]]

        self.scenario = None
        self.scenario_lock = threading.RLock()  # protects self.scenario and scenario.event_list
        self.scenario_stack = []
        self.scenario_generators = {}
        self.ignore_triggers = {}  # ignore triggers for a specific duration
        self.sleep_scenarios = {}

        self.finished_events = deque([], maxlen=self.config["finished_queue_length"])

        if entry_point:
            self.load_entry_point(entry_point)

    def load_entry_point(self, entry_point):
        try:
            found = self.db.find_one({"_id": ObjectId(entry_point)})
            if found is None:
                return
        except Exception:
            return

        self._logger.info(f"start from entry_point: {entry_point}")

        scenario_data = found
        scenario_data["triggered"] = []
        scenario_data["triggered_contents"] = {}

        self.action_manager.cancel_all()
        self.scenario = Scenario(self, scenario_data)
        self.update_internal_status()
        self._reset_observations()

    def update_internal_status(self):
        if self.is_idling:
            self.internal_state_logger.idling()
        else:
            self.internal_state_logger.scenario_update(self)

    def proc(self) -> List[Dict]:
        observations = self.get_observations()

        with self.scenario_lock:
            scenario_empty = self.scenario is None or self.scenario.is_empty()

        if scenario_empty:
            # add main scenario if current scenario is empty
            # MongoDB query は低速のためロック外で実行
            main_scenario = self._get_scenario(observations)
            if main_scenario is None:
                with self.scenario_lock:
                    if not self.is_idling:
                        self.is_idling = True
                        self._logger.info("Idling")
                        self.update_internal_status()
                time.sleep(1)
                return []
            else:
                self.is_idling = False
                if "ignore_after_activated" in main_scenario:
                    self.sleep_scenarios[main_scenario["_id"]] = main_scenario[
                        "ignore_after_activated"
                    ]
            self.observation_buffer_reset()
            self.action_manager.cancel_all()
            with self.scenario_lock:
                self.scenario = Scenario(self, main_scenario)
            # self._reset_observations()
            self._reset_specific_observations(["asr"])
            self._logger.info(f"Scenario {main_scenario['name']} is starting.")
            self.update_internal_status()
            self.observation_buffer_reset()

        # generate action from one step of scenario
        # get_event() と started フラグ更新をアトミックに取得
        with self.scenario_lock:
            event = self.scenario.get_event()
            if "interruptable" in event.data and event.data["interruptable"]:
                self.internal_state_logger.proc_show_variable("interruptable", True)
            else:
                self.internal_state_logger.proc_show_variable("interruptable", False)
            if not self.scenario.started:
                self.scenario.started = True

        if event:
            # event.proc() は LLM 呼び出しがあるため低速 → ロック外で実行
            actions = event.proc(observations)
            # done_event() と scenario.name 参照はアトミックに実行
            with self.scenario_lock:
                self.done_event()
                for action in actions:
                    action["scenario"] = self.scenario.name
            self._update_mentioned(observations)
        else:
            with self.scenario_lock:
                self.load_next_scenario_if_exist()
            return None

        return actions

    def done_event(self):
        if self.scenario.is_empty():
            return

        event = self.scenario.event_list.pop(0)
        if "utterance" in event:
            if event["utterance"]["type"] not in ["normal", "blank"]:
                return

        if "gesture" in event and event["gesture"]["type"] != "normal":
            return

        if "eye" in event and event["eye"]["type"] != "normal":
            return

        if "navigation" in event and event["navigation"]["type"] != "normal":
            return

        if "recall" in event and event["recall"]["type"] != "normal":
            return

        self.finished_events.append(event)

    def get_interruption(self, observations):
        if self.is_idling:
            return self._check_and_generate_interruption(observations)
        if self.scenario is None:
            return None

        subscenario = None
        is_interruption = None
        if self.scenario.interaction:
            # interaction mode
            subscenario = self._get_interaction_subscenario(observations)
        else:
            subscenario = self._check_and_generate_interruption(observations)

        return subscenario

    def start_subscenario(self, subscenario, observations):
        self.observation_buffer_reset()

        with self.scenario_lock:
            if not self.is_idling and "return" in subscenario and subscenario["return"]:
                self._logger.info(f"scenario {self.scenario.name} is pushed.")
                self.scenario_stack.append(self.scenario)
            else:
                self.scenario_stack = []
            self.scenario = Scenario(self, subscenario, is_main=False)

        if self.scenario.interaction:
            self._logger.info(
                f"Interaction SubScenario {subscenario['name']} is starting."
            )
        else:
            self._logger.info(
                f"Interruption SubScenario {subscenario['name']} is starting."
            )

        self.is_idling = False
        self.update_internal_status()
        self._update_mentioned(observations)
        self._reset_specific_observations(["asr"])
        return True, self.scenario.return_flag

    def _reset_asr(self) -> None:
        query = {"event": "asr"}
        data = {"ignored": True}
        try:
            self.databases["physical"].db.update_many(query, {"$set": data})
        except Exception as e:
            self._logger.error(e)

    def _reset_specific_observations(self, observation_names) -> None:
        query = {"event": {"$in": observation_names}}
        data = {"ignored": True}
        try:
            self.databases["cyber"].db.update_many(query, {"$set": data})
            self.databases["physical"].db.update_many(query, {"$set": data})
        except Exception as e:
            self._logger.error(e)

    def _reset_observations(self) -> None:
        query = {}
        data = {"mentioned": True, "ignored": True}
        try:
            self.databases["physical"].db.update_many(query, {"$set": data})
            self.databases["cyber"].db.update_many(query, {"$set": data})
        except Exception as e:
            self._logger.error(e)

    def get_observations(
        self, n=100, ignore_register=False, observe_after=None
    ) -> List[Dict]:
        observations = {}
        observations["physical"] = self.databases["physical"].get_latest_N(
            n, observe_after=observe_after
        )
        observations["cyber"] = self.databases["cyber"].get_latest_N(
            n, observe_after=observe_after
        )
        if self.scenario is not None and not ignore_register:
            for obs in self.scenario.observation_buffer.values():
                key = obs["db_name"]
                observations[key].append(obs)
        return observations

    def _is_in(self, trigger: dict, observation: dict):
        items = list(trigger.items())
        if len(items) != 1:
            self._logger.warning(f"_is_in: trigger has {len(items)} keys, expected 1")
            return False
        key, value = items[0]
        if value is None:
            # OK if observation contains the key
            if key == observation["event"]:
                return True
            else:
                return False
        else:
            if key == observation["event"]:
                cond = True
                if not isinstance(value, dict):
                    return False
                for name, cvalue in value.items():
                    if isinstance(cvalue, dict):
                        if "$gt" in cvalue and name in observation["contents"]:
                            cond = (
                                cond and observation["contents"][name] > cvalue["$gt"]
                            )
                        if "$lt" in cvalue and name in observation["contents"]:
                            cond = (
                                cond and observation["contents"][name] < cvalue["$lt"]
                            )
                        if "$in" in cvalue and name in observation["contents"]:
                            cond = (
                                cond and observation["contents"][name] in cvalue["$in"]
                            )
                        if "$not" in cvalue and name in observation["contents"]:
                            cond = (
                                cond and observation["contents"][name] != cvalue["$not"]
                            )
                    else:
                        # OK if observation contains the key and its value is equal to value
                        cond = cond and observation["contents"][name] == cvalue
                    if not cond:
                        break
                return cond
            return False

    def is_trigger_contained(self, triggers, observation):
        is_contain = True
        for trigger in triggers:
            tmp = self._is_in(trigger, observation)
            is_contain = is_contain and tmp
            if not is_contain:
                break

        return is_contain

    def _get_scenario(self, observations) -> Scenario:
        # pick a scenario using observations
        possible_scenarios, weights = self._get_possible_scenarios(observations)

        if len(possible_scenarios) == 0:
            return None

        # randomly select a scenario based on its importance
        scenario_data = random.choices(possible_scenarios, weights=weights)[0]

        for t in scenario_data["triggered"]:
            t["mentioned"] = True

        # 完全LLM生成シナリオの場合はここで生成する
        if "events" not in scenario_data:
            scenario_data.update(self._generate_scenario(scenario_data, observations))

        return scenario_data

    def _get_possible_scenarios(self, observations) -> List[Tuple[float, Scenario]]:
        try:
            scenario_pool = list(self.db.find({"status": "active"}))
        except Exception as e:
            self._logger.error(e)
            scenario_pool = []

        scenario_pool = [
            scenario
            for scenario in scenario_pool
            if not self._check_sleep_scenario(scenario)
        ]
        return self._scenario_selection(scenario_pool, observations)

    def _check_sleep_scenario(self, scenario):
        return scenario["_id"] in self.sleep_scenarios

    def update_sleep_scenarios(self):
        scenarios = {}
        for key, value in self.sleep_scenarios.items():
            if value > 0:
                scenarios[key] = value - 1
        self.sleep_scenarios = scenarios

    def _scenario_selection(self, scenario_pool, observations):
        # must not be called if the condition scenario["trigger"] is not met
        possible_scenarios = []
        is_hit = False
        for scenario in scenario_pool:
            scenario["triggered"] = []
            scenario["triggered_contents"] = {}
            if "trigger" not in scenario or len(scenario["trigger"]) == 0:
                # scenarios without trigger info. (always add)
                possible_scenarios.append((scenario, scenario["priority"]))
            else:
                for obs_key, obs_val in observations.items():
                    is_contain = False
                    for observation in sorted(
                        obs_val, key=lambda x: x["inserted"], reverse=True
                    ):
                        is_contain = self.is_trigger_contained(
                            scenario["trigger"], observation
                        )

                        if is_contain:
                            if "save_trigger_contents_values" in scenario:
                                for k in scenario["save_trigger_contents_values"]:
                                    if k in observation["contents"]:
                                        scenario["triggered_contents"][k] = observation[
                                            "contents"
                                        ][k]
                            observation["mentioned"] = True
                            possible_scenarios.append((scenario, scenario["priority"]))
                            is_hit = True
                            break
                    if is_contain:
                        break

        if is_hit:
            # トリガーにかかった場合は，無条件実行のものを弾く
            possible_scenarios = [
                (scenario, importance)
                for scenario, importance in possible_scenarios
                if len(scenario["trigger"]) != 0
            ]

        if len(possible_scenarios) == 0:
            return [], []
        return list(zip(*possible_scenarios))

    def _generate_scenario(self, scenario_data, opts):
        # 生成 = scenario(BDのエントリjson)の要素すべてを生成する
        # Generatorが未定義なら読み込む
        generator_name = scenario_data["generator"]
        if generator_name not in self.scenario_generators:
            self.scenario_generators[generator_name] = (
                scenario_generators.get_generator(generator_name, self.config)
            )

        return self.scenario_generators[generator_name].generate(self.config, opts)

    def _is_interruptable(self):
        if self.is_idling:
            return True

        if self.scenario is None:
            return True

        if len(self.finished_events) == 0:
            return False

        if not self.scenario or len(self.scenario.event_list) == 0:
            return False

        if not self.scenario.started:
            return False

        prev_event = self.finished_events[-1]
        if (
            "type" in self.scenario.event_list[0]
            and self.scenario.event_list[0]["type"] == "idling"
        ):
            # 待ち状態のときは割り込み可
            return True
        elif "interruptable" in prev_event and not prev_event["interruptable"]:
            # 割り込み不可の状態
            return False
        else:
            return True

    def _get_interaction_subscenario(self, observations) -> Scenario:
        if not self._is_interruptable():
            return None

        # pick a scenario using observations
        possible_scenarios, weights = self._get_possible_subscenarios(observations)

        if len(possible_scenarios) == 0:
            return None

        # randomly select a scenario based on its importance
        scenario_data = random.choices(possible_scenarios, weights=weights)[0]

        for t in scenario_data["triggered"]:
            t["mentioned"] = True

        # 完全LLM生成シナリオの場合はここで生成する
        if "events" not in scenario_data:
            scenario_data.update(self._generate_scenario(scenario_data, observations))

        return scenario_data

    def _get_possible_subscenarios(self, observations) -> List[Tuple[float, dict]]:
        try:
            subscenario_pool = list(self.interaction_db.find({"status": "active"}))
        except Exception as e:
            self._logger.error(e)
            subscenario_pool = []

        subscenario_pool = [
            subs
            for subs in subscenario_pool
            if str(subs["_id"]) in self.scenario.interaction_subscenario_ids
        ]
        return self._scenario_selection(subscenario_pool, observations)

    def _check_and_generate_interruption(self, observations):
        possible_interruptions, weights = self._get_possible_interruptions(observations)

        # 重要な割り込みが存在する場合は優先
        subscenario_data = self._find_important_scenario(
            possible_interruptions, weights
        )
        if subscenario_data is not None:
            for t in subscenario_data["triggered"]:
                t["mentioned"] = True
            return subscenario_data

        # 割り込み不可な状況の場合は終了
        if not self._is_interruptable():
            return None

        if len(possible_interruptions) == 0:
            return None

        # randomly select a subscenario based on its importance
        subscenario_data = random.choices(possible_interruptions, weights=weights)[0]

        for t in subscenario_data["triggered"]:
            t["mentioned"] = True

        return subscenario_data

    def _find_important_scenario(self, possible_interruptions, original_weights):
        weights = [
            w
            for i, w in enumerate(original_weights)
            if "important" in possible_interruptions[i]
            and possible_interruptions[i]["important"]
        ]
        scenarios = [
            s for s in possible_interruptions if "important" in s and s["important"]
        ]
        if len(scenarios) == 0:
            return None
        else:
            return random.choices(scenarios, weights=weights)[0]

    def _get_possible_interruptions(self, observations) -> List[Tuple[float, dict]]:
        try:
            subscenario_pool = list(self.interruption_db.find({"status": "active"}))
        except Exception as e:
            self._logger.error(e)
            subscenario_pool = []

        subscenario_pool = [
            scenario
            for scenario in subscenario_pool
            if self.is_idling or not self._check_ignore(scenario)
        ]
        return self._scenario_selection(subscenario_pool, observations)

    def _check_ignore(self, scenario):
        # check the given scenario trigger should be ignored or not
        if (
            not self.is_idling
            and scenario
            and self.scenario
            and scenario["_id"] in self.scenario.ignore_scenarios
        ):
            return True
        for trig in scenario["trigger"]:
            ((key, val),) = trig.items()
            if key in self.ignore_triggers:
                return True
        return False

    def update_ignore_triggers(self):
        trigs = {}
        for key, value in self.ignore_triggers.items():
            if value > 0:
                trigs[key] = value - 1
        self.ignore_triggers = trigs

    def _update_mentioned(self, opts: dict) -> None:
        for key, obs in opts.items():
            for o in obs:
                if "mentioned" in o and o["mentioned"]:
                    self.databases[key].set_mentioned(
                        o, self.scenario.ignore_same_observations
                    )
                    self.ignore_triggers[o["event"]] = (
                        self.scenario.ignore_after_activated
                    )

    def dump(self):
        name = self.scenario.name if self.scenario is not None else "(none)"
        return f"scenario manager: {name}"

    def add_asr_to_history(self, observation):
        data = {}
        data["actor"] = "person"
        data["utterance"] = {}
        data["utterance"]["type"] = "normal"
        try:
            data["utterance"]["sentence"] = observation["contents"]["words"]
            self.finished_events.append(data)
        except Exception as e:
            self._logger.error(e)
            pass

    def observation_register(self, obs_id, observation):
        self.scenario.observation_buffer[str(obs_id)] = observation

    def observation_buffer_reset(self):
        if self.scenario is not None:
            self.scenario.observation_buffer = {}

    def pop_scenario(self):
        with self.scenario_lock:
            if len(self.scenario_stack) > 0:
                self.scenario = self.scenario_stack.pop()
                self._logger.info(f"scenario {self.scenario.name} poped.")
                return True
            return False

    def load_next_scenario_if_exist(self):
        if self.pop_scenario():
            return

        possible_scenarios = []
        weights = []
        for ns in self.scenario.next_scenarios:
            try:
                found = self.db.find_one({"_id": ObjectId(ns)})
            except Exception:
                found = None
            if found is not None:
                possible_scenarios.append(found)
                weights.append(found["priority"])
        self._logger.info(
            f"{self.scenario.name} found next_scenarios: "
            + ":".join([s["name"] for s in possible_scenarios])
        )

        if len(possible_scenarios) == 0:
            with self.scenario_lock:
                self.scenario = None  # idle 遷移時のみ None にする（ウィンドウを最小化）
            self.is_idling = True
            self.update_internal_status()
            return

        # randomly select a scenario based on its importance
        scenario_data = random.choices(possible_scenarios, weights=weights)[0]
        scenario_data["triggered"] = []
        scenario_data["triggered_contents"] = {}

        with self.scenario_lock:
            self.scenario = Scenario(self, scenario_data)  # None を経由せず直接置き換え
        self.internal_state_logger.scenario_update(self)
        self._reset_specific_observations(["asr"])
        self.observation_buffer_reset()
