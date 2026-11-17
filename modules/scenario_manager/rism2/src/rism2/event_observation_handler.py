"""event_observation_handler.py - 観測を待つイベント（wait_for）と、観測の待ち方"""
import datetime
import time
from contextlib import contextmanager
from logging import getLogger
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from bson import ObjectId

from .condition_checker import match_any_null_key
from .condition_waiter import WaitResult
from .constants import ACTION_CANCELLED_STATUSES, RECEIVED_AT_KEY
from .action_change_notifier import notifier_for
from .navigation_query import get_action_status, get_collection_and_actor
from .event_model import Event, EventLike, WaitForEvent

if TYPE_CHECKING:
    from .event_processor import EventProcessor


def _received_before(obs: Dict[str, Any], since: float) -> bool:
    """
    観測を受け取ったのが since（time.time()）より前か

    キャッシュが書いた受け取り時刻を使う。ない観測（DB から直接読んだときなど）は、_id の ObjectId の
    作成時刻を使う。どちらもなければ古くないとみなす
    """
    received = obs.get(RECEIVED_AT_KEY)
    if received is None:
        obs_id = obs.get("_id")
        if not isinstance(obs_id, ObjectId):
            return False
        received = obs_id.generation_time.timestamp()
    return received < since


class ObservationHandler:
    """wait_for と、if / until も使う観測の待ち合わせ"""

    def __init__(self, events: "EventProcessor") -> None:
        self.events = events
        self.interpreter = events.interpreter
        self._logger = getLogger(__name__)

    def poll_condition(self, event: EventLike, check_condition, timeout: float,
                       start_time: float, label: str):
        """
        条件に合う観測を最大 0.5 秒待ち、合った観測を確保する（待ちのループの1回分。wait_for / if / until）

        待つ前に、打ち切り（exit）と、たまっている割り込みを確認する。
        合った観測は使用済みにする。ほかの処理（割り込み検知など）が先に使っていたら、合わなかったことにする
        （その観測はキャッシュからも外れるので、次の回では別の観測で照合する）。

        Returns:
            ConditionWaiter の結果（observations は確保できたもの）。打ち切られたか時間切れなら None
        """
        if self.events.exit_requested():
            return None
        if Event.coerce(event).interruptable and self.interpreter.process_pending_interrupts():
            self._logger.info(f"Interrupt handled during {label}, resuming")
            if self.events.exit_requested():  # 割り込みがメインシナリオを終わらせた
                return None
        remaining_time = timeout - (time.time() - start_time)
        if remaining_time <= 0:
            return None
        result = self.interpreter.condition_waiter.wait_for_condition(
            check_condition=check_condition,
            timeout=min(remaining_time, 0.5)
        )
        if not (result.matched and result.observations):
            return result
        claimed = self.interpreter.scenario_manager.observations.claim_observations(
            [obs for obs in result.observations if obs])
        if not claimed:
            self._logger.info(f"Matched observation was already used elsewhere, keep waiting ({label})")
            return WaitResult(matched=False, observations=[])
        return WaitResult(matched=True, observations=claimed)

    @contextmanager
    def reserve_observation_events(self, event_keys):
        """
        ブロック内の間、event_keys の観測を割り込み検知に取らせない

        入れ子（until のループ内の wait_for など）でも、抜けるときは外側の予約に戻す。
        抜けるときは、待ち始める前からしていた予約（ExecutionContext.waits_ahead）も外す。
        """
        with self.interpreter.ctx.reserving(event_keys):
            yield

    def execute_pre_wait_actions(self, event: EventLike) -> bool:
        """
        待機イベント（wait_for / if / until）の待つ前に gesture / navigation を実行する

        どれかが送れない・失敗する・時間切れになったら False（イベントを失敗にする）。
        """
        event = Event.coerce(event)  # wait_for / if / until（action の形の dict でもよい）
        actor = event.actor
        if not actor:
            return True
        if actor not in self.interpreter.action_managers:
            self._logger.warning(f"Actor '{actor}' not found (no robot with this name), skipping pre-wait actions")
            return True

        commands = [(name, data) for name in ("gesture", "navigation")
                    if (data := getattr(event, name, None)) is not None]
        if not commands:
            return True
        self._logger.info(f"Executing pre-wait actions for {actor}: {[name for name, _ in commands]}")

        sent = []
        for name, data in commands:
            sent_action = self._send_pre_wait_action(event, actor, name, data)
            if sent_action is None:
                return False
            sent.append(sent_action)
        for action_id, manager, name in sent:
            if not self._wait_pre_wait_action(actor, action_id, manager, name, event):
                return False

        self._logger.info(f"Pre-wait actions completed for {actor}")
        return True

    def _send_pre_wait_action(self, event: Event, actor: str, name: str, data: Dict[str, Any]):
        """待つ前の gesture / navigation を1つ送る。送れなかったら None、送れたら (action_id, manager, 種類)"""
        manager = self.interpreter.action_managers[actor].get(name)
        if manager is None:
            self._logger.error(f"Manager '{name}' not found for actor {actor}")
            return None
        option = self.events.actions.process_command_option(name, data, event)
        payload = self.events.actions.gesture_data(option) if name == "gesture" else option
        try:
            ret = manager.insert(payload)
        except Exception as e:
            self._logger.error(f"Exception inserting {name} action for {actor}: {e}", exc_info=True)
            return None
        if not ret or not hasattr(ret, 'inserted_id'):
            self._logger.error(f"Failed to insert {name} action for {actor}")
            return None
        return ret.inserted_id, manager, name

    def _wait_pre_wait_action(self, actor: str, action_id: Any, manager: Any, name: str,
                              event: Optional[Event] = None) -> bool:
        """待つ前の動作1つの完了を待つ（executor の default_{種類}_timeout まで）。終わらなければ False"""
        config = self.interpreter.executor_config
        timeout = config.get(f"default_{name}_timeout", config.get("default_timeout", 30))
        start_time = time.time()
        notifier = notifier_for(get_collection_and_actor(manager)[0])
        actions = [{"command": name, "action_id": str(action_id)}]
        with self.interpreter.wait_state.waiting("pre_wait_action", event, timeout=timeout, actions=actions) as wait, \
                notifier.watching(action_id) as changed:
            wait.result = "timeout"
            while time.time() - start_time < timeout:
                try:
                    status = get_action_status(manager, action_id)
                except Exception as e:
                    self._logger.error(f"Error checking {name} status for {actor}: {e}")
                    wait.result = "failed"
                    break
                if status in ("done", "ignored"):
                    wait.result = "done"
                    return True
                if status in ACTION_CANCELLED_STATUSES:
                    wait.result = "failed"  # 取り消された（今までどおり、待つ前の動作は済んだものとして進む）
                    return True
                if status in ("error", "failed"):
                    self._logger.error(f"Pre-wait action {name} failed for {actor}")
                    wait.result = "failed"
                    break
                notifier.pause(changed)
        self._logger.error(f"Pre-wait action {name} timed out or was cancelled for {actor}")
        return False

    def execute_wait_for_event(self, event: EventLike) -> bool:
        """wait_forイベントを実行（観測データ待機＋結果保存）"""
        event = WaitForEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        condition = self.events.resolve_condition(event.condition)
        timeout = event.timeout if event.timeout is not None else self.interpreter.executor_config.get("default_timeout", 1)

        if not self.execute_pre_wait_actions(event):
            return False

        start_time = time.time()
        # 答えにするのは、直前の動作（問いかけの発話など）を始めた後に届いた観測だけ。
        # それより前の観測は、まだ使われていなくても古い（問いかける前の発話などを答えにしない）
        since = self.interpreter.ctx.last_action_started_at
        if since is None:
            since = self.interpreter.ctx.top_frame.started_at
        self._logger.info(f"Starting wait_for event (timeout: {timeout}s)")

        self.interpreter.update_current_state({
            "processing": {"is_asr_waiting": True}
        })

        # ロボット側に「この観測を待っている」と知らせる（llm_responder は llm-kd のこれを見て返事を作る）
        marker = self._insert_observation_action(event, condition, timeout)
        marker_status, found = "cancelled", None
        try:
            # 待っている間は、条件のイベントを割り込み検知に取らせない
            with self.interpreter.wait_state.waiting("wait_for", event, condition=condition, timeout=timeout) as wait, \
                    self.reserve_observation_events(condition.keys()):
                observations = self._wait_for_observations(event, condition, timeout, start_time, since=since)
                wait.result = "exit" if self.events.exit_requested() else "matched" if observations is not None else "timeout"
            if wait.result == "matched":
                marker_status, found = "done", (observations[0] if observations else None)
            elif wait.result == "timeout":
                marker_status = "timeout"
        finally:
            self._finish_observation_action(marker, marker_status, found)

        self.interpreter.update_current_state({
            "processing": {"is_asr_waiting": False}
        })

        if self.events.exit_requested():
            # exit_condition で打ち切られたら、success / failure のどちらも実行しない
            return True

        if observations is not None:
            self._logger.info("Condition matched in wait_for event")
            if observations:
                self.interpreter.ctx.wait_for_result = observations[0]
                self.events.record_heard_speech(observations[0])
                self.interpreter.ctx.last_observation_time = datetime.datetime.now()

            self._logger.info("Executing success branch for wait_for event")
            return self.events.run_events(event.success)

        self._logger.info("wait_for event timed out, executing failure branch")
        return self.events.run_events(event.failure)

    def _insert_observation_action(self, event: WaitForEvent, condition: Dict[str, Any],
                                   timeout: float) -> Optional[tuple]:
        """
        wait_for を始めたことを、Actions に command: observation（status: waiting）として書く

        旧 RISM の observation イベントと同じ形（option に trigger / timeout / name / orig_name と、
        イベントのほかの項目）。ロボット側の llm_responder は trigger が llm-kd のものを取って返事を作り、
        robot_looking は終わった後の found から話している人を知る。
        書けなくても待つのはやめない。

        Returns:
            (manager, Action の _id)。書かなかったら None
        """
        actor = event.actor
        manager = self.interpreter.action_managers.get(actor, {}).get("observation") if actor else None
        if manager is None:
            return None
        # llm_responder は trigger の先頭の llm-kd を読むので、llm-kd があれば先頭にする
        trigger = sorted(({k: v} for k, v in condition.items()), key=lambda t: "llm-kd" not in t)
        robot = (self.interpreter.config.get("robots") or {}).get(actor, {})
        scenario = self.interpreter.ctx.top_frame.scenario
        option = {k: v for k, v in event.raw.items() if k not in ("success", "failure", "condition")}
        option.update({
            "command": "observation",
            "type": "observation",
            "actor": actor,
            "orig_name": actor,
            "name": robot.get("name_alias") or robot.get("name") or actor,
            "trigger": trigger,
            "timeout": timeout,
            "scenario": scenario.name if scenario is not None else None,
        })
        try:
            ret = manager.insert(option)
            return manager, ret.inserted_id
        except Exception as e:
            self._logger.warning(f"Failed to write the observation action for wait_for: {e}")
            return None

    def _finish_observation_action(self, marker: Optional[tuple], status: str,
                                   found: Optional[Dict[str, Any]]) -> None:
        """wait_for の終わりを、書いた observation の Action に書く（done と found / timeout / cancelled）"""
        if marker is None:
            return
        manager, action_id = marker
        if found is not None:
            found = {k: v for k, v in found.items() if k != RECEIVED_AT_KEY}
        try:
            manager.col.update_one({"_id": action_id}, {"$set": {
                "status": status, "found": found,
                "last_update": datetime.datetime.now(datetime.timezone.utc)}})
        except Exception as e:
            self._logger.warning(f"Failed to update the observation action {action_id}: {e}")

    def _wait_for_observations(
        self,
        event: Event,
        condition: Dict[str, Any],
        timeout: float,
        start_time: float,
        since: Optional[float] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        wait_for の条件に合う観測を待つ

        Args:
            since: この時刻（time.time()）より前に RISM が受け取った観測は使わない。None なら全部使う

        Returns:
            条件に合った観測のリスト（mentioned=true に更新済み）。タイムアウトならNone
        """
        noted_stale = False

        def check_condition(observations):
            nonlocal noted_stale
            fresh = observations if since is None else {
                source: [obs for obs in obs_list if not _received_before(obs, since)]
                for source, obs_list in observations.items()}
            matched = match_any_null_key(condition, fresh)
            if not matched[0] and not noted_stale and since is not None and match_any_null_key(condition, observations)[0]:
                noted_stale = True
                self._logger.info("wait_for: ignoring matching observation(s) received before the previous action started")
            return matched

        while time.time() - start_time < timeout:
            result = self.poll_condition(event, check_condition, timeout, start_time, "wait_for event")
            if result is None:
                break
            if result.matched:
                return result.observations
        return None
