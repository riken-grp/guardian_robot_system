"""interrupt_detector.py - イベント駆動型の割り込み検知"""
import random
import threading
import time
from logging import getLogger
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING

from rism2.condition_checker import is_match_condition
from rism2.interrupt_queue import InterruptPriority
from rism2.navigation_query import get_collection_and_actor, navigation_query
from rism2.protocols import InterruptRuntime
from rism2.scenario_model import Scenario

if TYPE_CHECKING:
    from rism2.observation_watcher import ObservationWatcher


class InterruptDetector:
    """
    イベント駆動型の割り込み検知クラス

    ObservationWatcher からのコールバック通知で割り込み条件をチェックし、
    マッチした割り込みをキューに追加する。

    従来のポーリング方式（50ms sleep）を廃止し、イベント駆動化により
    API呼び出しコストを削減する。
    """

    POLL_INTERVAL = 0.5  # 定期チェック間隔（秒）

    def __init__(
        self,
        interpreter: InterruptRuntime,
        watcher: Optional['ObservationWatcher'] = None
    ):
        """
        初期化

        Args:
            interpreter: 親のScenarioInterpreterインスタンス
            watcher: ObservationWatcher（観測が届いたら知らせてもらう）
        """
        self.interpreter = interpreter
        self._watcher = watcher
        self._running = False
        self._logger = getLogger(__name__)
        self._poll_thread: Optional[threading.Thread] = None
        # サブシナリオID → 最後に割り込みキューへ追加した時刻（ignore_after_activated 用）
        self._last_activated: Dict[str, float] = {}
        # サブシナリオID → 実行中のイベントの ignore_interruptions で無視した観測のID
        self._event_ignored_obs: Dict[str, set] = {}

    def start(self) -> None:
        """割り込み検知を開始"""
        if self._running:
            return

        if self._watcher is None:
            raise RuntimeError("ObservationWatcher not set")

        self._running = True
        self._watcher.register_callback(self)
        self._logger.info(
            f"[InterruptDetector] Started (callback + {self.POLL_INTERVAL}s periodic polling)"
        )

        # Bug2修正: デテクター停止中に蓄積した未処理観測（mentioned=False）を即時チェック
        # シナリオ遷移中に届いた観測が次の新規観測まで無視されるのを防ぐ
        if self.interpreter.ctx.current_scenario:
            try:
                self._detect_and_queue_interrupts()
            except Exception as e:
                self._logger.error(
                    f"[InterruptDetector] Error in initial detection on start: {e}",
                    exc_info=True
                )

        # 定期チェックスレッドを起動（コールバックが来ない場合でも確実に検知）
        self._poll_thread = threading.Thread(
            target=self._periodic_poll,
            name="InterruptDetector-poll",
            daemon=True
        )
        self._poll_thread.start()

    def stop(self) -> None:
        """割り込み検知を停止"""
        if not self._running:
            return

        self._running = False
        if self._watcher is not None:
            self._watcher.unregister_callback(self)
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
        self._logger.info("[InterruptDetector] Stopped")

    def _periodic_poll(self) -> None:
        """0.5秒ごとに割り込み条件をチェックするバックグラウンドスレッド"""
        import time as _time
        while self._running:
            _time.sleep(self.POLL_INTERVAL)
            if not self._running:
                break
            if not self.interpreter.ctx.current_scenario:
                continue
            try:
                self._detect_and_queue_interrupts()
            except Exception as e:
                self._logger.error(
                    f"[InterruptDetector] Error in periodic poll: {e}",
                    exc_info=True
                )

    def on_observation(self, observation: Dict[str, Any]) -> None:
        """
        ObservationCallback プロトコル実装: 新しい観測データ到着時に呼ばれる

        Args:
            observation: 観測データ辞書（event, _id, contents等を含む）
        """
        if not self._running:
            self._logger.debug(
                f"[InterruptDetector] on_observation called but not running "
                f"(event={observation.get('event')})"
            )
            return

        if not self.interpreter.ctx.current_scenario:
            self._logger.debug(
                f"[InterruptDetector] on_observation called but no current_scenario "
                f"(event={observation.get('event')})"
            )
            return

        self._logger.info(
            f"[InterruptDetector] on_observation triggered: "
            f"event={observation.get('event')}, _id={observation.get('_id')}"
        )
        # 割り込み検知とキューイング
        try:
            self._detect_and_queue_interrupts()
        except Exception as e:
            self._logger.error(
                f"[InterruptDetector] Error in on_observation: {e}",
                exc_info=True
            )

    def _detect_and_queue_interrupts(self) -> None:
        """
        条件に合うサブシナリオを探し、発動させるものを優先度キューに追加する

        1. 条件に合うサブシナリオを探す（複数なら、今は発動させないものを外して確率で1つ選ぶ）
        2. 今は使えない観測を外す（wait_for が待っている、ignore_interruptions、ignore_after_activated など）
        3. まだ使われていない観測を確保して（mentioned にする）、キューに入れる
        """
        # 実行中のシナリオの exit_condition に合う観測が来たら、そのシナリオを打ち切る
        self._check_exit_condition()

        chosen = self._choose_subscenario()
        if chosen is None:
            return
        subscenario, matched_obs = chosen

        pending_ids = self.interpreter.interrupt_queue.pending_observation_ids()
        if pending_ids:
            self._logger.info(f"[InterruptDetector] Current pending IDs: {pending_ids}")
        self._logger.info("[InterruptDetector] Found 1 matching subscenario(s)")

        reserved = self._reserved_events()
        usable = self._usable_observations(subscenario, matched_obs, reserved)
        if not usable:
            return
        new_obs = self._claim_new_observations(subscenario, usable)
        if not new_obs:
            return

        # ignore_same_observations: まとめて届いた同じイベントの残りも使用済みにする
        # （発動の可否を確率で決める場合も、同じまとまりで何度も判定し直さない）
        if subscenario.ignore_same_observations:
            self._use_up_same_observations(subscenario, subscenario.condition, new_obs, reserved)

        # interruption_probability に基づき発動させるか決める（観測は使用済みなので、同じ観測で再判定しない）
        if not self._should_interrupt(subscenario):
            self.interpreter.interrupt_queue.remove_pending_observation_ids(
                [str(obs.get("_id", "")) for obs in new_obs if obs.get("_id")])
            return

        self._enqueue(subscenario, new_obs)

    def _choose_subscenario(self) -> Optional[Tuple[Scenario, List[Dict[str, Any]]]]:
        """条件に合うサブシナリオと、合った観測。複数なら、今は発動させないものを外してから確率で1つ選ぶ"""
        time_context = {
            "scenario_start_time": self.interpreter.ctx.scenario_start_time,
            "last_utterance_time": self.interpreter.ctx.last_utterance_time,
            "last_observation_time": self.interpreter.ctx.last_observation_time
        }
        matched = self.interpreter.scenario_manager.selector.find_matching_subscenarios(time_context)
        if not matched:
            return None
        matched = [(Scenario.coerce(sub), obs) for sub, obs in matched]
        if len(matched) > 1:
            matched = self._drop_suppressed(matched)
        if len(matched) == 1:
            return matched[0]
        self._logger.info(
            f"[InterruptDetector] {len(matched)} subscenarios matched simultaneously, "
            f"selecting one probabilistically..."
        )
        eff_priorities = [self._get_effective_priority(sub) for sub, _ in matched]
        return self.interpreter.scenario_manager.selector.select_subscenario_probabilistically(
            matched, effective_priorities=eff_priorities)

    def _usable_observations(self, subscenario: Scenario, matched_obs: List[Dict[str, Any]],
                             reserved) -> List[Dict[str, Any]]:
        """
        合った観測のうち、いまこのサブシナリオの発動に使ってよいもの。使えなければ空

        使えない理由によって、観測を使用済みにする（あとでも使わない）か、残す（続く wait_for に渡す）かが違う。
        """
        scenario_id = subscenario.id_str or "unknown"

        # wait_for が待っている（このあと待つ）イベントの観測は、wait_for に使わせる
        if reserved:
            matched_obs = [obs for obs in matched_obs if obs.get("event") not in reserved]
            if not matched_obs:
                self._logger.info(
                    f"[InterruptDetector] Leaving observation(s) to wait_for: {subscenario.name} "
                    f"(events: {sorted(reserved)})"
                )
                return []

        # 同じサブシナリオを実行中（例: バッテリ補充中に定期的に届く low_battery）
        if self.interpreter.interrupt_queue.is_scenario_active(scenario_id):
            return self._skip(subscenario, matched_obs, "while same subscenario is active")

        # このサブシナリオで一度見送った観測は、あとから使わない
        skipped_before = self._event_ignored_obs.get(scenario_id)
        if skipped_before:
            matched_obs = [obs for obs in matched_obs if str(obs.get("_id", "")) not in skipped_before]
            if not matched_obs:
                return []

        # 実行中のイベントの ignore_interruptions（「〜いますか？」の呼びかけ中など）。
        # 観測は使用済みにしない（続く wait_for が同じ観測を受け取れるように）
        if self._ignored_by_running_event(scenario_id):
            ids = self._event_ignored_obs.setdefault(scenario_id, set())
            ids.update(str(obs.get("_id", "")) for obs in matched_obs if obs.get("_id"))
            if len(ids) > 1000:
                self._event_ignored_obs[scenario_id] = set(list(ids)[-500:])
            self._logger.info(
                f"[InterruptDetector] Ignoring interrupt during event with ignore_interruptions: "
                f"{subscenario.name} (obs_count: {len(matched_obs)})"
            )
            return []

        # 実行中のシナリオの ignore_interruptions（例: 充電中の雑談の間の low_battery）
        if self._ignored_by_current_scenario(subscenario, scenario_id):
            return self._skip(subscenario, matched_obs, "listed in ignore_interruptions")

        # ignore_after_activated 秒以内に発動した（例: 顔検知が続く間の挨拶）
        if self._in_cooldown(subscenario, scenario_id):
            return self._skip(subscenario, matched_obs, "within ignore_after_activated")

        return matched_obs

    def _skip(self, subscenario: Scenario, observations: List[Dict[str, Any]], reason: str) -> List[Dict[str, Any]]:
        """発動を見送り、観測を使用済みにする（同じ観測で何度も判定しない）。空のリストを返す"""
        try:
            self.interpreter.scenario_manager.observations.update_mentioned_observations(observations)
        except Exception as e:
            self._logger.error(f"[InterruptDetector] Failed to update mentioned: {e}")
        self._logger.info(
            f"[InterruptDetector] Ignoring interrupt {reason}: {subscenario.name} (obs_count: {len(observations)})"
        )
        return []

    def _claim_new_observations(self, subscenario: Scenario,
                                observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        キューに入っていない観測を確保する（pending に入れ、mentioned にする）。確保できたものを返す

        wait_for など他の処理が先に使った観測は除く。
        """
        queue = self.interpreter.interrupt_queue
        new_obs, skipped = [], []
        for obs in observations:
            obs_id = str(obs.get("_id", ""))
            if not obs_id:
                # _id のない観測は重複を確かめられないので、そのまま使う
                self._logger.warning(f"[InterruptDetector] Observation without _id for: {subscenario.name}")
                new_obs.append(obs)
            elif queue.is_observation_pending(obs_id):
                skipped.append(obs_id)
            else:
                new_obs.append(obs)
                queue.add_pending_observation_id(obs_id)
                self._logger.info(f"[InterruptDetector] Added pending ID: {obs_id}")
        if not new_obs:
            self._logger.info(f"[InterruptDetector] Skipping already pending: {subscenario.name} (skipped IDs: {skipped})")
            return []

        claimed = self.interpreter.scenario_manager.observations.claim_observations(new_obs)
        claimed_ids = {id(obs) for obs in claimed}
        unclaimed = [str(obs.get("_id", "")) for obs in new_obs if id(obs) not in claimed_ids and obs.get("_id")]
        if unclaimed:
            queue.remove_pending_observation_ids(unclaimed)
        if not claimed:
            self._logger.info(
                f"[InterruptDetector] Skipping already used observation(s): {subscenario.name} (IDs: {unclaimed})")
            return []
        self._logger.info(f"[InterruptDetector] Marked {len(claimed)} observation(s) as mentioned for: {subscenario.name}")
        return claimed

    def _enqueue(self, subscenario: Scenario, observations: List[Dict[str, Any]]) -> None:
        """優先度キューに入れる（優先度の高いものから実行される）"""
        priority = self._get_effective_priority(subscenario)
        scenario_id = subscenario.id_str or "unknown"
        self.interpreter.interrupt_queue.add(priority, scenario_id, subscenario, subscenario.condition, observations)
        self._last_activated[scenario_id] = time.time()
        self._logger.info(
            f"[InterruptDetector] Interrupt ADDED to queue: {subscenario.name} "
            f"(priority: {priority}, queue_size: {len(self.interpreter.interrupt_queue)}, "
            f"obs_count: {len(observations)})"
        )

    def _use_up_same_observations(self, subscenario: Scenario, condition: Dict[str, Any],
                                  used: List[Dict[str, Any]], reserved) -> None:
        """
        発動に使った観測と同じイベントの、まだ使われていない観測をすべて使用済みにする

        例: asr が続けて3件届いたとき、1件目で発動したら残りの2件では発動しない。
        wait_for などが待っているイベントには手を付けない。
        """
        events = {name for name in condition if not name.startswith("$")} - set(reserved or ())
        if not events:
            return
        used_ids = {str(obs.get("_id")) for obs in used}
        observations = self.interpreter.scenario_manager.observations.get_recent_observations()
        if not isinstance(observations, dict):
            return
        rest = [obs for obs_list in observations.values() for obs in obs_list or []
                if obs.get("event") in events and str(obs.get("_id")) not in used_ids]
        if not rest:
            return
        claimed = self.interpreter.scenario_manager.observations.claim_observations(rest)
        if claimed:
            self._logger.info(
                f"[InterruptDetector] ignore_same_observations: used up {len(claimed)} more "
                f"observation(s) of {sorted(events)} for: {subscenario.name}"
            )


    def _check_exit_condition(self) -> None:
        """
        一番内側のシナリオの exit_condition に合う観測が、そのシナリオの開始後に来たら打ち切る

        例: 音声対話中に no people が来たら、対話をやめる。
        使った観測は mentioned にして、同じ観測で割り込みが発動しないようにする。
        """
        # 一番内側のフレーム（割り込み中ならそのサブシナリオ、そうでなければメインシナリオ）
        frame = self.interpreter.ctx.top_frame
        scenario, started = frame.scenario, frame.started_at
        conditions = scenario.exit_conditions if scenario is not None else []
        if not conditions or frame.exit_requested:
            return

        def is_new(obs):
            oid = obs.get("_id")
            return hasattr(oid, "generation_time") and oid.generation_time.timestamp() >= started - 1

        observations = self.interpreter.scenario_manager.observations.get_recent_observations()
        if not isinstance(observations, dict):
            return
        new_obs = {name: [o for o in obs_list if is_new(o)] for name, obs_list in observations.items()}
        # 条件が複数あれば、どれか1つが合えば打ち切る（no_people か conversation_finished など）
        for condition in conditions:
            matched, matched_obs = is_match_condition(condition, new_obs)
            if matched:
                break
        else:
            return
        claimed = self.interpreter.scenario_manager.observations.claim_observations([o for o in matched_obs if o])
        if not claimed:
            return
        self._logger.info(
            f"[InterruptDetector] exit_condition met, ending scenario: {scenario.name} "
            f"(events: {[o.get('event') for o in claimed]})"
        )
        # 照合している間に別の割り込みが始まっても、照合したフレームを打ち切る
        frame.exit_trigger_events = [o.get("event") for o in claimed]
        frame.exit_condition_met = True
        frame.exit_requested = True

    def _reserved_events(self) -> set:
        """wait_for などが待っている、またはこのあと待つイベント名（その観測は割り込みに使わない）"""
        return self.interpreter.ctx.events_kept_from_interrupts()

    def _drop_suppressed(self, matched):
        """
        同時に合ったサブシナリオから、今は発動させないもの（実行中のイベントやシナリオの
        ignore_interruptions、同じサブシナリオを実行中、ignore_after_activated の間）を外す。全部外れるなら元のまま返す
        （それぞれの扱いは、このあとの個別の判定でする）

        外さずに選ぶと、発動させないほうが選ばれて、発動できるほうまで見送ることになる。
        """
        def suppressed(subscenario: Scenario) -> bool:
            scenario_id = subscenario.id_str or "unknown"
            return (self._ignored_by_running_event(scenario_id)
                    or self._ignored_by_current_scenario(subscenario, scenario_id)
                    or self.interpreter.interrupt_queue.is_scenario_active(scenario_id)
                    or self._in_cooldown(subscenario, scenario_id))

        remaining = [(sub, obs) for sub, obs in matched if not suppressed(sub)]
        return remaining or matched

    def _ignored_by_current_scenario(self, subscenario: Scenario, scenario_id: str) -> bool:
        """
        実行中のシナリオ（割り込み実行中のサブシナリオも含む）の
        ignore_interruptions（サブシナリオIDのリスト）に含まれるかを判定する

        Args:
            subscenario: サブシナリオ
            scenario_id: サブシナリオID

        Returns:
            無視すべきならTrue
        """
        running = [f.scenario for f in self.interpreter.ctx.interrupt_frames]
        scenarios = [self.interpreter.ctx.current_scenario] + running
        return any(scenario_id in s.ignore_interruptions for s in scenarios if s is not None)

    def _ignored_by_running_event(self, scenario_id: str) -> bool:
        """実行中のイベント（「〜いますか？」の返事待ちなど）の ignore_interruptions に含まれるか"""
        return self.interpreter.ctx.ignored_by_running_events(scenario_id)

    def _in_cooldown(self, subscenario: Scenario, scenario_id: str) -> bool:
        """
        ignore_after_activated（秒）以内に発動済みかを判定する

        Args:
            subscenario: サブシナリオ
            scenario_id: サブシナリオID

        Returns:
            無視すべき期間内ならTrue
        """
        seconds = subscenario.ignore_after_activated
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            return False
        last = self._last_activated.get(scenario_id)
        return last is not None and time.time() - last < seconds

    def _should_interrupt(self, subscenario: Scenario) -> bool:
        """
        interruption_probabilityに基づき割り込みを実行するか判定する

        サブシナリオの interruption_probability があればそれを、なければ rism_config の値を使う。
        important または force_interrupt が true のサブシナリオは常に実行する。

        Args:
            subscenario: サブシナリオ

        Returns:
            割り込みを実行する場合True
        """
        if subscenario.always_interrupts:
            return True

        probability = subscenario.interruption_probability
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            probability = self.interpreter.config.get("interruption_probability", 1.0)
        if probability is None or probability >= 1.0:
            return True

        if random.random() < probability:
            return True

        self._logger.info(
            f"[InterruptDetector] Interrupt not selected by interruption_probability "
            f"({probability}): {subscenario.name}"
        )
        return False

    # ===================================================================
    # F6: 内部状態ベースの動的 priority 調整
    # ===================================================================

    def _get_effective_priority(self, subscenario: Scenario) -> int:
        """
        内部状態とconfigルールに基づいて effective priority を計算する

        Args:
            subscenario: サブシナリオ（priority と tags を参照）

        Returns:
            effective priority（0〜1000、大きいほど優先）。ルールの priority_boost を足す
        """
        priority = subscenario.priority
        tags = subscenario.tags
        internal_state = getattr(self.interpreter, "internal_state", {})
        rules = self.interpreter.config.get("internal_state_priority_rules", [])
        for rule in rules:
            if self._rule_matches(rule, internal_state) and self._tags_overlap(rule, tags):
                priority += rule.get("priority_boost", 0)
        return max(InterruptPriority.MIN, min(InterruptPriority.MAX, int(priority)))

    def _is_navigating(self) -> bool:
        """
        tBlackBoard.Actions の navigation コレクションで is_playing を確認

        Returns:
            いずれかのロボットがナビゲーション中なら True
        """
        for managers_dict in self.interpreter.action_managers.values():
            collection, nav_actor = get_collection_and_actor(managers_dict.get("navigation"))
            if collection is None or nav_actor is None:
                continue
            if collection.count_documents(navigation_query(nav_actor, ("is_playing",))) > 0:
                return True
        return False

    def _rule_matches(self, rule: Dict[str, Any], internal_state: Dict[str, Any]) -> bool:
        """
        when セクションの条件が internal_state にマッチするか判定

        サポートする条件キー:
            is_navigating: bool  → tBlackBoard.Actions で確認
            <field>_gte: float   → internal_state[field] >= value
            <field>_lte: float   → internal_state[field] <= value
            <field>: value       → internal_state[field] == value
        """
        for key, expected in rule.get("when", {}).items():
            if key == "is_navigating":
                if self._is_navigating() != expected:
                    return False
            elif key.endswith("_gte"):
                field = key[:-4]
                if internal_state.get(field, 0.0) < expected:
                    return False
            elif key.endswith("_lte"):
                field = key[:-4]
                if internal_state.get(field, 0.0) > expected:
                    return False
            else:
                if internal_state.get(key) != expected:
                    return False
        return True

    def _tags_overlap(self, rule: Dict[str, Any], tags: List[str]) -> bool:
        """
        ルールの match_tags と subscenario の tags が重複するか判定

        match_tags が空の場合は全 subscenario に適用（True を返す）
        """
        match_tags = rule.get("match_tags", [])
        return not match_tags or bool(set(match_tags) & set(tags))
