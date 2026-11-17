"""event_processor.py - イベントを種類ごとの処理に振り分ける

ScenarioInterpreter から受け取ったイベントを、種類ごとの Handler に渡す。
種類の多い処理は Handler に分け、ここには振り分けと、どの Handler も使う処理
（プレースホルダー、会話履歴、scenario_exit など）を置く。

    action        ActionHandler       (event_action_handler.py)
    generate      GenerateHandler     (event_generate_handler.py、action の speak.type: generate)
    repeat/random/if/until  ControlFlowHandler (event_control_flow_handler.py)
    wait_for      ObservationHandler  (event_observation_handler.py)
    command_event / scenario_exit / queue_scenario  このクラス
"""
import math
import re
import time
import datetime
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from . import event_generators  # テストが get_generator を差し替えるため
from .constants import ACTION_CANCELLED_STATUSES, ExitCode
from .navigation_query import get_action_status
from .event_action_handler import ActionHandler
from .event_control_flow_handler import ControlFlowHandler
from .event_generate_handler import GenerateHandler
from .event_model import CommandEvent, Event, EventLike, FacePersonEvent, IncludeEvent, QueueScenarioEvent, ScenarioExitEvent
from .event_observation_handler import ObservationHandler
from .protocols import EventRuntime
from .scenario_model import Scenario, ScenarioLike


