"""event_action_handler.py - action イベントの処理

action イベント（speak / gesture / eye / navigation / ros_command）の
挿入・完了待ち・リトライと、そのためのオプション処理。
"""
import datetime
import time
from dataclasses import dataclass
from logging import getLogger
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

from bson import ObjectId

from .constants import ACTION_CANCELLED_STATUSES
from .action_change_notifier import notifier_for
from .navigation_query import get_action_status, get_collection_and_actor
from .event_model import ActionEvent, Event, EventLike

if TYPE_CHECKING:
    from .event_processor import EventProcessor


def is_dock(kind: str, option: Any) -> bool:
    """充電ステーションに入る navigation（option の dock が true）か"""
    return kind == "navigation" and isinstance(option, dict) and option.get("dock") is True


@dataclass
class SentAction:
    """ロボットに送った動作1つ（完了待ち・リトライ・送り直しに使う）"""
    kind: str                       # utterance / gesture / navigation / eye / ros_command
    action_id: Any
    manager: Any
    data: Any                       # 送った内容（リトライで同じものを送る）
    option: Dict[str, Any]          # 処理後のオプション（navigation の送り直しに使う）
    retry_config: Dict[str, Any]
    timeout_config: Dict[str, Any]


class ActionHandler:
    """action イベント（ロボットへのアクションの挿入と完了待ち）"""

    def __init__(self, events: "EventProcessor") -> None:
        self.events = events
        self.interpreter = events.interpreter
        self._logger = getLogger(__name__)

    # 完了を待たない動作
    NO_WAIT_COMMANDS = ("eye",)

    def execute_action_event(self, event: EventLike) -> bool:
        """アクションイベントを実行（pyindyベース）"""
        event = ActionEvent.coerce(event)
        actor = event.actor
        if not actor:
            self._logger.warning("No actor specified in event, skipping this event")
            return True

        if actor not in self.interpreter.action_managers:
            self._logger.warning(f"Actor '{actor}' not found (no robot with this name), skipping this event")
            return True

        # wait_for が、この動作より前に届いた観測を答えにしないよう、始めた時刻を覚えておく
        self.interpreter.ctx.last_action_started_at = time.time()

        # type: "generate"の場合は特別処理
        if event.generates:
            return self.events.generation.execute_generate_event(actor, event)

        managers = self.interpreter.action_managers[actor]

        # 各コマンドを個別に挿入
        insertion_start_time = time.time()
        sent, speak_text = self._insert_actions(event, actor, managers)

        if not sent:
            self._logger.warning(f"No commands found in action event for actor {actor}")
            return True

        insertion_time = time.time() - insertion_start_time
        self._logger.info(f"Action insertion completed in {insertion_time:.3f}s ({len(sent)} action(s))")

        # 話し始めたら会話履歴に入れ、それから次の発話を先読みする（話している間に作る）。
        # 履歴に入れる前に先読みすると、LLM が今の発話を知らずに作り、同じ書き出しを続けてしまう
        if speak_text:
            self.events.add_to_conversation_history(actor, speak_text)
        self.interpreter.prefetch_manager.try_start_next_event_prefetch()

        if speak_text is not None:
            self.interpreter.update_current_state({
                "processing": {"is_tts_processing": True}
            })

        self._wait_for_all(event, actor, sent)

        if speak_text is not None:
            self.interpreter.update_current_state({
                "processing": {"is_tts_processing": False}
            })

        if speak_text:
            self.interpreter.ctx.last_utterance_time = datetime.datetime.now()  # 話し終えた時刻

        self.interpreter.scenario_manager.history.add_to_finished_events(event.to_dict())

        return True

    def _wait_for_all(self, event: ActionEvent, actor: str, sent: List[SentAction]) -> None:
        """
        送った動作の完了を順に待ち、結果をログに出す

        目の表示は送れば切り替わるので完了を待たない（ロボットの完了報告が10秒以上遅れることがある）。
        """
        max_timeout = self.interpreter.executor_config.get("default_timeout", 30)
        not_waited = [a.kind for a in sent if a.kind in self.NO_WAIT_COMMANDS]
        waited = [a for a in sent if a.kind not in self.NO_WAIT_COMMANDS]
        if not_waited:
            self._logger.info(f"Not waiting for {', '.join(not_waited)} to complete")
        self._logger.info(f"Waiting for {len(waited)} action(s) to complete")

        started = time.time()
        actions = [{"command": a.kind, "action_id": str(a.action_id)} for a in waited]
        # 待つ時間は、それぞれの動作の時間切れの長い方（移動は default_navigation_timeout など）
        longest = max((self._action_timeout(a, max_timeout) for a in waited), default=max_timeout)
        with self.interpreter.wait_state.waiting("action", event, timeout=longest, actions=actions) as wait:
            failures = [f for f in (self._wait_for_action(event, actor, max_timeout, a) for a in waited) if f is not None]
            wait.result = ("done" if not failures
                           else "timeout" if any(reason.startswith("timed out") for _, _, reason in failures)
                           else "failed")
        elapsed = time.time() - started
        if not failures:
            self._logger.info(f"All {len(waited)} action(s) completed successfully (total time: {elapsed:.2f}s)")
            return
        self._logger.warning(
            f"Action execution completed: {len(waited) - len(failures)}/{len(waited)} succeeded, "
            f"{len(failures)} failed (total time: {elapsed:.2f}s)"
        )
        for kind, action_id, reason in failures:
            self._logger.warning(f"  - {kind}: {action_id} ({reason})")

    def _insert_actions(self, event: ActionEvent, actor: str,
                        managers: Dict[str, Any]) -> Tuple[List[SentAction], Optional[str]]:
        """
        action イベントの各動作（speak / gesture / navigation / eye / ros_command）をロボットに送る

        Returns:
            (送った動作のリスト, 発話した文。発話を送らなかったら None)
        """
        if event.command_names:
            self._logger.info(f"Inserting actions for {actor}: {', '.join(event.command_names)}")
        sent, speak_text = [], None
        for kind, data, option, describe in self._actions_to_send(event, actor):
            action = self._send(actor, managers, kind, data, option, describe)
            if action is None:
                continue
            sent.append(action)
            if kind == "utterance":
                speak_text = data["text"]
            elif kind == "navigation":
                self.interpreter.ctx.save_navigation(actor, {
                    "type": event.navigation.get("type", "normal"),
                    "option": option,
                    "action_id": str(action.action_id)
                })
                self.interpreter.update_current_state({"processing": {"is_navigating": True}})
        return sent, speak_text

    def _actions_to_send(self, event: ActionEvent,
                         actor: str) -> Iterator[Tuple[str, Any, Dict[str, Any], Callable[[Any], str]]]:
        """
        送る動作を、(種類, 送る内容, 処理後のオプション, 送ったときのログ) の形で順に出す

        処理後のオプションは、プレースホルダーの置き換えなどをしたもの。リトライと timeout の設定もここから読む。
        """
        if event.speak is not None:
            option = self.process_command_option("speak", event.speak, event)
            utterance = {"text": option.get("text", "")}
            for key in ("file", "english"):
                if key in option:
                    utterance[key] = option[key]
            if not utterance["text"].strip() and "file" not in utterance:
                # 生成した発話を取りやめたとき（繰り返しや知らない名前）は文が空になる。ロボットには送らない
                self._logger.info(f"Skipping empty utterance for {actor}")
            else:
                yield "utterance", utterance, option, lambda _: f"Utterance inserted: {utterance['text'][:50]}..."

        if event.gesture is not None:
            option = self.process_command_option("gesture", event.gesture, event)
            gesture = self.gesture_data(option)
            yield "gesture", gesture, option, lambda _: f"Gesture inserted: {gesture.get('gesture', 'unknown')}"

        if event.navigation is not None:
            option = self.process_command_option("navigation", event.navigation, event)
            target = (option.get("goal") or option.get("destination") or option.get("navigation")
                      or next((f"{k} {option[k]}" for k in ("rotate", "move") if k in option), None)
                      or ("dock" if option.get("dock") else "unknown"))
            yield "navigation", option, option, lambda action_id: f"Navigation inserted: {target} (action_id: {action_id})"

        if event.eye is not None:
            eye = event.eye
            yield "eye", eye, eye.get("option", {}), lambda _: f"Eye inserted: {eye.get('image', 'unknown')}"

        if event.ros_command is not None:
            ros = event.ros_command
            yield "ros_command", ros, ros.get("option", {}), lambda _: f"ROS command inserted: {ros.get('topic', ros.get('command', 'unknown'))} {ros.get('data', '')!r}"

    @staticmethod
    def gesture_data(option: Dict[str, Any]) -> Dict[str, Any]:
        """gesture のオプションを、pyindy の GestureManager に渡す形にする（command → gesture、type の既定は normal）"""
        gesture = dict(option)
        if "command" in gesture:
            gesture["gesture"] = gesture.pop("command")
        gesture.setdefault("type", "normal")
        return gesture

    def _send(self, actor: str, managers: Dict[str, Any], kind: str, data: Any, option: Dict[str, Any],
              describe: Callable[[Any], str]) -> Optional[SentAction]:
        """動作1つを Actions に書く。書けなかったら None"""
        manager = managers.get(kind)
        try:
            ret = manager.insert(data)
        except Exception as e:
            self._logger.error(f"Exception inserting {kind} action for {actor}: {e}", exc_info=True)
            return None
        if not ret or not hasattr(ret, "inserted_id"):
            self._logger.error(f"Failed to insert {kind} action for {actor}: insert returned {ret}")
            return None
        self._logger.info(describe(ret.inserted_id))
        return SentAction(kind, ret.inserted_id, manager, data, option,
                          self.extract_retry_config(option), self._extract_timeout_config(option))

    def _action_timeout(self, action: SentAction, default: float) -> float:
        """動作1つの完了を待つ秒数（イベントの timeout、なければ executor の default_{種類}_timeout、なければ default）"""
        config = self.interpreter.executor_config
        if action.timeout_config.get("timeout"):
            return action.timeout_config["timeout"]
        if is_dock(action.kind, action.option):
            # ドッキングは充電が始まるまで（ロボットの navigate_to_charge）待つので、ほかの移動より長い
            return config.get("default_dock_timeout", 200)
        return config.get(f"default_{action.kind}_timeout", default)

    def _wait_for_action(self, event: ActionEvent, actor: str, max_timeout: float, action: SentAction):
        """
        送った動作1つの完了を待つ（リトライ、割り込みで再開したnaviの追跡、タイムアウト時の代わりの動作も含む）

        Returns:
            失敗したら (種類, action_id, 理由)。成功（または代わりの動作を実行）したら None
        """
        command_type, action_id, manager = action.kind, action.action_id, action.manager
        retry_config, timeout_config = action.retry_config, action.timeout_config
        timeout = self._action_timeout(action, max_timeout)
        retry_count = retry_config.get("retry", 0)
        retry_delay = retry_config.get("retry_delay", 1.0)

        outcome = self.FAILED
        for attempt in range(retry_count + 1):
            if attempt > 0:
                self._logger.info(f"Retrying {command_type} action (attempt {attempt}/{retry_count})...")
                time.sleep(retry_delay)
                action_id = self._reinsert(command_type, manager, action.data, attempt)
                if action_id is None:
                    continue

            outcome, action_id = self._watch_action(event, actor, command_type, action_id, manager,
                                                    timeout, action.option, attempt)
            if outcome == self.SUCCEEDED:
                return None
            will_retry = "" if attempt == retry_count else ", will retry"
            if outcome == self.TIMED_OUT:
                self._logger.warning(f"{command_type} action timed out after {timeout}s: {action_id}{will_retry}")
                self._cancel_action(command_type, manager, action_id)
                self._forget_navigation(command_type, actor, action_id)

        self._forget_navigation(command_type, actor, action_id)
        if outcome == self.TIMED_OUT and self._run_timeout_fallback(event, actor, command_type, timeout_config):
            return None
        return (command_type, action_id, "timed out after retries" if outcome == self.TIMED_OUT else "failed after retries")

    # _watch_action の結果
    SUCCEEDED, FAILED, TIMED_OUT = "succeeded", "failed", "timed_out"

    def _watch_action(self, event: ActionEvent, actor: str, command_type: str, action_id: Any, manager: Any,
                      timeout: float, option: Any, attempt: int):
        """
        送った動作1つの状態を timeout 秒まで見る

        done / ignored / cancelled なら成功、failed / error なら失敗。navigation は、割り込みで
        再開されたものを追い、送ってすぐ失敗したものは少し待って送り直す。

        Returns:
            (SUCCEEDED / FAILED / TIMED_OUT, 最後に見ていた action_id)
        """
        is_navigation = command_type == "navigation"
        dock = is_dock(command_type, option)
        start_time = sent_at = time.time()
        resends = 0
        # 状態が変わったら変更通知ですぐ読み直す（使えなければ 0.1 秒ごと）
        notifier = notifier_for(get_collection_and_actor(manager)[0])
        with notifier.watching(action_id) as changed:
            while time.time() - start_time < timeout:
                if event.interruptable and self.interpreter.process_pending_interrupts():
                    self._logger.info("Interrupt handled during action wait, resuming")
                    # stop で止めたnaviをロボットが done と報告することがあるので、status より先に再開を見る
                    if is_navigation and (resumed_id := self._follow_resumed_navigation(actor, action_id)):
                        notifier.follow(action_id, resumed_id)
                        action_id, start_time, sent_at, resends = resumed_id, time.time(), time.time(), 0

                try:
                    status = get_action_status(manager, action_id)
                except Exception as e:
                    self._logger.error(f"Error checking action status for {command_type} ({action_id}): {e}", exc_info=True)
                    return self.FAILED, action_id

                if status == "ignored" and dock:
                    # ドッキングできていないのに成功にしない（dock を知らない古いロボットは ignored にする）
                    self._logger.error(f"dock action ignored by the robot: {action_id}")
                    return self.FAILED, action_id

                if status in ("done", "ignored"):
                    suffix = f" on retry {attempt}" if attempt > 0 else ""
                    state = "completed" if status == "done" else "ignored (treated as complete)"
                    self._logger.info(f"{command_type} action {state}{suffix}: {action_id}")
                    self._forget_navigation(command_type, actor, action_id)
                    return self.SUCCEEDED, action_id

                if status in ACTION_CANCELLED_STATUSES or status in ("error", "failed"):
                    # 割り込みで中断されたnaviは、再開したnaviの完了を待つ（stop で failed になることもある）
                    if is_navigation and (resumed_id := self._follow_resumed_navigation(actor, action_id)):
                        notifier.follow(action_id, resumed_id)
                        action_id, start_time, sent_at, resends = resumed_id, time.time(), time.time(), 0
                        continue
                    if status in ACTION_CANCELLED_STATUSES:
                        self._logger.warning(f"{command_type} action cancelled: {action_id}")
                        self._forget_navigation(command_type, actor, action_id)
                        return self.SUCCEEDED, action_id
                    # ロボットは前の移動を終える前の navigation をすぐ拒否することがあるので、少し待って送り直す
                    # ドッキングの失敗（ステーションが見つからないなど）は送り直さない
                    if is_navigation and not dock and self._should_resend_navigation(sent_at, resends):
                        new_id = self._resend_navigation(actor, manager, option, action_id)
                        if new_id is not None:
                            notifier.follow(action_id, new_id)
                            action_id, start_time, sent_at, resends = new_id, time.time(), time.time(), resends + 1
                            continue
                    self._logger.error(f"{command_type} action failed: {action_id} (status: {status})")
                    return self.FAILED, action_id

                notifier.pause(changed)
        return self.TIMED_OUT, action_id

    def _reinsert(self, command_type: str, manager: Any, data: Any, attempt: int) -> Optional[Any]:
        """リトライのために同じ動作を送り直す。送れなかったら None"""
        try:
            ret = manager.insert(data)
        except Exception as e:
            self._logger.error(f"Exception re-inserting {command_type} action on retry {attempt}: {e}", exc_info=True)
            return None
        if not ret or not hasattr(ret, "inserted_id"):
            self._logger.error(f"Failed to re-insert {command_type} action on retry {attempt}")
            return None
        self._logger.info(f"{command_type} action re-inserted: {ret.inserted_id}")
        return ret.inserted_id

    def _cancel_action(self, command_type: str, manager: Any, action_id: Any) -> None:
        """時間切れの動作を cancelled にする"""
        try:
            manager.set_status(action_id, "cancelled")
            self._logger.info(f"Cancelled timed-out {command_type} action: {action_id}")
        except Exception as e:
            self._logger.error(f"Failed to cancel timed-out action: {e}")

    def _run_timeout_fallback(self, event: ActionEvent, actor: str, command_type: str,
                              timeout_config: Dict[str, Any]) -> bool:
        """timeout_fallback_text / on_timeout があれば、時間切れの代わりの動作を実行する。実行したら True"""
        fallback_text = timeout_config.get("timeout_fallback_text")
        on_timeout = timeout_config.get("on_timeout")
        if not (fallback_text or on_timeout):
            return False
        self._logger.info(f"Executing timeout fallback for {command_type} action")
        if fallback_text:
            self.execute_fallback_action(actor, event, fallback_text, f"{command_type} action timeout")
            return True
        fallback_event = {"type": "action", "actor": actor}
        if "action" in on_timeout:
            fallback_event[on_timeout["action"]] = {
                "type": "normal",
                "option": {k: v for k, v in on_timeout.items() if k != "action"}
            }
        self.execute_action_event(fallback_event)
        return True

    def _forget_navigation(self, command_type: str, actor: str, action_id: Any) -> None:
        """navigation が終わったら目的地を忘れる（割り込みで新しいnaviに替わっていたら何もしない）"""
        if command_type == "navigation" and self._is_current_navigation(actor, action_id):
            self.interpreter.ctx.clear_navigation(actor)
            self.interpreter.update_current_state({"processing": {"is_navigating": False}})

    def _follow_resumed_navigation(self, actor: str, action_id: Any) -> Optional[ObjectId]:
        """割り込みで中断・再開されていたら、再開したnaviのID（ログも出す）。なければ None"""
        resumed_id = self._get_resumed_navigation_id(actor, action_id)
        if resumed_id is not None:
            self._logger.info(
                f"navigation action {action_id} was suspended by interrupt, following resumed navigation: {resumed_id}"
            )
        return resumed_id

    def _navigation_setting(self, name: str, default: float) -> float:
        """navigation_* の設定（以前の resumed_navigation_* の名前でもよい）"""
        config = self.interpreter.executor_config
        return config.get(f"navigation_{name}", config.get(f"resumed_navigation_{name}", default))

    def _should_resend_navigation(self, sent_at: float, resends: int) -> bool:
        """
        送ってすぐ（既定 5 秒以内）に失敗したnaviで、まだ送り直せる（既定 2 回まで）か

        executor の navigation_quick_fail_sec / navigation_resends で変えられる。
        """
        quick_fail = self._navigation_setting("quick_fail_sec", 5)
        max_resends = self._navigation_setting("resends", 2)
        return resends < max_resends and time.time() - sent_at < quick_fail

    def _resend_navigation(self, actor: str, manager: Any, option: Dict[str, Any],
                           failed_id: Any) -> Optional[Any]:
        """
        すぐ失敗したnaviを、少し待ってから同じ目的地で送り直す（executor の navigation_resend_delay、既定 3 秒）

        Returns:
            新しいaction_id。送れなかったらNone
        """
        delay = self._navigation_setting("resend_delay", 3)
        self._logger.warning(f"Navigation failed right away: {failed_id}; resending in {delay}s: {option}")
        time.sleep(delay)
        try:
            ret = manager.insert(option)
        except Exception as e:
            self._logger.error(f"Error resending navigation for {actor}: {e}", exc_info=True)
            return None
        if not ret or not hasattr(ret, "inserted_id"):
            self._logger.error(f"Failed to resend navigation for {actor}: insert returned {ret}")
            return None
        current = self.interpreter.ctx.active_navigations.get(actor)
        if isinstance(current, dict):
            current["action_id"] = str(ret.inserted_id)
        self._logger.info(f"Resent navigation for {actor}: {ret.inserted_id}")
        return ret.inserted_id

    def _get_resumed_navigation_id(self, actor: str, action_id: Any) -> Optional[ObjectId]:
        """
        中断されたnaviの代わりに resume_interrupted_navigations() で挿入されたnaviのIDを取得

        Returns:
            active_navigations に別のaction_idが記録されていればそのObjectId、なければNone
        """
        current = self.interpreter.ctx.active_navigations.get(actor)
        if not isinstance(current, dict):
            return None
        stored_id = current.get("action_id")
        if stored_id is None or str(stored_id) == str(action_id):
            return None
        try:
            return ObjectId(str(stored_id))
        except Exception:
            return None

    def _is_current_navigation(self, actor: str, action_id: Any) -> bool:
        """
        action_id が現在 active_navigations に記録されているナビゲーションと一致するか確認

        resume_interrupted_navigations() で新しいナビゲーションが挿入された場合、
        古い action_id によるクリア処理をスキップするために使用する。

        Returns:
            True: 一致する（または情報なし） → クリア処理を実行
            False: 不一致（新しいナビが挿入済み）→ クリア処理をスキップ
        """
        current = self.interpreter.ctx.active_navigations.get(actor)
        if not isinstance(current, dict):
            return True
        stored_id = current.get("action_id")
        if stored_id is None:
            return True
        return str(stored_id) == str(action_id)

    def process_command_option(
        self,
        command_name: str,
        command_data: Dict[str, Any],
        event: EventLike
    ) -> Dict[str, Any]:
        """コマンドのoptionを処理（type別処理）"""
        event = Event.coerce(event)
        cmd_type = command_data.get("type", "normal")
        option = command_data.get("option", {})

        if cmd_type == "normal":
            return option

        elif cmd_type == "file":
            result = {}
            if "text" in option:
                result["text"] = option["text"]
            if "file" in option:
                result["file"] = option["file"]
            if "english" in option:
                result["english"] = option["english"]
            return result

        elif cmd_type == "blank":
            if "text" in option:
                text = option["text"]
                repeat_count = event.repeat.count if event.repeat else 1
                context = {
                    "repeat_count": repeat_count,
                    (event.repeat.variable if event.repeat else "rep"): repeat_count,
                    "wait_for": self.interpreter.ctx.wait_for_result,
                    "triggered": self.interpreter.ctx.triggered_observation
                }
                try:
                    replaced_text = self.events.replace_placeholders(text, context)
                    return {"text": replaced_text}
                except KeyError:
                    if "except" in option:
                        return {"text": option["except"]}
                    else:
                        return {"text": "変数の置換に失敗しました"}

        elif cmd_type == "generate":
            self._logger.error("type: 'generate' should not reach _process_command_option")
            return {"text": "[エラー: generateはここで処理されません]"}

        return option

    def extract_retry_config(self, option: Dict[str, Any]) -> Dict[str, Any]:
        """アクションのリトライ設定を抽出"""
        default_retry = self.interpreter.config.get("error_recovery", {}).get("default_retry_count", 0)
        default_retry_delay = self.interpreter.config.get("error_recovery", {}).get("default_retry_delay", 1.0)

        retry_count = option.get("retry", default_retry)
        retry_delay = option.get("retry_delay", default_retry_delay)

        max_retry = self.interpreter.config.get("error_recovery", {}).get("max_retry_count", 5)
        if retry_count > max_retry:
            self._logger.warning(f"Retry count {retry_count} exceeds maximum {max_retry}, capping at {max_retry}")
            retry_count = max_retry

        min_retry_delay = self.interpreter.config.get("error_recovery", {}).get("min_retry_delay", 0.1)
        if retry_delay < min_retry_delay:
            self._logger.warning(f"Retry delay {retry_delay}s is too short, using minimum {min_retry_delay}s")
            retry_delay = min_retry_delay

        return {
            "retry": int(retry_count),
            "retry_delay": float(retry_delay)
        }

    def execute_fallback_action(self, actor: str, original_event: EventLike, fallback_text: str, reason: str) -> bool:
        """フォールバックテキストを使用してアクションを実行"""
        self._logger.info(f"Using fallback text due to: {reason}")

        fallback_event = Event.from_dict({
            "type": "action",
            "actor": actor,
            "speak": {
                "type": "normal",
                "option": {"text": fallback_text}
            }
        })
        repeat = Event.coerce(original_event).repeat
        if repeat is not None:
            fallback_event = fallback_event.with_repeat(repeat.count, repeat.variable, repeat.subevent_index)

        return self.execute_action_event(fallback_event)

    def _extract_timeout_config(self, option: Dict[str, Any]) -> Dict[str, Any]:
        """アクションのタイムアウト設定を抽出"""
        return {
            "timeout": option.get("timeout"),
            "timeout_fallback_text": option.get("timeout_fallback_text"),
            "on_timeout": option.get("on_timeout")
        }
