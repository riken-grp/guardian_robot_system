"""メインインタプリタ - シナリオ実行とイベント処理"""
import copy
import time
import datetime
from contextlib import ExitStack
from logging import getLogger
from typing import Dict, Any, Optional
from threading import Lock

# ActionManager は pyindy のマネージャーに置き換えられました
from .scenario_manager import ScenarioManager
from .debug import DebugManager
from .interrupt_queue import InterruptQueue
from .interrupt_queue_visualizer import InterruptQueueVisualizer
from .interrupt_queue_tracker import InterruptQueueTracker
from .interrupt_queue_monitor import InterruptQueueMonitor
from .interrupt_detector import InterruptDetector
from .condition_waiter import ConditionWaiter
from .database import shared_client, use_shared_client

# Phase 4 Wave 2: 委譲先モジュール
from .settings import check_and_fill
from .wait_state import WaitStateTracker
from .state_manager import StateManager
from .prefetch_manager import PrefetchManager
from .interrupt_manager import InterruptManager
from .event_processor import EventProcessor
from .constants import ExitCode, NavigationInterruptMode, ResumeAfter
from .execution_context import EventInterrupted, ExecutionContext


class ScenarioInterpreter:
    """シナリオインタプリタ - シナリオの実行とイベント処理"""

    def __init__(self, config: Dict[str, Any], entry_point: Optional[str] = None):
        """
        Args:
            config: 設定辞書
            entry_point: 開始シナリオID（オプション）
        """
        self._logger = getLogger(__name__)
        # 設定を検査し、書いていない項目に既定値を入れる（項目の一覧は settings.py）
        for warning in check_and_fill(config):
            self._logger.warning(f"[Settings] {warning}")
        self.config = config
        self.scenario_manager = ScenarioManager(config)
        self.running = False
        self.context_lock = Lock()
        # シナリオ実行中の状態（実行中のシナリオのフレーム、wait_for の結果、会話履歴など）
        self.ctx = ExecutionContext()

        self._read_settings(config)
        self._setup_actors()
        self._setup_interrupts(config)
        self._setup_workers(config)

        # アイドルモードの状態
        self._idle_mode_logged = False
        self._last_scenario_search_time: Optional[float] = None
        self._idle_check_count = 0

        # エントリーポイントがある場合はロード（部品をすべて作ってから）
        if entry_point:
            self.load_scenario(entry_point)

    def _read_settings(self, config: Dict[str, Any]) -> None:
        """よく使う設定（check_and_fill で既定値が入っている）"""
        self.executor_config = config.get("executor", {})       # 完了待ちの timeout など
        self.max_history_length = config.get("max_history_length", 10)  # LLM に渡す会話履歴の長さ
        self.default_exit_code = config.get("default_scenario_exit_code", ExitCode.SUCCESS)
        self.default_navigation_interrupt_mode = config.get(
            "default_navigation_interrupt_mode", NavigationInterruptMode.PARALLEL)
        self.debug_manager = DebugManager(config, self._logger)

    def _setup_actors(self) -> None:
        """ロボットごとの ActionManager と状態（キーはシナリオの actor: robot1, robot2, ...）"""
        self.event_generators = {}  # Event Generator（LLM 生成など）。使うときに作る
        self.action_managers = {}
        self._setup_action_managers()
        # 値は {"name": ロボットの名前（name_alias）, "status": "waiting" | "running"}
        self.actors_status = {
            robot_id: {"name": robot_config.get("name_alias"), "status": "waiting"}
            for robot_id, robot_config in self.config["robots"].items()
        }
        # ロボットの内部状態（割り込みの優先度の調整に使う）
        self.internal_state: Dict[str, Any] = dict(self.INITIAL_INTERNAL_STATE)

    def _setup_interrupts(self, config: Dict[str, Any]) -> None:
        """割り込みの検知・キューと、観測の待ち合わせ（どちらも観測が届いたら知らせてもらう）"""
        watcher = self.scenario_manager.observations.watcher
        self.interrupt_queue = InterruptQueue()
        self.interrupt_detector = InterruptDetector(self, watcher)
        self.queue_monitor = self._build_queue_monitor(config)
        self.condition_waiter = ConditionWaiter(self.scenario_manager.observations)
        watcher.register_callback(self.condition_waiter)

    def _setup_workers(self, config: Dict[str, Any]) -> None:
        """状態の記録、先読み、イベントの実行、割り込みの実行"""
        self.state_manager = StateManager(config)
        self.wait_state = WaitStateTracker(self)  # 待ち状態を current_state.waiting / last_wait に出す
        prefetch = config.get("prefetch", {})
        self.prefetch_manager = PrefetchManager(
            interpreter=self,
            enabled=prefetch.get("enabled", True),
            wait_timeout=prefetch.get("wait_timeout", 30.0)
        )
        self.event_processor = EventProcessor(self)
        self.interrupt_mgr = InterruptManager(self)

    # ロボットの内部状態の初期値
    INITIAL_INTERNAL_STATE: Dict[str, Any] = {
        "emotion": "neutral",       # "positive" | "neutral" | "negative"
        "personality": "friendly",  # "friendly" | "formal" | "calm"
        "stress_level": 0.0,        # 0.0 〜 1.0
    }

    def _build_queue_monitor(self, config: Dict[str, Any]) -> InterruptQueueMonitor:
        """割り込みキューの可視化（debug.visualize_interrupt_queue）と MongoDB への記録（debug.track_interrupt_queue）"""
        debug_config = config.get("debug", {})
        visualizer = None
        if debug_config.get("visualize_interrupt_queue", False):
            visualizer = InterruptQueueVisualizer(use_rich=True)
            self._logger.info("Interrupt queue visualization enabled")
        tracker = InterruptQueueTracker(
            mongo_client=shared_client(config["demo"]["host"], config["demo"]["port"]),
            db_name="tBlackBoard",
            enabled=debug_config.get("track_interrupt_queue", False),
            logger=self._logger
        )
        return InterruptQueueMonitor(visualizer, tracker)

    def _setup_action_managers(self) -> None:
        """各アクターのActionManager（pyindyベース）を初期化"""
        from pyindy.mongo import (
            UtteranceManager,
            GestureManager,
            NavigationManager,
            EyeManager,
            ROSCommandManager,
            RecallManager,
            ObservationManager
        )
        
        for robot_id, robot_config in self.config["robots"].items():
            host = robot_config["action_db"]["host"]
            port = robot_config["action_db"]["port"]
            dbname = robot_config["action_db"]["dbname"]
            actor_name = robot_config["name"]
            # action_db versionを取得（デフォルトは"2.0"）
            version = robot_config["action_db"].get("version", "2.0")

            # pyindyの各マネージャーを作成（actorにはnameを使用、versionも渡す）。接続は共有のものを使う
            self.action_managers[robot_id] = {
                kind: use_shared_client(cls(host, port, actor_name, dbname, version=version),
                                        host, port, dbname, "Actions")
                for kind, cls in (("utterance", UtteranceManager), ("gesture", GestureManager),
                                  ("navigation", NavigationManager), ("eye", EyeManager),
                                  ("ros_command", ROSCommandManager), ("recall", RecallManager),
                                  # wait_for の間の「観測中」の印（llm_responder などロボット側が読む）
                                  ("observation", ObservationManager))
            }
            self._logger.info(f"Pyindy managers initialized for {robot_id} ({actor_name}) with version {version}")

    def update_current_state(self, updates: Dict[str, Any]) -> None:
        """current_stateを更新 → StateManagerに委譲"""
        return self.state_manager.update_current_state(updates)

    def update_internal_state(self, key: str, value: Any) -> None:
        """
        ロボットの内部状態を更新してMongoDBにも書き込む（F6）

        Args:
            key: 更新するフィールド名（"emotion", "personality", "stress_level" 等）
            value: 新しい値
        """
        self.internal_state[key] = value
        self.update_current_state({"internal_state": {key: value}})

    def _decrease_stress_level_on_scenario_complete(self) -> None:
        """シナリオ完了時に stress_level を減少させる（F8）"""
        stress_cfg = self.config.get("stress_level", {})
        decrement = stress_cfg.get("decrement", 0.1)
        current = self.internal_state.get("stress_level", 0.0)
        new_level = max(0.0, current - decrement)
        if new_level != current:
            self.update_internal_state("stress_level", new_level)
            self._logger.info(f"[stress_level] Decreased on scenario complete: {current:.2f} → {new_level:.2f}")

    def _get_current_state(self) -> Dict[str, Any]:
        """現在の状態を取得 → StateManagerに委譲"""
        return self.state_manager.get_current_state()

    def load_scenario(self, scenario_id: str) -> bool:
        """
        シナリオをロード

        Args:
            scenario_id: シナリオID

        Returns:
            成功した場合True
        """
        with self.context_lock:
            # 実行するシナリオはID指定（entry_point / next_scenarios / redirect）で決まっているため、
            # inactiveなシナリオ（next_scenarios経由でのみ実行するもの）もロードする
            scenario = self.scenario_manager.scenarios.load_scenario(scenario_id, include_inactive=True)
            if not scenario:
                self._logger.error(f"Failed to load scenario: {scenario_id}")
                return False

            self.ctx.current_scenario = copy.deepcopy(scenario)
            self.ctx.current_event_index = 0

            # シナリオ開始時刻を記録（時間ベース条件用）
            self.ctx.scenario_start_time = datetime.datetime.now()

            # プリフェッチキャッシュをクリア
            self.prefetch_manager.clear_cache()

            # 前のメインシナリオの履歴が終わっていなければ（例外、redirect など）、aborted で閉じる
            self._close_open_histories("aborted")
            # 待ちのスタックを空にする（割り込みのサブシナリオはここを通らないので、外側の待ちは消えない）
            self.wait_state.reset()

            # シナリオ開始をscenario_historyに記録
            self._logger.debug(f"About to call start_scenario_in_history for scenario: {scenario.name}")
            self.ctx.current_scenario_history_id = self.scenario_manager.history.start_scenario_in_history(
                scenario_id=scenario.id_str,
                scenario_name=scenario.name,
                is_interruption=False,
                parent_history_id=None,
                depth=0,
                robot=self.robot_name_for_history
            )
            self._logger.debug(f"start_scenario_in_history returned: {self.ctx.current_scenario_history_id}")

            # 全ロボットのステータスを取得（Actionsのis_playingを確認）
            actors_status = self.scenario_manager.robots.get_all_robots_status()

            self.update_current_state(self._state_on_load(scenario, actors_status))

            self._logger.info(f"Scenario loaded: {scenario.name} (ID: {scenario_id})")
            return True

    @staticmethod
    def _state_on_load(scenario, actors_status: Dict[str, Any]) -> Dict[str, Any]:
        """シナリオを読み込んだときの current_state（status は scenario_history と同じ is_playing）"""
        return {
            "interpreter": {"status": "loading"},
            "scenario": {"id": scenario.id_str, "name": scenario.name, "status": "is_playing"},
            "event": {"index": 0},
            "actors": actors_status,
            "interrupt": {"is_interrupted": False, "depth": 0},
            "waiting": [],  # last_wait は残す
            "processing": {
                "is_asr_waiting": False,
                "is_llm_generating": False,
                "is_tts_processing": False,
                "is_prefetching": False,
                "prefetch_event_index": -1
            }
        }

    def _determine_next_scenario(self) -> Optional[str]:
        """
        次に実行するシナリオIDを決定
        
        優先順位:
        1. redirect_scenario_id（割り込みからのリダイレクト）
        2. scenario_exit_statusのnext_scenario（メインシナリオからのリダイレクト）
        3. None（次のシナリオなし）
        
        Returns:
            次のシナリオID（ObjectId文字列）、またはNone
        """
        # 割り込みからのリダイレクトを優先
        if self.ctx.redirect_scenario_id:
            next_scenario_id = self.ctx.redirect_scenario_id
            self.ctx.redirect_scenario_id = None  # クリア
            self._logger.info(f"Next scenario determined from interrupt redirect: {next_scenario_id}")
            return next_scenario_id
        
        # scenario_exit_statusからnext_scenarioを取得
        if self.ctx.scenario_exit_status:
            exit_code = self.ctx.scenario_exit_status.get("exit_code")
            exit_data = self.ctx.scenario_exit_status.get("exit_data", {})
            
            if exit_code == ExitCode.REDIRECT:
                next_scenario_id = exit_data.get("next_scenario")
                if next_scenario_id:
                    self._logger.info(f"Next scenario determined from exit_status: {next_scenario_id}")
                    return next_scenario_id
                else:
                    self._logger.warning("Redirect exit_code but no next_scenario in exit_data")
        
        # 次のシナリオなし
        self._logger.info("No next scenario determined")
        return None

    def execute_scenario(self) -> bool:
        """
        現在のシナリオを実行

        Returns:
            成功した場合True
        """
        if not self.ctx.current_scenario:
            self._logger.error("No scenario loaded")
            return False

        # シナリオ開始時に終了ステータスをリセット
        self.ctx.begin_scenario()

        self._logger.info(f"[execute_scenario] Starting interrupt_detector for: {self.ctx.current_scenario.name}")
        self.interrupt_detector.start()
        self._logger.info(f"[execute_scenario] interrupt_detector started (running={self.interrupt_detector._running})")

        try:
            with self.context_lock, ExitStack() as stack:
                self.update_current_state({"interpreter": {"status": "running"}})
                events = self.ctx.current_scenario.events
                self._logger.info(f"Executing scenario: {self.ctx.current_scenario.name} ({len(events)} events)")
                reserve_next_waits = stack.enter_context(self.ctx.waits_ahead(events))

                event_idx = 0
                while event_idx < len(events):
                    self.ctx.current_event_index = event_idx
                    reserve_next_waits(event_idx)
                    try:
                        step = self._run_main_event(events, event_idx, events[event_idx])
                    except EventInterrupted as interrupted:
                        # 割り込みの resume_after: restart ならこのイベントをやり直し、next_event なら次へ
                        if self.ctx.terminate_main_scenario:
                            break
                        if interrupted.mode == ResumeAfter.RESTART:
                            self._logger.info(f"Restarting interrupted event {event_idx}")
                            continue
                        self._logger.info(f"Skipping the rest of interrupted event {event_idx}")
                        event_idx += 1
                        continue
                    if step == self.EVENT_FAILED:
                        return False
                    if step == self.STOP_SCENARIO:
                        break
                    event_idx += 1

                self._finish_scenario()
                return True
        finally:
            # 割り込み検知スレッドを止め、次の実行のためにキューを空にする
            self.interrupt_detector.stop()
            self.interrupt_queue.clear()

    # _run_main_event の結果
    NEXT_EVENT, STOP_SCENARIO, EVENT_FAILED = "next_event", "stop_scenario", "event_failed"

    def _run_main_event(self, events, event_idx: int, event) -> str:
        """
        メインシナリオのイベント1つを実行し、そのあと割り込みを処理する

        Returns:
            NEXT_EVENT（続ける）/ STOP_SCENARIO（残りを打ち切る）/ EVENT_FAILED（失敗）
        """
        actor = event.actor or ""
        self._set_actor_status(actor, "running", "Event start")
        self.update_current_state({"event": {"index": event_idx, "type": event.type}, "actors": self.actors_status})
        self._dump_debug_state(self.debug_manager.dump_state_before_event, events, event_idx, event, done=event_idx)

        if not self.event_processor.execute_event(event):
            self._logger.error(f"Event execution failed at index {event_idx}")
            self.update_current_state({"interpreter": {"status": "error"}})
            return self.EVENT_FAILED

        if self.ctx.exit_requested:
            self._logger.info(f"Scenario exit requested at index {event_idx}, skipping remaining events")
            self.event_processor.run_exit_events(self.ctx.current_scenario)
            return self.STOP_SCENARIO

        self._dump_debug_state(self.debug_manager.dump_state_after_event, events, event_idx, event, done=event_idx + 1)
        self._set_actor_status(actor, "waiting", "Event end")
        self.update_current_state({"event": {"index": event_idx + 1}, "actors": self.actors_status})

        # イベントが終わるたびに割り込みを検知する（interruptable に関わらず。検知スレッドを待たずにキューに入れる）
        self._detect_interrupts("[execute_scenario]")
        # 割り込みの実行は interruptable なイベントのあとだけ。important のものは interruptable: false のイベントの直後でも実行する
        if self.process_interrupts_between_events(important_only=not event.interruptable):
            self._logger.info("Interrupt handled, resuming main scenario")
            self._mark_back_from_interrupt()

        if self.ctx.terminate_main_scenario:
            self._logger.info("Main scenario terminated by interrupt, skipping remaining events")
            return self.STOP_SCENARIO
        return self.NEXT_EVENT

    def _finish_scenario(self) -> None:
        """シナリオの終わり: 終わり方を決め、履歴と状態を更新し、残っている割り込みを処理する"""
        if self.ctx.scenario_exit_status is None:
            self.ctx.scenario_exit_status = {
                "exit_code": self.default_exit_code,
                "exit_data": {},
                "timestamp": datetime.datetime.now().isoformat()
            }
            self._logger.info(f"No explicit exit_code, using default: {self.default_exit_code}")

        if self.ctx.current_scenario_history_id:
            self.scenario_manager.history.finish_scenario_in_history(
                self.ctx.current_scenario_history_id,
                exit_status=self.ctx.scenario_exit_status
            )
            self.ctx.current_scenario_history_id = None
        else:
            self._logger.warning("current_scenario_history_id is None, skipping finish_scenario_in_history")

        self.update_current_state({
            "interpreter": {"status": "completed"},
            "scenario": {"id": None, "name": None, "status": "done"},  # scenario_history と同じ status
            "event": {"index": -1}
        })
        self._logger.info(f"Scenario completed: {self.ctx.current_scenario.name}")
        self._decrease_stress_level_on_scenario_complete()

        # 最後のイベントの間や後に届いた割り込みを、キューを空にする前に実行する
        if self.process_interrupts_between_events():
            self._logger.info("Interrupt handled after all scenario events completed")
            self._mark_back_from_interrupt()

    def _set_actor_status(self, actor: str, status: str, label: str) -> None:
        """イベントの始まり（running）と終わり（waiting）に actor の状態を変える"""
        if actor and actor in self.actors_status:
            self.actors_status[actor]["status"] = status
        self._logger.debug(f"[ACTORS] {label} (actor={actor}): {self.actors_status}")

    def _dump_debug_state(self, dump, events, event_idx: int, event, done: int) -> None:
        """デバッグモードなら、イベントの前後の状態を書き出す（done はそれまでに終えたイベントの数）"""
        if self.debug_manager.is_enabled():
            finished_events = [e.to_dict() for e in events[:done]]
            dump(event_idx, event.to_dict(), self._get_current_state(), finished_events, self.ctx.conversation_history)

    def _mark_back_from_interrupt(self) -> None:
        """割り込みから戻ったことを current_state に書く"""
        self.update_current_state({
            "interpreter": {"status": "running"},
            "scenario": {"status": "is_playing"},
            "interrupt": {"is_interrupted": False, "depth": 0, "subscenario_id": None, "subscenario_name": None}
        })

    def _detect_interrupts(self, label: str) -> None:
        """割り込みを検知してキューに入れる（失敗してもシナリオは続ける）"""
        try:
            self.interrupt_detector._detect_and_queue_interrupts()
        except Exception as e:
            self._logger.error(f"{label} Error in interrupt detection: {e}", exc_info=True)

    def run_scenario_chain(self, initial_scenario_id: Optional[str]) -> None:
        """
        シナリオを連鎖的に実行

        Args:
            initial_scenario_id: 開始シナリオID（Noneの場合は待機モードで開始）
        """
        self.running = True
        current_id = initial_scenario_id

        while self.running:
            if current_id is None:
                current_id = self._idle_once()
                continue

            self._logger.info(f"[CHAIN] Loading scenario: {current_id}")
            if not self.load_scenario(current_id):
                self._logger.error(f"[CHAIN] Failed to load scenario: {current_id} — stopping chain")
                break
            self._logger.info(f"[CHAIN] Executing scenario: {current_id}")
            if not self.execute_scenario():
                self._logger.error(f"[CHAIN] Scenario execution failed: {current_id} — stopping chain")
                break

            current_id = self._next_scenario_id()
            if current_id:
                self._logger.info(f"Loading next scenario: {current_id}")
                time.sleep(0.5)
            else:
                self._logger.info("No next scenario found, entering idle mode")

        self.running = False
        self._logger.info("Scenario chain completed")

    def _next_scenario_id(self) -> Optional[str]:
        """
        次に実行するシナリオ

        1. リダイレクト（scenario_exit や割り込みから）
        2. 割り込みでメインシナリオを終えたなら、すべてのアクティブなシナリオから条件で選ぶ
        3. next_scenarios があれば、その中から選ぶ
        4. なければ、すべてのアクティブなシナリオから条件で選ぶ
        """
        selector = self.scenario_manager.selector
        redirected = self._determine_next_scenario()
        if redirected:
            return redirected
        if not self.ctx.terminate_main_scenario and self.ctx.current_scenario.next_scenarios:
            return selector.select_next_scenario(self.ctx.current_scenario.next_scenarios)
        return selector.find_matching_scenario()

    def _idle_once(self) -> Optional[str]:
        """
        待機中の1回分: 割り込みを検知・実行し、5秒ごとに実行できるシナリオを探す

        Returns:
            見つかったシナリオのID。なければ None（待機を続ける）
        """
        if not self._idle_mode_logged:
            self._logger.info("=" * 60)
            self._logger.info("Entering IDLE MODE - waiting for interruption or new scenario")
            self._logger.info("=" * 60)
            self._idle_mode_logged = True
        else:
            self._logger.debug("Idle mode: waiting...")
        self.update_current_state({"interpreter": {"status": "idle"}, "scenario": {"status": "idle"}})

        # 待機中は検知スレッドが止まっているので、ここで検知する
        self._detect_interrupts("[IDLE]")
        if self.process_interrupts_between_events():
            self._logger.info("Interrupt handled in idle mode, searching for next scenario...")
            # 割り込みの間に届いた観測を、シナリオ探しで使われる前に割り込みとしてキューに入れる
            self._detect_interrupts("[IDLE] post-interrupt")
            # 割り込みからのリダイレクトを優先する
            found = self.ctx.redirect_scenario_id or self.scenario_manager.selector.find_matching_scenario()
            self.ctx.redirect_scenario_id = None
            if found:
                self._logger.info(f"Exiting idle mode: Found scenario '{found}'")
                self._idle_mode_logged = False
                return found
            self._logger.info("No scenario found after interrupt, continuing idle mode")
        else:
            time.sleep(0.1)

        if self._last_scenario_search_time is None:
            self._last_scenario_search_time = time.time()
            self._idle_check_count = 0
        if time.time() - self._last_scenario_search_time <= 5.0:
            return None

        self._idle_check_count += 1
        observations = self.scenario_manager.observations.get_recent_observations(limit=10)
        obs_count = sum(len(obs_list) for obs_list in observations.values())
        active_scenarios = self.scenario_manager.scenarios.get_active_scenarios()
        active_subscenarios = self.scenario_manager.scenarios.get_active_subscenarios()
        self._logger.info(
            f"[IDLE] Still in idle mode (check #{self._idle_check_count}): "
            f"obs={obs_count} (unmentioned), scenarios={len(active_scenarios)}, subscenarios={len(active_subscenarios)}"
        )
        self._logger.debug(f"Active scenarios: {[s.name or s.id_str for s in active_scenarios]}")

        found = self.scenario_manager.selector.find_matching_scenario()
        self._last_scenario_search_time = time.time()
        if found:
            self._logger.info(f"[IDLE] Exiting idle mode: Found active scenario '{found}'")
            self._idle_mode_logged = False
        return found

    def stop(self) -> None:
        """インタプリタを停止"""
        self.running = False
        self.update_current_state({
            "interpreter": {
                "status": "idle"
            }
        })
        self._logger.info("Interpreter stopped")

    def cleanup(self) -> None:
        """
        リソースのクリーンアップ

        割り込み検知と観測の監視を止め、まだ始まっていない（waiting の）アクションを取り消す。
        止めたあとにロボットが古いアクションを実行しないようにする。
        """
        self._logger.info("Cleaning up interpreter resources")
        self._close_open_histories("aborted")
        self.stop()
        self.interrupt_detector.stop()
        self.scenario_manager.close()

    @property
    def robot_name_for_history(self) -> Optional[str]:
        """scenario_history の robot（最初のロボットの名前）"""
        robots = list(self.config.get("robots", {}).values())
        return robots[0].get("name") if robots else None

    def _close_open_histories(self, exit_code: str) -> None:
        """
        終わっていない scenario_history の記録を、内側から順に閉じる（exit_status の exit_code は exit_code）

        前のメインシナリオが終わらないまま次を読み込むとき（例外、redirect など）と、プロセスを終えるときに呼ぶ。
        """
        history = self.scenario_manager.history
        for frame in reversed(self.ctx.frames):
            if frame.history_id:
                history.finish_scenario_in_history(frame.history_id, exit_status={
                    "exit_code": exit_code, "timestamp": datetime.datetime.now().isoformat()})
                self._logger.info(f"Closed unfinished scenario history {frame.history_id} as {exit_code}")
                frame.history_id = None

    def process_pending_interrupts(self, important_only: bool = False) -> bool:
        """
        イベントの途中（動作や観測を待つ間）で、キューの割り込みを実行する（InterruptManager に委譲）

        割り込みの resume_after が next_event / restart なら、戻ったところで EventInterrupted を送り、
        実行中のイベントを抜ける（そのシナリオのイベントの並びが、次へ進むかやり直す）。

        Args:
            important_only: True なら important のものだけを実行する（interruptable: false のイベントの直後）

        Returns:
            割り込みを実行したら True
        """
        handled = self.interrupt_mgr.process_pending_interrupts(important_only)
        if handled:
            self.ctx.raise_if_event_interrupted()
        return handled

    def process_interrupts_between_events(self, important_only: bool = False) -> bool:
        """
        イベントの合間や待機中に、キューの割り込みを実行する（抜けるイベントがないので resume_after は resume と同じ）

        important_only: True なら important のものだけを実行する（interruptable: false のイベントの直後）
        """
        handled = self.interrupt_mgr.process_pending_interrupts(important_only)
        self.ctx.top_frame.resume_mode = None
        return handled

    def suspend_navigation(self) -> None:
        """実行中の移動を止める（suspend_navigation イベント）→ InterruptManagerに委譲"""
        self.interrupt_mgr.suspend_navigation()