class EventProcessor:
    """イベントの種類ごとに Handler へ振り分ける"""

    # 実行中にプリフェッチの前提（観測や分岐）が変わるイベント

    def __init__(self, interpreter: EventRuntime) -> None:
        self.interpreter = interpreter
        self._logger = getLogger(__name__)
        self.actions = ActionHandler(self)
        self.generation = GenerateHandler(self)
        self.control_flow = ControlFlowHandler(self)
        self.observation = ObservationHandler(self)
        # イベントの種類 → 処理（Handler を差し替えても効くよう、呼ぶときに引く）
        self._handlers: Dict[str, Callable[[Event], bool]] = {
            "action": lambda event: self.actions.execute_action_event(event),
            "command_event": lambda event: self._execute_command_event(event),
            "scenario_exit": lambda event: self._execute_scenario_exit_event(event),
            "repeat": lambda event: self.control_flow.execute_repeat_event(event),
            "random": lambda event: self.control_flow.execute_random_event(event),
            "shuffle": lambda event: self.control_flow.execute_shuffle_event(event),
            "if": lambda event: self.control_flow.execute_if_event(event),
            "until": lambda event: self.control_flow.execute_until_event(event),
            "wait_for": lambda event: self.observation.execute_wait_for_event(event),
            "queue_scenario": lambda event: self._execute_queue_scenario_event(event),
            "suspend_navigation": lambda event: self._execute_suspend_navigation_event(event),
            "include": lambda event: self._execute_include_event(event),
            "face_person": lambda event: self._execute_face_person_event(event),
        }

    def _dispatch_event(self, event: Event) -> bool:
        """イベントの種類ごとの処理を呼ぶ"""
        # 返事待ちなどで状況が変わっても、先読みは消さない（使う前に状況が同じかを確かめる: PrefetchManager.take）
        handler = self._handlers.get(event.type)
        if handler is None:
            self._logger.warning(f"Unknown event type: {event.type}")
            return True
        return handler(event)

    def replace_placeholders(self, text: str, context: Dict[str, Any]) -> str:
        """プレースホルダー {変数名} を実際の値に置換

        サポート形式:
        - {変数名}: 単純な変数参照
        - {変数名.キー}: ドット記法
        - {triggered[key]}: ブラケット記法
        """
        import re
        pattern = r'\{([^}]+)\}'

        def replacer(match):
            var_expr = match.group(1)

            bracket_pattern = r'(\w+)\[([^\]]+)\](?:\[([^\]]+)\])?'
            bracket_match = re.match(bracket_pattern, var_expr)

            if bracket_match:
                var_name = bracket_match.group(1)
                first_key = bracket_match.group(2)
                second_key = bracket_match.group(3)

                try:
                    value = context[var_name]
                    first_key = first_key.strip('\'"')
                    value = value[first_key]

                    if second_key:
                        second_key = second_key.strip('\'"')
                        value = value[second_key]

                    return str(value)
                except (KeyError, TypeError):
                    raise KeyError(f"Variable {var_expr} not found")
            else:
                keys = var_expr.split('.')
                value = context
                try:
                    for key in keys:
                        value = value[key]
                    return str(value)
                except (KeyError, TypeError):
                    raise KeyError(f"Variable {var_expr} not found")

        return re.sub(pattern, replacer, text)

    # 条件の中で置き換えるプレースホルダー（{triggered[instance_id]} / {wait_for.contents.text} など）。
    # $regex の {2} のような書き方は置き換えない
    CONDITION_PLACEHOLDER = re.compile(r"\{(?:triggered\[|wait_for[.\[])[^{}]*\}")

    def resolve_condition(self, condition: Dict[str, Any]) -> Dict[str, Any]:
        """
        wait_for / if / until の条件の中のプレースホルダーを、待ち始めるときの値で置き換える

        例: {"person_noticed": {"instance_id": "{triggered[instance_id]}"}} で、
        割り込みのきっかけになった人の反応だけを待つ。値がプレースホルダーだけなら、元の型（数値など）のまま入れる。
        置き換えられないものはそのまま残す。
        """
        context = {"triggered": self.interpreter.ctx.triggered_observation or {},
                   "wait_for": self.interpreter.ctx.wait_for_result or {}}

        def resolve(value):
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            if not isinstance(value, str) or not self.CONDITION_PLACEHOLDER.search(value):
                return value
            try:
                if self.CONDITION_PLACEHOLDER.fullmatch(value):
                    return self._placeholder_value(value[1:-1], context)
                return self.CONDITION_PLACEHOLDER.sub(
                    lambda m: str(self._placeholder_value(m.group(0)[1:-1], context)), value)
            except (KeyError, IndexError, TypeError):
                self._logger.warning(f"Placeholder in condition not found, left as is: {value}")
                return value

        return resolve(condition)

    @staticmethod
    def _placeholder_value(expr: str, context: Dict[str, Any]) -> Any:
        """triggered[key] / wait_for.contents.text の値（型はそのまま）"""
        parts = re.findall(r"[^.\[\]'\"]+", expr)
        value = context
        for part in parts:
            value = value[part]
        return value

    def build_llm_history(self, current_actor: str) -> List[Dict[str, str]]:
        """LLM用の会話履歴を構築"""
        history = []
        for entry in self.interpreter.ctx.conversation_history:
            spk = "[SPK2]" if entry["actor"] == current_actor else "[SPK1]"
            history.append({"spk": spk, "utt": entry["text"]})
        return history

    def add_to_conversation_history(self, actor: str, text: str) -> None:
        """会話履歴に追加"""
        self.interpreter.ctx.conversation_history.append({"actor": actor, "text": text})

        if len(self.interpreter.ctx.conversation_history) > self.interpreter.max_history_length:
            self.interpreter.ctx.conversation_history = self.interpreter.ctx.conversation_history[-self.interpreter.max_history_length:]

        self._logger.debug(f"Added to conversation history: {actor}: {text}")

    def exit_requested(self) -> bool:
        """
        シナリオの残りのイベントを打ち切るべきか

        scenario_exit が実行されたとき（今のフレーム）と、メインシナリオを実行中に、割り込みが
        resume_after: terminate でメインシナリオを終わらせたとき。後者を見ないと、repeat / random / shuffle /
        if / until などの中で割り込まれたとき、その中の残りのイベントを最後まで実行してしまう。
        """
        ctx = self.interpreter.ctx
        if ctx.exit_requested is True:
            return True
        return ctx.terminate_main_scenario is True and ctx.interrupt_depth == 0

    def record_heard_speech(self, observation: Optional[Dict[str, Any]]) -> None:
        """
        待っていた観測が音声認識（asr）なら、相手の発話として会話履歴に入れる

        LLM の応答生成が相手の発言を踏まえられるようにする。
        """
        if not isinstance(observation, dict) or observation.get("event") != "asr":
            return
        contents = observation.get("contents")
        contents = contents if isinstance(contents, dict) else {}
        text = contents.get("text") or contents.get("words") or observation.get("text")
        if isinstance(text, str) and text.strip():
            self.add_to_conversation_history("user", text.strip())

    def execute_event(self, event: EventLike, event_type: Optional[str] = None) -> bool:
        """イベントを実行

        イベントに ignore_interruptions（サブシナリオIDのリスト）があれば、
        そのイベントの実行中（wait_for の分岐なども含む）はそれらの割り込みを無視する。

        Args:
            event: イベント（シナリオDBの dict でもよい）
            event_type: dict の type の代わりに使う種類（省略時は dict の type、無ければ action）

        Returns:
            成功した場合True
        """
        event = Event.coerce(event, event_type)
        if not event.ignore_interruptions:
            return self._dispatch_event(event)
        with self.interpreter.ctx.ignoring_interruptions(event.ignore_interruptions):
            return self._dispatch_event(event)

    def run_events(self, events: List[EventLike]) -> bool:
        """イベントを順に実行する。失敗したら False、scenario_exit などで打ち切られたらそこで True"""
        with self.interpreter.ctx.waits_ahead(events) as reserve_next:
            for idx, event in enumerate(events):
                reserve_next(idx)
                if not self.execute_event(event):
                    return False
                if self.exit_requested():
                    return True
        return True

    def _execute_command_event(self, event: EventLike) -> bool:
        """コマンドイベントを実行（任意のLinuxコマンド）"""
        event = CommandEvent.coerce(event)
        actor = event.actor
        if not actor:
            self._logger.warning("No actor specified in event, skipping this event")
            return True

        if actor not in self.interpreter.action_managers:
            self._logger.warning(f"Actor '{actor}' not found (no robot with this name), skipping this event")
            return True

        option = event.option
        if not option or "command" not in option:
            self._logger.error(f"Missing command in command_event for actor {actor}")
            return False

        managers = self.interpreter.action_managers[actor]
        ros_manager = managers.get("ros_command")
        if not ros_manager:
            self._logger.error(f"ros_command manager not found for actor {actor}")
            return False

        timeout = self.interpreter.executor_config.get(
            "default_command_event_timeout",
            self.interpreter.executor_config.get("default_timeout", 30)
        )

        try:
            ret = ros_manager.insert(option)
            if not ret or not hasattr(ret, 'inserted_id'):
                self._logger.error(f"Failed to insert command_event action for {actor}")
                return False
            action_id = ret.inserted_id
        except Exception as e:
            self._logger.error(f"Exception inserting command_event for {actor}: {e}", exc_info=True)
            return False

        start_time = time.time()
        actions = [{"command": "ros_command", "action_id": str(action_id)}]
        with self.interpreter.wait_state.waiting("command_event", event, timeout=timeout, actions=actions) as wait:
            while time.time() - start_time < timeout:
                try:
                    status = get_action_status(ros_manager, action_id)
                    if status in ("done", "ignored") or status in ACTION_CANCELLED_STATUSES:
                        wait.result = "done"
                        break
                    elif status in ["error", "failed"]:
                        self._logger.error(f"command_event failed for {actor}: {status}")
                        wait.result = "failed"
                        return False
                except Exception as e:
                    self._logger.error(f"Error checking command_event status for {actor}: {e}")
                    wait.result = "failed"
                    return False
                time.sleep(0.1)
            else:
                self._logger.error(f"command_event timed out or was cancelled for {actor}")
                wait.result = "timeout"
                return False

        self.interpreter.scenario_manager.history.add_to_finished_events(event.to_dict())
        return True

    def _execute_scenario_exit_event(self, event: EventLike) -> bool:
        """scenario_exitイベントを実行"""
        event = ScenarioExitEvent.coerce(event)
        exit_code = event.exit_code if "exit_code" in event.raw else ExitCode.SUCCESS
        exit_data = dict(event.exit_data)

        if event.next_scenario is not None and "next_scenario" not in exit_data:
            exit_data["next_scenario"] = event.next_scenario

        if exit_code == ExitCode.REDIRECT:
            if "next_scenario" not in exit_data:
                self._logger.error("scenario_exit with redirect requires next_scenario")
                return False

            next_scenario = exit_data["next_scenario"]
            if not isinstance(next_scenario, str) or len(next_scenario) != 24:
                self._logger.error(f"Invalid ObjectId format for next_scenario: {next_scenario}")
                return False

            try:
                int(next_scenario, 16)
            except ValueError:
                self._logger.error(f"Invalid ObjectId format (not hexadecimal): {next_scenario}")
                return False

        self.interpreter.ctx.scenario_exit_status = {
            "exit_code": exit_code,
            "exit_data": exit_data,
            "timestamp": datetime.datetime.now().isoformat()
        }

        self.interpreter.update_current_state({
            "scenario_exit_status": self.interpreter.ctx.scenario_exit_status
        })

        self._logger.info(f"Scenario exit: code={exit_code}, data={exit_data}")
        # 残りのイベント（repeat などのループ内も含む）を実行せずにシナリオを終える
        self.interpreter.ctx.exit_requested = True

        self.interpreter.scenario_manager.history.add_to_finished_events(event.to_dict())
        return True

    def run_exit_events(self, scenario: ScenarioLike) -> None:
        """
        exit_condition で打ち切られたシナリオの exit_events を実行する

        exit_events がイベント名ごとに書いてあれば、打ち切ったきっかけ（no_people など）のものを実行する。

        Args:
            scenario: 打ち切られたシナリオ（またはサブシナリオ）
        """
        if not self.interpreter.ctx.exit_condition_met:
            return
        self.interpreter.ctx.exit_condition_met = False
        self.interpreter.ctx.exit_requested = False
        triggers, self.interpreter.ctx.exit_trigger_events = self.interpreter.ctx.exit_trigger_events, []
        for exit_event in Scenario.coerce(scenario).exit_events_for(triggers):
            if not self.execute_event(exit_event):
                break
            if self.interpreter.ctx.exit_requested is True:
                break
        self.interpreter.ctx.exit_requested = True

    # include の入れ子の上限（自分を include し続けて止まらなくなるのを防ぐ）
    MAX_INCLUDE_DEPTH = 5

    def _execute_include_event(self, event: EventLike) -> bool:
        """include: 指定したシナリオ（サブシナリオ）のイベントを、今のシナリオの続きとしてその場で実行する"""
        event = IncludeEvent.coerce(event)
        depth = getattr(self, "_include_depth", 0)
        if depth >= self.MAX_INCLUDE_DEPTH:
            self._logger.error(f"include nested more than {self.MAX_INCLUDE_DEPTH} levels: {event.scenario}")
            return False
        target = self._find_included(event.scenario)
        if target is None:
            self._logger.error(f"include: scenario not found: {event.scenario}")
            return False
        self._logger.info(f"Including events of '{target.name}' ({len(target.events)} events)")
        self._include_depth = depth + 1
        try:
            ok = self.run_events(target.events)
        finally:
            self._include_depth = depth
        self.interpreter.scenario_manager.history.add_to_finished_events(event.to_dict())
        return ok

    def _find_included(self, scenario_id: str) -> Optional[Scenario]:
        """include するシナリオ。サブシナリオ、シナリオの順に探す（status は問わない）"""
        repository = self.interpreter.scenario_manager.scenarios
        try:
            return repository.find_subscenario(scenario_id) or repository.load_scenario(scenario_id, include_inactive=True)
        except Exception as e:
            self._logger.error(f"include: cannot load {scenario_id}: {e}")
            return None

    def _execute_suspend_navigation_event(self, event: EventLike) -> bool:
        """suspend_navigation: 実行中の移動を止める（割り込みの中なら、終わったら送り直す）"""
        self.interpreter.suspend_navigation()
        self.interpreter.scenario_manager.history.add_to_finished_events(Event.coerce(event).to_dict())
        return True

    def _execute_face_person_event(self, event: EventLike) -> bool:
        """
        face_person: 体をその人の方へ回す（その場で回る navigation の rotate を送り、回り終わるのを待つ）

        人の位置は観測の中から読む（tracking は読まない）。直前の wait_for で受け取った観測、割り込みのきっかけの
        観測の順に、location_sensor（体）か face_location_sensor（顔）を探す。instance_id があれば、その人の観測だけを使う。
        位置は頭のカメラの座標系（x が右、y が下、z が奥）で、首が正面を向いている前提。rotate はラジアンで、正が左回り。
        人の位置がわからないとき、回る角度が min_angle_deg より小さいときは、回らずに次へ進む。
        """
        event = FacePersonEvent.coerce(event)
        instance_id = self.resolve_condition({"instance_id": event.instance_id})["instance_id"]
        location = self._person_location(instance_id)
        if location is None:
            self._logger.warning(f"face_person: no location of person {instance_id} in the observations, not turning")
            return True
        angle = math.atan2(-float(location[0]), float(location[2]))   # 右（x > 0）にいれば負（右回り）
        if abs(math.degrees(angle)) < event.min_angle_deg:
            self._logger.info(f"face_person: person {instance_id} is already in front ({math.degrees(angle):.0f} deg)")
            return True
        self._logger.info(f"face_person: turning {math.degrees(angle):.0f} deg towards person {instance_id}")
        rotate = {"actor": event.actor, "type": "action", "interruptable": event.interruptable,
                  "navigation": {"type": "normal", "option": {"rotate": round(angle, 3)}}}
        return self.actions.execute_action_event(rotate)

    LOCATION_KEYS = ("location_sensor", "face_location_sensor")

    def _person_location(self, instance_id: Any) -> Optional[List[float]]:
        """
        その人の、頭のカメラから見た位置（wait_for の結果、きっかけの観測の順に探す）。なければ None

        instance_id が指定されていて、観測にも instance_id があるなら、同じ人の観測だけを使う。
        """
        ctx = self.interpreter.ctx
        for observation in (ctx.wait_for_result, ctx.triggered_observation):
            if not isinstance(observation, dict):
                continue
            contents = observation.get("contents") if isinstance(observation.get("contents"), dict) else {}
            fields = {**observation, **contents}
            if instance_id not in (None, "") and fields.get("instance_id") not in (None, "") \
                    and str(fields["instance_id"]) != str(instance_id):
                continue
            for key in self.LOCATION_KEYS:
                location = fields.get(key)
                if isinstance(location, (list, tuple)) and len(location) >= 3 and float(location[2]) > 0:
                    return list(location)
        return None

    def _execute_queue_scenario_event(self, event: EventLike) -> bool:
        """
        queue_scenario イベントを実行: scenario_manager のシナリオキューにシナリオIDを追加

        scenario_id の解決順序:
          1. event["option"]["scenario_id"] に明示指定されている場合はそれを使用
          2. なければ triggered_observation.contents.scenario_id を参照

        使用例（subscenario内）:
            {"type": "queue_scenario", "option": {"scenario_id": "scenario_001"}}
            {"type": "queue_scenario"}  # triggered_observation から自動抽出

        Args:
            event: イベント辞書

        Returns:
            成功した場合True
        """
        event = QueueScenarioEvent.coerce(event)
        scenario_id = event.option.get("scenario_id")

        if not scenario_id:
            # triggered_observation から scenario_id を抽出
            triggered = self.interpreter.ctx.triggered_observation
            if triggered:
                contents = triggered.get("contents", {})
                if isinstance(contents, dict):
                    scenario_id = contents.get("scenario_id")
                if not scenario_id:
                    scenario_id = triggered.get("scenario_id")

        if not scenario_id:
            self._logger.warning("[queue_scenario] No scenario_id found in option or triggered_observation")
            return True  # 失敗してもシナリオ実行は継続

        self.interpreter.scenario_manager.selector.add_to_scenario_queue(str(scenario_id))
        self._logger.info(f"[queue_scenario] Queued scenario: {scenario_id}")

        # F8: stress_level 更新
        self._update_stress_level_on_queue_add()

        return True

    def _update_stress_level_on_queue_add(self) -> None:
        """
        シナリオキュー追加時に stress_level を増加し、閾値アクションを実行する（F8）

        設定（MongoDB rism_configs.rism_config）:
            stress_level.increment: float  キュー追加時の増加量（デフォルト 0.2）
            stress_level.thresholds: list  閾値アクション定義リスト
        """
        if not hasattr(self.interpreter, "update_internal_state"):
            return

        stress_cfg = self.interpreter.config.get("stress_level", {})
        increment = stress_cfg.get("increment", 0.2)
        current = self.interpreter.internal_state.get("stress_level", 0.0)
        new_level = min(1.0, current + increment)
        self.interpreter.update_internal_state("stress_level", new_level)
        self._logger.info(f"[stress_level] Updated: {current:.2f} → {new_level:.2f}")

        self._check_stress_thresholds(new_level, stress_cfg)

    def _check_stress_thresholds(self, stress_level: float, stress_cfg: Dict[str, Any]) -> None:
        """
        stress_level が閾値を超えた場合に割り込みを投入する（F8）

        閾値設定例（MongoDB rism_configs.rism_config）:
            stress_level.thresholds:
              - level: 0.7
                action: "trigger_interrupt"
                subscenario_id: "<ObjectId文字列>"

        Args:
            stress_level: 更新後の stress_level 値
            stress_cfg: config["stress_level"] 辞書
        """
        for threshold in stress_cfg.get("thresholds", []):
            if stress_level < threshold.get("level", 1.0):
                continue
            action = threshold.get("action")
            if action != "trigger_interrupt":
                continue
            subscenario_id = threshold.get("subscenario_id")
            if not subscenario_id:
                self._logger.warning("[stress_level] threshold has no subscenario_id, skipping")
                continue

            try:
                subscenario = self.interpreter.scenario_manager.scenarios.find_subscenario(subscenario_id)
            except Exception as e:
                self._logger.error(f"[stress_level] Failed to find subscenario {subscenario_id}: {e}")
                continue

            if not subscenario:
                self._logger.warning(f"[stress_level] subscenario not found: {subscenario_id}")
                continue

            priority_level = subscenario.priority
            scenario_id_str = subscenario.id_str
            condition = subscenario.condition

            self.interpreter.interrupt_queue.add(
                priority_level, scenario_id_str, subscenario, condition, []
            )
            self._logger.info(
                f"[stress_level] Triggered interrupt: {subscenario.name} "
                f"(stress_level={stress_level:.2f}, threshold={threshold['level']})"
            )
