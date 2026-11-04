# -*- coding: utf-8
import itertools
import random

from pyindy.mongo import get_internal_state_logger

from . import event_generators, events


class Scenario:
    def __init__(self, scenario_manager, scenario_data, is_main=True):
        self.internal_state_logger = get_internal_state_logger()
        self.started = False
        self.scenario_manager = scenario_manager
        self.config = scenario_manager.config
        self.observation_buffer = {}
        self.scenario_id = scenario_data["_id"]
        self.name = scenario_data["name"]
        self.scenario_data = scenario_data
        self.event_list = scenario_data["events"]
        self.triggered = scenario_data["triggered"]
        self.triggered_contents = scenario_data["triggered_contents"]
        self.interaction = False
        self.ignore_scenarios = (
            scenario_data["ignore_scenarios"]
            if "ignore_scenarios" in scenario_data
            else []
        )
        self.prompt = scenario_data["prompt"] if "prompt" in scenario_data else ""
        self.interaction_subscenario_ids = (
            scenario_data["interaction_subscenario_ids"]
            if "interaction_subscenario_ids" in scenario_data
            else []
        )
        self.ignore_after_activated = (
            scenario_data["ignore_after_activated"]
            if "ignore_after_activated" in scenario_data
            else 0
        )
        self.ignore_same_observations = (
            True
            if "ignore_same_observations" in scenario_data
            and scenario_data["ignore_same_observations"]
            else False
        )
        self.return_flag = "return" in scenario_data and scenario_data["return"]
        self.next_scenarios = (
            scenario_data["next_scenarios"]
            if not self.return_flag and "next_scenarios" in scenario_data
            else []
        )
        if is_main:
            self.event_list += self._generate_end_of_scenario_event()
        else:
            if self.return_flag:
                self.event_list += self._generate_restore_event()
            else:
                self.event_list += self._generate_end_of_scenario_event()

        self.event_generators = {}  # イベントをad hocに生成する生成クラスのdict

    def is_empty(self):
        return len(self.event_list) == 0

    def get_event(self):
        if len(self.event_list) == 0:
            return None
        else:
            return events.build_event(self.event_list[0], self)

    def activate_interaction(self, observations):
        self.interaction = True

    def deactivate_interaction(self, observations):
        self.interaction = False

    def generate(self, speaker_name, event, opts):
        # 生成 = scenario.event_listに対して，シナリオを追加する
        # （生成コマンドを，生成したイベント列に置き換える）
        #    speaker_name: ロボットの呼び名
        #    event: 現在の生成命令オブジェクト
        #    opts: 現在の観測情報等
        #    scenario: 現在実行中のシナリオ
        # Generatorが未定義なら読み込む

        if "generator" not in event["utterance"]:
            event["utterance"]["generator"] = "DefaultEventGenerator"

        if event["utterance"]["generator"] not in self.event_generators:
            self.event_generators[event["utterance"]["generator"]] = (
                event_generators.get_generator(
                    event["utterance"]["generator"], self.config
                )
            )

        # これまでの会話の情報
        # TODO event に actorが入っているか？ eにactorが入っているか？
        history = [
            {
                "spk": "[SPK1]" if e["actor"] != event["actor"] else "[SPK2]",
                "utt": e["utterance"]["sentence"],
            }
            for e in list(
                itertools.islice(
                    self.scenario_manager.finished_events,
                    0,
                    len(self.scenario_manager.finished_events) - 1,
                )
            )
            if "utterance" in e
            and "sentence" in e["utterance"]
            and (
                "add_context" not in e["utterance"] or not e["utterance"]["add_context"]
            )
        ] if self.scenario_manager.finished_events else []

        if "history_length" in event:
            history = history[: -int(event["history_length"])]

        # 生成したものをevent_listへ追加
        generated = self.event_generators[event["utterance"]["generator"]].generate(
            self, speaker_name, event, history, opts
        )

        self.event_list = [self.event_list[0]] + generated + self.event_list[1:]

    def _generate_restore_event(self):
        event = {}
        event["type"] = "command"
        event["command"] = "restore_scenario"
        return [event]

    def _generate_end_of_scenario_event(self):
        self.internal_state_logger.run_initialize()
        event = {}
        event["type"] = "command"
        event["command"] = "end_of_scenario"
        return [event]
