"""execution_context.py - シナリオ実行中の状態

ScenarioInterpreter が持つ状態のうち、シナリオの実行に伴って変わるものをまとめる。
EventProcessor や InterruptManager は interpreter.ctx を通してこれを読み書きする。
"""
import datetime
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, Dict, List, Optional, Set, Tuple

from .event_model import Event, WaitingEvent
from .scenario_model import Scenario

_logger = getLogger(__name__)


class EventInterrupted(BaseException):
    """
    割り込みの resume_after が next_event / restart だったので、割り込まれたイベントを抜ける

    イベントの完了を待つ処理が、割り込みから戻ったところで送る。そのフレームのイベントの並び
    （メインシナリオのループや、割り込みのイベントのループ）が受け取り、次のイベントへ進むかやり直す。
    イベントの処理のあちこちにある except Exception で止まらないよう、BaseException から作る。
    """

    def __init__(self, mode: str):
        super().__init__(mode)
        self.mode = mode


def _remove_identical(items: List[Any], item: Any) -> None:
    """item そのもの（同じ中身の別のものではなく）をリストから外す"""
    for i, x in enumerate(items):
        if x is item:
            del items[i]
            return


@dataclass(eq=False)  # フレームは中身ではなく、同じものかどうかで比べる
class Frame:
    """
    実行中のシナリオ1つ分。ExecutionContext.frames の一番下がメインシナリオで、割り込みが始まるたびに積む
    """
    scenario: Optional[Scenario] = None
    kind: str = "main"                     # main / interrupt
    started_at: float = field(default_factory=time.time)
    history_id: Any = None                 # scenario_history の記録の ID
    suspended_navigations: Dict[str, Any] = field(default_factory=dict)  # この割り込みで止めた移動（終わったら送り直す）
    triggered_observation: Dict[str, Any] = field(default_factory=dict)  # 割り込みのきっかけになった観測
    wait_for_result: Dict[str, Any] = field(default_factory=dict)        # このシナリオの wait_for の結果
    resume_mode: Optional[str] = None      # 中の割り込みが終わったあと、割り込まれたイベントを抜けるか（next_event / restart）
    event_index: int = 0                   # 実行中のイベントの位置（メインシナリオで使う）
    # このシナリオの終わり方
    exit_status: Optional[Dict[str, Any]] = None  # scenario_exit の {"exit_code": str, "exit_data": dict, ...}
    exit_requested: bool = False           # 残りのイベントを打ち切る（scenario_exit か exit_condition）
    exit_condition_met: bool = False       # exit_condition で打ち切った（exit_events を実行する）
    exit_trigger_events: List[str] = field(default_factory=list)  # exit_condition に合った観測のイベント名
    # exit_condition のプレースホルダーを置き換えたもの (置き換えに使った triggered_observation, 条件の配列)
    resolved_exit_conditions: Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = None
    # 割り込み検知に取らせないもの（割り込み検知は、すべてのフレームの分を見る）
    event_ignores: List[List[str]] = field(default_factory=list)  # 実行中のイベントの ignore_interruptions（入れ子の順）
    reserved_events: Set[str] = field(default_factory=set)        # wait_for などが今待っているイベント名
    upcoming_wait_events: Set[str] = field(default_factory=set)   # このあとの wait_for などが待つイベント名
    wait_scopes: List[List[Set[str]]] = field(default_factory=list, repr=False)  # waits_ahead の入れ子ごとの [外側の予約, 次のイベントが待つイベント名]
    # 実行中のイベントの並び（入れ子の順）: {"events": [...], "idx": 実行中の位置, "prefetch": 次を先読みするか}
    # メインシナリオ・割り込みのイベント、分岐（success / failure など）、include の部品、repeat、random の中身
    cursors: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    left: bool = False                     # 割り込みを出た（あとは後片付けだけ）


