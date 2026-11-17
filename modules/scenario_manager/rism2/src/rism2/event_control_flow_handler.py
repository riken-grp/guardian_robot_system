"""event_control_flow_handler.py - 制御フローイベント（repeat / random / shuffle / if / until）の処理"""
import time
from logging import getLogger
from typing import TYPE_CHECKING

from .condition_checker import first_with_event, is_match_condition
from .event_model import EventLike, IfEvent, RandomEvent, RepeatEvent, ShuffleEvent, UntilEvent

if TYPE_CHECKING:
    from .event_processor import EventProcessor


class ControlFlowHandler:
    """repeat / random / shuffle / if / until"""

    def __init__(self, events: "EventProcessor") -> None:
        self.events = events
        self.interpreter = events.interpreter
        self._logger = getLogger(__name__)

    def execute_repeat_event(self, event: EventLike) -> bool:
        """repeatイベントを実行"""
        event = RepeatEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        self._logger.info(f"Executing repeat event: {event.times} times")

        # 次の回の先頭も「次のイベント」になるので、全回を並べたものについて予約する
        # repeat の中は回ごとに先読みする（start_repeat_prefetch）ので、並びの次の先読みはしない
        with self.interpreter.ctx.waits_ahead(list(event.subevents) * event.times, prefetch=False) as reserve_next_waits:
            for i in range(event.times):
                for j, subevent in enumerate(event.subevents):
                    current = subevent.with_repeat(i + 1, event.variable, j)
                    reserve_next_waits(i * len(event.subevents) + j)

                    # 次のイテレーションの同じsubeventをprefetch
                    if i < event.times - 1 and current.type == "action":
                        self.interpreter.prefetch_manager.start_repeat_prefetch(
                            subevent.with_repeat(i + 2, event.variable, j))

                    if not self.events.execute_event(current):
                        return False
                    if self.events.exit_requested():
                        return True

                    if self.interpreter.process_pending_interrupts(important_only=not current.interruptable):
                        self._logger.info("Interrupt handled in repeat loop, resuming")
                        if self.events.exit_requested():  # 割り込みがメインシナリオを終わらせた
                            return True

        return True

    def execute_random_event(self, event: EventLike) -> bool:
        """randomイベントを実行"""
        event = RandomEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        choices = event.choices
        # 次のイベントの先読みで候補を先に選んでいれば、その候補を実行する（先読みした発話を使えるように）
        index = self.interpreter.ctx.random_picks.pop(id(event.raw), None)
        if index is None or index >= len(choices):
            index = event.pick_index()
        if index is None:
            weights = event.weights
            self._logger.error(f"Cannot pick a random choice: {len(choices)} choices, weights {weights}")
            return False
        self._logger.info(f"Random event selected choice {index + 1}/{len(choices)}")

        with self.interpreter.ctx.waits_ahead(choices[index]) as reserve_next_waits:
            for idx, subevent in enumerate(choices[index]):
                reserve_next_waits(idx)
                if not self.events.execute_event(subevent):
                    return False
                if self.events.exit_requested():
                    return True

                if self.interpreter.process_pending_interrupts(important_only=not subevent.interruptable):
                    self._logger.info("Interrupt handled in random event, resuming")
                    if self.events.exit_requested():  # 割り込みがメインシナリオを終わらせた
                        return True

        return True

    def execute_shuffle_event(self, event: EventLike) -> bool:
        """shuffle イベントを実行（choices を、シャッフルした順番で全部実行する）"""
        event = ShuffleEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        choices = event.choices
        # 次のイベントの先読みで順番を先に決めていれば、その順番で実行する（先読みした発話を使えるように）
        order = self.interpreter.ctx.shuffle_orders.pop(id(event.raw), None)
        if order is None or sorted(order) != list(range(len(choices))):
            order = event.pick_order()
        self._logger.info(f"Shuffle event order: {[i + 1 for i in order]} of {len(choices)} choices")

        # 並べた全部を1つの並びとして実行する（次の候補の先頭も「次のイベント」として先読み・予約する）
        events = [subevent for index in order for subevent in choices[index]]
        with self.interpreter.ctx.waits_ahead(events) as reserve_next_waits:
            for idx, subevent in enumerate(events):
                reserve_next_waits(idx)
                if not self.events.execute_event(subevent):
                    return False
                if self.events.exit_requested():
                    return True

                if self.interpreter.process_pending_interrupts(important_only=not subevent.interruptable):
                    self._logger.info("Interrupt handled in shuffle event, resuming")
                    if self.events.exit_requested():  # 割り込みがメインシナリオを終わらせた
                        return True

        return True

    def execute_if_event(self, event: EventLike) -> bool:
        """ifイベントを実行（条件分岐、timeout対応）"""
        event = IfEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        condition = self.events.resolve_condition(event.condition)
        timeout = event.timeout if event.timeout is not None else self.interpreter.executor_config.get("default_timeout", 1)

        if not self.events.observation.execute_pre_wait_actions(event):
            return False

        event_keys = list(condition.keys())
        start_time = time.time()

        self._logger.info(f"Waiting for condition (timeout: {timeout}s)")

        # 条件どおりの観測か、条件のイベントだが中身が違う観測が来たら待ち終わる
        def check_condition(observations):
            match, matched = is_match_condition(condition, observations)
            if match:
                return True, matched
            obs = first_with_event(observations, event_keys)
            return (True, [obs]) if obs is not None else (False, [])

        # 待っている間は、条件のイベントを割り込み検知に取らせない（wait_for と同じ）
        self.interpreter.update_current_state({"processing": {"is_asr_waiting": True}})
        with self.interpreter.wait_state.waiting("if", event, condition=condition, timeout=timeout) as wait, \
                self.events.observation.reserve_observation_events(event_keys):
            got_obs = self._wait_if_condition(event, check_condition, timeout, start_time)
            is_match = bool(got_obs) and bool(is_match_condition(condition, {"tBlackBoard": got_obs})[0])
            has_event = got_obs is not None and not is_match
            wait.result = ("exit" if self.events.exit_requested() else "matched" if is_match
                           else "unmatched" if has_event else "timeout")
        self.interpreter.update_current_state({"processing": {"is_asr_waiting": False}})
        if self.events.exit_requested():
            # exit_condition で打ち切られたら、どの分岐も実行しない
            return True

        self._logger.info(f"Condition check finished (is_match={is_match}, has_event={has_event})")

        if got_obs:
            # 観測は poll_condition で使用済みにしてある（false でも、後続の待ちで同じ観測に反応しないように）
            self.interpreter.ctx.wait_for_result = got_obs[0]
            self.events.record_heard_speech(got_obs[0])

        if is_match:
            self._logger.info("Condition matched, executing 'true' branch")
            return self.events.run_events(event.true)
        if has_event:
            self._logger.info("Event found but condition not matched, executing 'false' branch")
            return self.events.run_events(event.false)
        self._logger.info("Event not found in observations, executing 'failure' branch")
        return self.events.run_events(event.failure)

    def _wait_if_condition(self, event, check_condition, timeout, start_time):
        """if イベントの条件を待つ。来た観測のリストを返し、タイムアウトなら None"""
        while time.time() - start_time < timeout:
            result = self.events.observation.poll_condition(event, check_condition, timeout, start_time, "if event wait")
            if result is None:
                break
            if result.matched:
                return [obs for obs in result.observations if obs]
        return None

    def execute_until_event(self, event: EventLike) -> bool:
        """untilイベントを実行（条件付きループ）"""
        event = UntilEvent.coerce(event)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        condition = self.events.resolve_condition(event.condition)
        loop_timeout = event.loop_timeout if event.loop_timeout is not None else \
            self.interpreter.executor_config.get("default_timeout", 1)

        if not self.events.observation.execute_pre_wait_actions(event):
            return False

        start_time = time.time()
        self._logger.info(f"Starting until loop (timeout: {loop_timeout}s)")

        def check_condition(observations):
            return is_match_condition(condition, observations)

        # ループ中も条件のイベントは割り込み検知に取らせない（ループ内のイベント実行中も含む）
        self.interpreter.update_current_state({"processing": {"is_asr_waiting": True}})
        with self.interpreter.wait_state.waiting("until", event, condition=condition, timeout=loop_timeout) as wait, \
                self.events.observation.reserve_observation_events(condition.keys()):
            matched = self._run_until_loop(event, check_condition, loop_timeout, event.loop, start_time)
            wait.result = ("failed" if matched is None else "exit" if self.events.exit_requested()
                           else "matched" if matched else "timeout")
        self.interpreter.update_current_state({"processing": {"is_asr_waiting": False}})
        if matched is None:
            return False
        if matched:
            return True

        self._logger.info("Until loop timed out, executing failure branch")
        return self.events.run_events(event.failure)

    def _run_until_loop(self, event, check_condition, loop_timeout, loop_events, start_time):
        """until のループ本体。条件成立で True、タイムアウトで False、イベント失敗で None"""
        while time.time() - start_time < loop_timeout:
            result = self.events.observation.poll_condition(event, check_condition, loop_timeout, start_time, "until loop")
            if result is None:
                # 打ち切りなら条件成立と同じく抜ける（failure は実行しない）
                return True if self.events.exit_requested() else False

            if result.matched:
                self._logger.info("Condition matched, exiting until loop")
                if result.observations:
                    self.interpreter.ctx.wait_for_result = result.observations[0]
                    self.events.record_heard_speech(result.observations[0])
                return True

            for loop_event in loop_events:
                if not self.events.execute_event(loop_event):
                    return None
                if self.events.exit_requested():
                    return True
        return False
