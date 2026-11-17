"""interrupt_manager.py - 割り込み検知・実行を管理するモジュール

ScenarioInterpreterから割り込み関連の責務を分離。
Phase 4責務分離の一環として作成。
"""
import datetime
from typing import Any, Dict, List, Optional
from logging import getLogger

from .constants import ExitCode, NavigationInterruptMode, ResumeAfter
from .execution_context import EventInterrupted
from .navigation_suspender import NavigationSuspender
from .scenario_model import Scenario, ScenarioLike
from .protocols import InterruptRuntime


class InterruptManager:
    """
    割り込み検知・実行を管理するクラス

    責務:
    - 割り込みキューの管理
    - pending割り込みの処理
    - 割り込み実行の制御
    - アクションのキャンセル・待機・復元
    - コンテキストの保存・復元
    """

    def __init__(self, interpreter: InterruptRuntime):
        """
        Args:
            interpreter: ScenarioInterpreter インスタンス
        """
        self.interpreter = interpreter
        self._logger = getLogger(__name__)
        self.navigation = NavigationSuspender(interpreter)

    def display_interrupt_queue_status(self) -> None:
        """
        割り込みキューの状態を可視化表示・保存

        デバッグモードで visualize_interrupt_queue が有効な場合は可視化表示。
        デバッグモードで track_interrupt_queue が有効な場合はMongoDBに保存。
        """
        # キュー状態を取得
        status = self.interpreter.interrupt_queue.get_status()

        self.interpreter.queue_monitor.show(status)

    def process_pending_interrupts(self, important_only: bool = False) -> bool:
        """
        キューに溜まった割り込みを処理（メインスレッド用）

        InterruptDetectorがバックグラウンドで検知・キュー追加した割り込みを
        優先度順に取り出して実行する。

        Args:
            important_only: True なら important / force_interrupt のものだけを実行する（ほかはキューに残す）。
                interruptable: false のイベントの直後に使う

        Returns:
            割り込みが発生して処理した場合True
        """
        queue_size = len(self.interpreter.interrupt_queue)
        if queue_size == 0:
            return False
        where = _is_important if important_only else None
        if where is not None and not self.interpreter.interrupt_queue.has(where):
            return False

        self._logger.info(f"[INTERRUPT_PROCESS] Processing {queue_size} pending interrupt(s) from queue...")

        # キュー状態を可視化表示
        self.display_interrupt_queue_status()

        interrupt_handled = False

        # キューに割り込みがある場合、優先度順に処理
        # 割り込みの実行中は、それより優先度の高いものだけを入れ子で実行する
        # （例: 音声対話の最中に QR コードの割り込みを挟まない）。ほかは終わってから実行する
        running_priority = self._running_priority()
        while not self.interpreter.interrupt_queue.is_empty():
            interrupt_entry = self.interpreter.interrupt_queue.get_next(above=running_priority, where=where)
            if interrupt_entry is None:
                if where is not None:  # important のものは実行し終えた。ほかは次の interruptable なところで実行する
                    break
                self._logger.info(
                    f"[INTERRUPT_PROCESS] Deferring {len(self.interpreter.interrupt_queue)} interrupt(s) "
                    f"until the running subscenario (priority: {running_priority}) finishes"
                )
                break

            self._logger.info(
                f"[INTERRUPT_PROCESS] Executing interrupt: {interrupt_entry.scenario_name} "
                f"(priority: {interrupt_entry.priority_str})"
            )

            # 割り込み実行（マッチした観測データも渡す）
            execution_success = self.execute_interrupt(
                interrupt_entry.scenario_data,
                interrupt_entry.matched_observations
            )
            if execution_success:
                interrupt_handled = True

            # 処理済みの観測IDをpending setから削除
            removed_ids = []
            for obs in (interrupt_entry.matched_observations or []):
                obs_id = str(obs.get("_id", ""))
                if obs_id:
                    self.interpreter.interrupt_queue.remove_pending_observation_id(obs_id)
                    removed_ids.append(obs_id)
            if removed_ids:
                self._logger.info(f"[INTERRUPT_PROCESS] Removed pending IDs: {removed_ids}")

            # 削除後のpending setの状態を確認
            remaining_pending = len(self.interpreter.interrupt_queue.pending_observation_ids())
            self._logger.info(f"[INTERRUPT_PROCESS] Remaining pending IDs count: {remaining_pending}")

            # 実行履歴を記録（MongoDBトラッキング有効時）
            self.interpreter.queue_monitor.record_execution(interrupt_entry, execution_success)

            if self.interpreter.ctx.terminate_main_scenario:
                self._drop_queued_after_main_ended(interrupt_entry.scenario_name)
                break

        return interrupt_handled

    def _drop_queued_after_main_ended(self, ended_by: str) -> None:
        """
        割り込みがメインシナリオを終えた（terminate / exit_main / redirect）ので、キューに残っている割り込みを捨てる

        残っているのは、その割り込みの間に見送ったもので、終える前の状況に合わせたもの
        （例: バッテリ補充の間に見つけた人への挨拶や手を挙げる割り込み）。実行すると次のシナリオ
        （充電中のつぶやきなど）が始まるのが遅れ、その間に同じ割り込み（low_battery）がまた始まってしまう。
        """
        queue = self.interpreter.interrupt_queue
        dropped = queue.scenario_names()
        if not dropped:
            return
        queue.clear()
        self._logger.info(
            f"[INTERRUPT_PROCESS] Main scenario ended by '{ended_by}': dropped {len(dropped)} queued interrupt(s) {dropped}"
        )

    def _running_priority(self):
        """実行中の割り込みサブシナリオの優先度（入れ子なら最も高いもの）。なければ None"""
        running = self.interpreter.ctx.interrupt_frames
        if not running:
            return None
        return max(f.scenario.priority for f in running)

    def _resume_mode(self, subscenario: Scenario) -> ResumeAfter:
        """サブシナリオが終わった後の戻り方（resume_after、既定 resume）"""
        resume_after = subscenario.resume_after
        if resume_after is None and "return" in subscenario.raw:
            # 古い書き方の return（真偽）も読むが、resume_after に書き換えてもらう
            self._logger.warning(
                f"Subscenario '{subscenario.name}' uses deprecated 'return'; use 'resume_after' instead"
            )
            resume_after = subscenario.raw.get("return")
        if resume_after is None:
            return ResumeAfter.RESUME
        if isinstance(resume_after, bool):
            return ResumeAfter.RESUME if resume_after else ResumeAfter.TERMINATE
        try:
            return ResumeAfter(resume_after)
        except ValueError:
            self._logger.warning(f"Invalid resume_after value: {resume_after}, defaulting to 'resume'")
            return ResumeAfter.RESUME

    def execute_interrupt(self, subscenario: ScenarioLike,
                          matched_observations: List[Dict[str, Any]] = None) -> bool:
        """
        割り込みサブシナリオを実行

        実行中は同じサブシナリオの割り込みを検知しても無視されるよう、
        実行中のシナリオとして登録する。

        Args:
            subscenario: サブシナリオ（DB の文書でもよい）
            matched_observations: トリガーとなった観測データのリスト

        Returns:
            成功した場合True
        """
        subscenario = Scenario.coerce(subscenario)
        scenario_id = subscenario.id_str or "unknown"
        self.interpreter.interrupt_queue.mark_scenario_active(scenario_id)
        # 割り込みのフレームを積む（割り込み検知は、実行中のサブシナリオの ignore_interruptions なども見る）
        frame = self.interpreter.ctx.push_interrupt(subscenario)
        try:
            return self._execute_interrupt(subscenario, matched_observations)
        finally:
            self.interpreter.ctx.pop_interrupt(frame)
            self.interpreter.interrupt_queue.mark_scenario_inactive(scenario_id)

    def _execute_interrupt(self, subscenario: Scenario,
                           matched_observations: List[Dict[str, Any]] = None) -> bool:
        """
        割り込みサブシナリオを実行（本体）

        きっかけの観測を覚える → 割り込みに入る → 移動を止める → イベントを実行 → 割り込みを出る
        → 終わり方（exit_code / resume_after）に応じてメインシナリオに戻る。

        Args:
            subscenario: サブシナリオ
            matched_observations: トリガーとなった観測データのリスト

        Returns:
            成功した場合True
        """
        self._remember_trigger(matched_observations)
        resume_mode = self._resume_mode(subscenario)
        self._logger.info(f"Interrupt resume mode: {resume_mode}")

        frame = self.interpreter.ctx.top_frame
        self._enter(subscenario)
        # 最初の発話は、移動を止める（stop の処理を待つ）間に作り始める
        self.interpreter.prefetch_manager.start_first_utterance_prefetch(subscenario.events)
        frame.suspended_navigations.update(self._hold_navigation(subscenario))
        success = self._run_events(subscenario)  # suspend_navigation イベントでも frame.suspended_navigations に入る
        exit_code, exit_data = self._leave()
        self._return_to_main(subscenario, resume_mode, exit_code, exit_data, frame.suspended_navigations)
        return success

    def suspend_navigation(self) -> None:
        """
        実行中の移動をその場で止める（suspend_navigation イベント）

        割り込みの中なら止めた移動を覚えておき、割り込みが終わったら送り直す
        （navigation_interrupt_mode: parallel で始めて、途中で止めたいとき）。割り込みの外では止めるだけ。
        """
        frame = self.interpreter.ctx.top_frame
        if frame.kind != "interrupt":
            self._logger.warning("suspend_navigation outside an interrupt: stopping without resuming later")
            self.navigation.suspend_active_navigations()
            return
        suspended = frame.suspended_navigations
        for actor, info in self.navigation.suspend_active_navigations().items():
            suspended.setdefault(actor, info)
        self._logger.info(f"Suspended navigation by event; will resume after the interrupt: {list(suspended)}")

    def _remember_trigger(self, matched_observations: Optional[List[Dict[str, Any]]]) -> None:
        """きっかけの観測を覚える（{triggered[...]} の置き換え用。contents の中身は上の階層にも出す）"""
        observation = matched_observations[0] if matched_observations else {}
        if isinstance(observation.get("contents"), dict):
            observation = {**observation, **observation["contents"]}
        self.interpreter.ctx.triggered_observation = observation

    def _enter(self, subscenario: Scenario) -> None:
        """割り込みに入る: 履歴を始め、状態を interrupted にする（終わり方は、新しいフレームが空の状態で持つ）"""
        ctx = self.interpreter.ctx
        # 先読みは消さない（割り込みの前に作っておいたメインシナリオの次の発話は、戻ったあとに状況が同じなら使える）

        # 割り込みのフレームの履歴を始める（深さはフレームの数で決まる）。親は割り込まれたシナリオ（1つ外側のフレーム）の履歴
        outer = ctx.outer_frame()
        ctx.current_scenario_history_id = self.interpreter.scenario_manager.history.start_scenario_in_history(
            scenario_id=subscenario.id_str,
            scenario_name=subscenario.name,
            is_interruption=True,
            parent_history_id=outer.history_id if outer is not None else None,
            depth=ctx.interrupt_depth,
            robot=self.interpreter.robot_name_for_history
        )
        self.interpreter.update_current_state({
            "interpreter": {"status": "interrupted"},
            "scenario": {"status": "interrupted"},
            "interrupt": {
                "is_interrupted": True,
                "depth": ctx.interrupt_depth,
                "subscenario_id": subscenario.id_str,
                "subscenario_name": subscenario.name
            }
        })

    def _hold_navigation(self, subscenario: Scenario) -> Dict[str, Any]:
        """
        navigation_interrupt_mode（なければ important かどうかなどで決める）に従って、実行中の移動を扱う

        Returns:
            止めた移動（割り込みが終わったら送り直す）。suspend_and_resume で止めたときだけ中身がある
        """
        mode = subscenario.navigation_interrupt_mode
        if mode is None:
            mode = self.navigation.default_mode_for(subscenario)
        if mode == NavigationInterruptMode.WAIT:
            self._logger.info("Navigation interrupt mode: wait_completion")
            self.navigation.wait_for_navigations_completion(subscenario.navigation_wait_timeout)
            return {}
        if mode == NavigationInterruptMode.SUSPEND:
            self._logger.info("Navigation interrupt mode: suspend_and_resume")
            return self.navigation.suspend_active_navigations()
        self._logger.info("Navigation interrupt mode: parallel")
        return {}

    def _run_events(self, subscenario: Scenario) -> bool:
        """サブシナリオのイベントを実行する。exit_condition で打ち切ったときは exit_events も実行する"""
        ctx = self.interpreter.ctx
        events = subscenario.events
        self._logger.info(f"Executing subscenario: {subscenario.name} ({len(events)} events)")
        success = True
        with ctx.waits_ahead(events) as reserve_next_waits:
            event_idx = 0
            while event_idx < len(events):
                reserve_next_waits(event_idx)
                try:
                    executed = self.interpreter.event_processor.execute_event(events[event_idx])
                except EventInterrupted as interrupted:
                    # 中の割り込みの resume_after: restart ならこのイベントをやり直し、next_event なら次へ
                    if interrupted.mode != ResumeAfter.RESTART:
                        event_idx += 1
                    continue
                if not executed:
                    self._logger.error(f"Subscenario event failed at index {event_idx}")
                    success = False
                    break
                if ctx.exit_requested is True:
                    self._logger.info(f"Subscenario exit requested at index {event_idx}, skipping remaining events")
                    break
                event_idx += 1
        if ctx.exit_condition_met is True:
            self.interpreter.event_processor.run_exit_events(subscenario)
        # 打ち切りの印はこの割り込みのフレームにあるので、外側のシナリオは打ち切られない
        return success

    def _leave(self):
        """
        割り込みを出る: 履歴を終え、深さを戻し、中断したシナリオの状態を戻す

        Returns:
            (exit_code, exit_data)。scenario_exit がなければ return
        """
        ctx = self.interpreter.ctx
        if ctx.scenario_exit_status is None:
            ctx.scenario_exit_status = {
                "exit_code": ExitCode.RETURN,
                "exit_data": {},
                "timestamp": datetime.datetime.now().isoformat()
            }
        exit_code = ctx.scenario_exit_status.get("exit_code", ExitCode.RETURN)
        exit_data = ctx.scenario_exit_status.get("exit_data", {}) or {}

        if ctx.current_scenario_history_id:
            self.interpreter.scenario_manager.history.finish_scenario_in_history(
                ctx.current_scenario_history_id,
                exit_status=ctx.scenario_exit_status
            )
        # 割り込みを出る（フレームは execute_interrupt の最後で外す。ここから先の深さと履歴の ID は外側のもの）
        ctx.top_frame.left = True
        return exit_code, exit_data

    def _return_to_main(self, subscenario: Scenario, resume_mode: ResumeAfter, exit_code: Any,
                        exit_data: Dict[str, Any], suspended_nav_data: Dict[str, Any]) -> None:
        """終わり方に応じて、メインシナリオを終えるか、続きに戻る（止めた移動も送り直す）"""
        ctx = self.interpreter.ctx
        if exit_code == ExitCode.REDIRECT:
            next_scenario_id = exit_data.get("next_scenario")
            if next_scenario_id:
                self._logger.info(f"Interrupt exit: redirect to {next_scenario_id} - ending main scenario")
                self._end_main_scenario(redirect_scenario_id=next_scenario_id)
            else:
                self._logger.error("Redirect exit_code requires next_scenario in exit_data, returning to main scenario")
            return
        if exit_code == ExitCode.EXIT_MAIN:
            self._logger.info("Interrupt exit: exit_main - ending main scenario")
            self._end_main_scenario()
            return
        if exit_code != ExitCode.RETURN:
            self._logger.warning(f"Unexpected exit_code for interruption: {exit_code}, treating as return")

        if resume_mode == ResumeAfter.TERMINATE:
            # メインシナリオを終え、サブシナリオの next_scenarios から次を選ぶ
            self._logger.info("Resume mode: terminate - ending main scenario")
            self._end_main_scenario(next_scenarios=subscenario.next_scenarios)
        elif resume_mode in (ResumeAfter.NEXT_EVENT, ResumeAfter.RESTART):
            # 割り込まれたシナリオ（フレーム）に印を付ける。待っている処理がイベントを抜け、
            # そのシナリオのイベントの並びが、次へ進む（next_event）かやり直す（restart）
            ctx.top_frame.resume_mode = resume_mode
            self._logger.info(f"Resume mode: {resume_mode} - leaving the interrupted event")
        else:
            self._logger.info("Resume mode: resume - continuing from current position")

        # 止めた移動を送り直す（メインシナリオを終えるときは送らない）
        if suspended_nav_data and not ctx.terminate_main_scenario:
            self.navigation.resume_interrupted_navigations(suspended_nav_data)

        if ctx.current_scenario:
            status = "running" if ctx.is_interrupted else "active"
            self.interpreter.update_current_state({
                "interpreter": {"status": status},
                "scenario": {"status": status},
                "interrupt": {"is_interrupted": ctx.is_interrupted, "depth": ctx.interrupt_depth}
            })

    def _end_main_scenario(self, redirect_scenario_id: str = None,
                           next_scenarios: List[Any] = None) -> None:
        """
        割り込み後にメインシナリオへ戻らず終了させる

        次シナリオは redirect_scenario_id、next_scenarios の順で決定し、
        どちらもなければ run_scenario_chain 側で条件マッチングにより選択される。

        Args:
            redirect_scenario_id: リダイレクト先シナリオID
            next_scenarios: サブシナリオのnext_scenarios
        """
        self.interpreter.ctx.terminate_main_scenario = True
        # 割り込みの入れ子の中からでも、メインシナリオの終わり方として書く
        self.interpreter.ctx.main_frame.exit_status = {
            "exit_code": ExitCode.SUCCESS,
            "exit_data": {},
            "timestamp": datetime.datetime.now().isoformat()
        }

        if not redirect_scenario_id and next_scenarios:
            redirect_scenario_id = self.interpreter.scenario_manager.selector.select_next_scenario(next_scenarios)
            if not redirect_scenario_id:
                self._logger.warning(
                    f"No active scenario in subscenario next_scenarios {next_scenarios}, "
                    f"falling back to condition matching"
                )

        if redirect_scenario_id:
            self.interpreter.ctx.redirect_scenario_id = str(redirect_scenario_id)
            self._logger.info(f"Next scenario after interrupt: {redirect_scenario_id}")


def _is_important(entry) -> bool:
    """important / force_interrupt の割り込みか（interruptable: false のイベントの直後でも実行する）"""
    return Scenario.coerce(entry.scenario_data).always_interrupts