@dataclass
class ExecutionContext:
    # 実行中のシナリオの積み重ね。frames[0] がメインシナリオ、その上が割り込み（入れ子の順）
    frames: List[Frame] = field(default_factory=lambda: [Frame()])
    # frames と、各フレームの event_ignores の出し入れを守る。割り込み検知のスレッドが読むので、
    # 読む側はこの中で写しを取ってから見る（ロックを持つのは一瞬だけ）
    _frames_lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    # 会話履歴（LLM 生成用）: [{"actor": "robot1", "text": "こんにちは"}, ...]
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)

    # 時間ベース条件用
    last_utterance_time: Optional[Any] = None
    last_observation_time: Optional[Any] = None
    # 最後に action イベントを始めた時刻（time.time()）。wait_for はこれより前に届いた観測を使わない
    last_action_started_at: Optional[float] = None

    # 生成イベントの実行中の位置（generate イベント内でのプリフェッチ用）
    current_generated_events: Optional[List[Dict[str, Any]]] = None
    current_generated_index: int = -1

    # 先読みのために先に選んでおいた random の候補（イベントの元のデータ id(raw) → choices の番号）
    random_picks: Dict[int, int] = field(default_factory=dict, repr=False)
    # 先読みのために先に決めておいた shuffle の順番（イベントの元のデータ id(raw) → choices の番号の並び）
    shuffle_orders: Dict[int, List[int]] = field(default_factory=dict, repr=False)

    # シナリオの連鎖（メインシナリオが終わったあと、次のシナリオを選ぶときにも読む）
    terminate_main_scenario: bool = False  # 割り込みによりメインシナリオを終了するか
    redirect_scenario_id: Optional[str] = None  # 割り込みのあとに移るシナリオ

    # 実行中の navigation（割り込み時の中断／再開用）: {actor: {"destination": [...], ...}}
    active_navigations: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ---- フレーム ----

    @property
    def main_frame(self) -> Frame:
        """メインシナリオのフレーム（frames[0]）"""
        return self.frames[0]

    # メインシナリオ（割り込み中も変わらない）

    @property
    def current_scenario(self) -> Optional[Scenario]:
        """実行中のメインシナリオ。DB の文書（dict）を入れても Scenario になる"""
        return self.main_frame.scenario

    @current_scenario.setter
    def current_scenario(self, value: Any) -> None:
        self.main_frame.scenario = Scenario.coerce(value) if value is not None else None

    @property
    def current_event_index(self) -> int:
        """メインシナリオで実行中のイベントの位置"""
        return self.main_frame.event_index

    @current_event_index.setter
    def current_event_index(self, value: int) -> None:
        self.main_frame.event_index = value

    @property
    def scenario_start_time(self) -> Optional[datetime.datetime]:
        """メインシナリオを始めた時刻（ローカル時刻）。シナリオがなければ None"""
        if self.main_frame.scenario is None:
            return None
        return datetime.datetime.fromtimestamp(self.main_frame.started_at)

    @scenario_start_time.setter
    def scenario_start_time(self, value: Any) -> None:
        """datetime か time.time() の数値"""
        if value is None:
            value = time.time()
        self.main_frame.started_at = value.timestamp() if hasattr(value, "timestamp") else float(value)

    # 一番内側のシナリオの終わり方（割り込みが終われば、外側のシナリオのものに戻る）

    @property
    def scenario_exit_status(self) -> Optional[Dict[str, Any]]:
        return self.top_frame.exit_status

    @scenario_exit_status.setter
    def scenario_exit_status(self, value: Optional[Dict[str, Any]]) -> None:
        self.top_frame.exit_status = value

    @property
    def exit_requested(self) -> bool:
        return self.top_frame.exit_requested

    @exit_requested.setter
    def exit_requested(self, value: bool) -> None:
        self.top_frame.exit_requested = value

    @property
    def exit_condition_met(self) -> bool:
        return self.top_frame.exit_condition_met

    @exit_condition_met.setter
    def exit_condition_met(self, value: bool) -> None:
        self.top_frame.exit_condition_met = value

    @property
    def exit_trigger_events(self) -> List[str]:
        return self.top_frame.exit_trigger_events

    @exit_trigger_events.setter
    def exit_trigger_events(self, value: List[str]) -> None:
        self.top_frame.exit_trigger_events = list(value or [])

    @property
    def top_frame(self) -> Frame:
        """一番内側の、実行中のシナリオ（割り込み中ならその割り込み。出た割り込みは除く）"""
        with self._frames_lock:
            return next(f for f in reversed(self.frames) if not f.left)

    @property
    def interrupt_frames(self) -> List[Frame]:
        """実行中の割り込み（入れ子の順。出た割り込みは除く）"""
        with self._frames_lock:
            return [f for f in self.frames[1:] if not f.left]

    def outer_frame(self) -> Optional[Frame]:
        """一番内側のフレームの、1つ外側のフレーム（割り込まれたシナリオ）。メインシナリオなら None"""
        with self._frames_lock:
            active = [f for f in self.frames if not f.left]
        return active[-2] if len(active) >= 2 else None

    def push_interrupt(self, subscenario: Any) -> Frame:
        """割り込みを始める（フレームを積む）"""
        frame = Frame(scenario=Scenario.coerce(subscenario), kind="interrupt")
        with self._frames_lock:
            self.frames.append(frame)
        return frame

    def pop_interrupt(self, frame: Frame) -> None:
        """割り込みを終える（フレームを外す）"""
        with self._frames_lock:
            _remove_identical(self.frames, frame)

    @property
    def interrupt_depth(self) -> int:
        """割り込みの深さ（出ていない割り込みの数）"""
        return len(self.interrupt_frames)

    @property
    def is_interrupted(self) -> bool:
        return self.interrupt_depth > 0

    @property
    def triggered_observation(self) -> Dict[str, Any]:
        """一番内側のシナリオのきっかけになった観測（{triggered[...]}）。割り込みが終われば外側のものに戻る"""
        return self.top_frame.triggered_observation

    @triggered_observation.setter
    def triggered_observation(self, value: Dict[str, Any]) -> None:
        self.top_frame.triggered_observation = value if isinstance(value, dict) else {}

    @property
    def wait_for_result(self) -> Dict[str, Any]:
        """一番内側のシナリオの wait_for の結果（{wait_for...}）"""
        return self.top_frame.wait_for_result

    @wait_for_result.setter
    def wait_for_result(self, value: Dict[str, Any]) -> None:
        self.top_frame.wait_for_result = value if isinstance(value, dict) else {}

    # ---- 割り込み検知に取らせないもの（フレームごとに持ち、検知はすべてのフレームの分を見る） ----

    def events_kept_from_interrupts(self) -> Set[str]:
        """どのフレームかの wait_for などが待っている、またはこのあと待つイベント名（その観測は割り込みに使わない）"""
        kept: Set[str] = set()
        for frame in self._frames_snapshot():
            # 予約の集合は書き換えずに差し替えるので、読んでいる最中に変わらない
            kept |= frame.reserved_events | frame.upcoming_wait_events
        return kept

    def ignored_by_running_events(self, scenario_id: str) -> bool:
        """どのフレームかで実行中のイベントの ignore_interruptions に scenario_id があるか"""
        with self._frames_lock:
            ignores = [ignored for frame in self.frames for ignored in frame.event_ignores]
        return any(isinstance(ignored, list) and scenario_id in {str(x) for x in ignored} for ignored in ignores)

    def _frames_snapshot(self) -> List[Frame]:
        with self._frames_lock:
            return list(self.frames)

    @contextmanager
    def ignoring_interruptions(self, ignored: List[str]):
        """ブロックの間、ignored のサブシナリオを割り込ませない（実行中のイベントの ignore_interruptions）"""
        frame = self.top_frame
        with self._frames_lock:
            frame.event_ignores.append(ignored)
        try:
            yield
        finally:
            with self._frames_lock:
                _remove_identical(frame.event_ignores, ignored)

    @contextmanager
    def reserving(self, event_keys):
        """
        ブロックの間、event_keys の観測を割り込み検知に取らせない（wait_for などが待つ間）

        入れ子（until のループ内の wait_for など）でも、抜けるときは外側の予約に戻す。
        抜けるときは、待ち始める前からしていた予約（waits_ahead）のうち、このイベント自身の分も外す。
        """
        frame = self.top_frame
        previous = frame.reserved_events
        frame.reserved_events = set(previous) | set(event_keys)
        try:
            yield
        finally:
            frame.reserved_events = previous
            self.own_wait_finished(frame)

    def raise_if_event_interrupted(self) -> None:
        """
        割り込みから戻ったところで呼ぶ。resume_after が next_event / restart なら EventInterrupted を送って
        割り込まれたイベントを抜ける（印は消す）
        """
        frame = self.top_frame
        if frame.resume_mode:
            mode, frame.resume_mode = frame.resume_mode, None
            raise EventInterrupted(mode)

    @property
    def current_scenario_history_id(self) -> Any:
        """一番内側のシナリオの scenario_history の記録の ID"""
        return self.top_frame.history_id

    @current_scenario_history_id.setter
    def current_scenario_history_id(self, value: Any) -> None:
        self.top_frame.history_id = value

    def begin_scenario(self) -> None:
        """シナリオの実行を始めるときに、前のシナリオの終わり方を消す"""
        main = self.main_frame
        main.exit_status = None
        main.exit_requested = False
        main.exit_condition_met = False
        main.exit_trigger_events = []
        self.terminate_main_scenario = False

    def next_event_to_prefetch(self) -> Optional[Any]:
        """一番内側で実行中のイベントの並びの、次のイベント（先読みの対象）。なければ None"""
        frame = self.top_frame
        if not frame.cursors:
            return None
        cursor = frame.cursors[-1]
        next_idx = cursor["idx"] + 1
        if not cursor["prefetch"] or cursor["idx"] < 0 or next_idx >= len(cursor["events"]):
            return None
        return cursor["events"][next_idx]

    @contextmanager
    def waits_ahead(self, events, prefetch: bool = True):
        """
        イベントを順に実行する間、次のイベント（wait_for / if / until）が待つ観測を割り込み検知に取らせない

        「〜いますか？」のあとの wait_for(face_detected) が、呼びかけの間や
        イベントの切れ目に届いた顔を挨拶の割り込みに取られないようにする。
        reserve_next(idx) を events[idx] の実行前に呼ぶ。抜けるときは外側の予約に戻す。

        events[idx] 自身が待つイベントも、待ち始めるまでは予約しておく（イベントの切れ目で
        取られないように）。待ち終わったら own_wait_finished() で外す（そのあとの分岐の発話の間に
        届いた顔は、割り込みに使ってよい）。
        """
        frame = self.top_frame
        previous = frame.upcoming_wait_events
        scope = [set(previous), set()]
        frame.wait_scopes.append(scope)
        # 実行中の位置（次のイベントの先読みに使う）。repeat は回ごとに先読みするので prefetch=False
        cursor = {"events": events, "idx": -1, "prefetch": prefetch}
        frame.cursors.append(cursor)

        def reserve_next(idx: int) -> None:
            cursor["idx"] = idx
            following = events[idx + 1] if idx + 1 < len(events) else None
            scope[1] = _wait_events_of(following)
            frame.upcoming_wait_events = scope[0] | _wait_events_of(events[idx]) | scope[1]

        try:
            yield reserve_next
        finally:
            # 値の比較で外すと、中身が同じ入れ子の別の記録を外してしまう（終わるときに ValueError になっていた）
            _remove_identical(frame.wait_scopes, scope)
            _remove_identical(frame.cursors, cursor)
            frame.upcoming_wait_events = previous

    def own_wait_finished(self, frame: Optional[Frame] = None) -> None:
        """wait_for などが待ち終わったら、そのイベント自身の分の予約を外す（次のイベントの分は残す）"""
        frame = frame or self.top_frame
        if frame.wait_scopes:
            outer, following = frame.wait_scopes[-1]
            frame.upcoming_wait_events = outer | following

    def save_navigation(self, actor: str, navigation_data: Dict[str, Any]) -> None:
        """navigation の目的地を覚える（割り込み時の再開用）。navigation_data は action_id を含むことがある"""
        if "option" not in navigation_data:
            return
        option = navigation_data["option"]
        destination = (
            option.get("goal")
            or option.get("destination")
            or option.get("navigation")
            or ("dock" if option.get("dock") else None)
            or "unknown"
        )
        self.active_navigations[actor] = {
            "destination": destination,
            "navigation_type": navigation_data.get("type", "normal"),
            "navigation_data": navigation_data,
            "action_id": navigation_data.get("action_id"),
            "timestamp": datetime.datetime.now().isoformat()
        }
        _logger.info(f"Saved navigation destination for {actor}: {destination}")

    def clear_navigation(self, actor: str) -> None:
        """navigation の目的地を忘れる"""
        if actor in self.active_navigations:
            destination = self.active_navigations.pop(actor).get("destination")
            _logger.info(f"Cleared navigation destination for {actor}: {destination}")


def _wait_events_of(event) -> Set[str]:
    """wait_for / if / until が待つイベント名（それ以外のイベントなら空）"""
    if not isinstance(event, (dict, Event)):
        return set()
    event = Event.coerce(event)
    return set(event.condition.keys()) if isinstance(event, WaitingEvent) else set()
