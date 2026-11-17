"""event_model.py - シナリオのイベントを表すクラス

シナリオDBのイベント（dict）を、種類ごとの dataclass にする。
既定値（interruptable は true、type は action など）はここで決め、処理の側では dict のキーを引かない。

    Event.from_dict({"type": "repeat", "times": 2, "subevents": [...]})  -> RepeatEvent
    Event.coerce(x)  dict でも Event でも Event にする

元の dict は raw に残す。履歴への記録や Event Generator には to_dict() を渡す。
ロボットに渡す speak / gesture / navigation / eye / ros_command の中身は dict のまま持つ。
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Type, Union

EventLike = Union["Event", Dict[str, Any]]


@dataclass(frozen=True)
class RepeatPosition:
    """repeat の中で実行しているときの位置"""
    count: int              # 何回目か（1 から）
    variable: str = "rep"   # {変数名} に何回目かを入れる変数名
    subevent_index: int = 0  # subevents の何番目か


@dataclass(kw_only=True)
class Event:
    """イベントに共通の項目"""
    TYPE: ClassVar[str] = ""
    _registry: ClassVar[Dict[str, Type["Event"]]] = {}

    actor: Optional[str] = None
    interruptable: bool = True  # false なら、この間に検知した割り込みは後で実行する
    ignore_interruptions: List[str] = field(default_factory=list)  # この間は発動させないサブシナリオのID
    repeat: Optional[RepeatPosition] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.TYPE:
            Event._registry[cls.TYPE] = cls

    @property
    def type(self) -> str:
        return self.TYPE or str(self.raw.get("type", "action"))

    # ---- 作る ----

    @classmethod
    def from_dict(cls, data: Dict[str, Any], event_type: Optional[str] = None) -> "Event":
        """シナリオDBのイベント（dict）から作る。type が無ければ action"""
        event_type = event_type or data.get("type", "action")
        event_cls = Event._registry.get(event_type, UnknownEvent)
        repeat = None
        if "repeat_count" in data:
            repeat = RepeatPosition(int(data["repeat_count"]), data.get("repeat_variable", "rep"),
                                    int(data.get("repeat_subevent_index", 0)))
        ignores = data.get("ignore_interruptions")
        return event_cls(
            actor=data.get("actor"),
            interruptable=data.get("interruptable", True) is not False,
            ignore_interruptions=list(ignores) if isinstance(ignores, list) else [],
            repeat=repeat,
            raw=data,
            **event_cls._fields_from(data),
        )

    @classmethod
    def _fields_from(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """種類ごとの項目（サブクラスで決める）"""
        return {}

    @classmethod
    def coerce(cls, value: EventLike, event_type: Optional[str] = None) -> "Event":
        """
        dict でも Event でも Event にする

        RepeatEvent.coerce(d) のようにサブクラスから呼ぶと、d の type に関わらずその種類として読む。
        """
        if isinstance(value, Event):
            return value
        if isinstance(value, dict):
            return Event.from_dict(value, event_type or cls.TYPE or None)
        raise TypeError(f"not an event: {value!r}")

    def with_repeat(self, count: int, variable: str, subevent_index: int) -> "Event":
        """repeat の中の位置を付けたコピー"""
        return dataclasses.replace(self, repeat=RepeatPosition(count, variable, subevent_index))

    # ---- 書き出す ----

    def to_dict(self) -> Dict[str, Any]:
        """元の dict（repeat の中なら、その位置を repeat_count などとして加えたもの）"""
        data = dict(self.raw)
        data.setdefault("type", self.type)
        if self.repeat is not None:
            data.update(repeat_count=self.repeat.count, repeat_variable=self.repeat.variable,
                        repeat_subevent_index=self.repeat.subevent_index)
        return data


def parse_events(items: Optional[List[EventLike]]) -> List[Event]:
    """イベントのリストを Event のリストにする（None や dict でない要素は飛ばす）"""
    return [Event.coerce(item) for item in items or [] if isinstance(item, (dict, Event))]


@dataclass(kw_only=True)
class ActionEvent(Event):
    """ロボットに動作をさせる（speak / gesture / navigation / eye / ros_command）"""
    TYPE: ClassVar[str] = "action"
    COMMANDS: ClassVar[tuple] = ("speak", "gesture", "navigation", "eye", "ros_command")

    speak: Optional[Dict[str, Any]] = None
    gesture: Optional[Dict[str, Any]] = None
    navigation: Optional[Dict[str, Any]] = None
    eye: Optional[Dict[str, Any]] = None
    ros_command: Optional[Dict[str, Any]] = None

    @classmethod
    def _fields_from(cls, data):
        return {name: data[name] for name in cls.COMMANDS if isinstance(data.get(name), dict)}

    @property
    def generates(self) -> bool:
        """speak か eye が generate（Event Generator で作る）か"""
        return any(isinstance(cmd, dict) and cmd.get("type") == "generate" for cmd in (self.speak, self.eye))

    @property
    def speak_option(self) -> Dict[str, Any]:
        return (self.speak or {}).get("option", {}) or {}

    @property
    def command_names(self) -> List[str]:
        return [name for name in self.COMMANDS if getattr(self, name) is not None]


@dataclass(kw_only=True)
class CommandEvent(Event):
    """任意のコマンドをロボットで実行する"""
    TYPE: ClassVar[str] = "command_event"
    option: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _fields_from(cls, data):
        return {"option": data.get("option") or {}}


@dataclass(kw_only=True)
class ScenarioExitEvent(Event):
    """シナリオを終える（exit_code で終わり方を決める）"""
    TYPE: ClassVar[str] = "scenario_exit"
    exit_code: Optional[str] = None  # 無ければ success
    exit_data: Dict[str, Any] = field(default_factory=dict)
    next_scenario: Optional[str] = None

    @classmethod
    def _fields_from(cls, data):
        return {"exit_code": data.get("exit_code"), "exit_data": dict(data.get("exit_data") or {}),
                "next_scenario": data.get("next_scenario")}


@dataclass(kw_only=True)
class QueueScenarioEvent(Event):
    """シナリオを予約キューに積む"""
    TYPE: ClassVar[str] = "queue_scenario"
    option: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _fields_from(cls, data):
        return {"option": data.get("option") or {}}


@dataclass(kw_only=True)
class WaitingEvent(Event):
    """観測を待つイベント（wait_for / if / until）に共通の項目。待つ前に gesture / navigation をしてよい"""
    condition: Dict[str, Any] = field(default_factory=dict)
    gesture: Optional[Dict[str, Any]] = None
    navigation: Optional[Dict[str, Any]] = None
    failure: List[Event] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        condition = data.get("condition")
        return {"condition": condition if isinstance(condition, dict) else {},
                "gesture": data.get("gesture") if isinstance(data.get("gesture"), dict) else None,
                "navigation": data.get("navigation") if isinstance(data.get("navigation"), dict) else None,
                "failure": parse_events(data.get("failure"))}


@dataclass(kw_only=True)
class WaitForEvent(WaitingEvent):
    """条件に合う観測を timeout 秒まで待つ"""
    TYPE: ClassVar[str] = "wait_for"
    timeout: Optional[float] = None  # 無ければ executor の default_timeout
    success: List[Event] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        return {**super()._fields_from(data), "timeout": data.get("timeout"),
                "success": parse_events(data.get("success"))}


@dataclass(kw_only=True)
class IfEvent(WaitingEvent):
    """観測を待ち、条件に合えば true、条件のイベントだが中身が違えば false、来なければ failure"""
    TYPE: ClassVar[str] = "if"
    timeout: Optional[float] = None
    true: List[Event] = field(default_factory=list)
    false: List[Event] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        return {**super()._fields_from(data), "timeout": data.get("timeout"),
                "true": parse_events(data.get("true")), "false": parse_events(data.get("false"))}


@dataclass(kw_only=True)
class UntilEvent(WaitingEvent):
    """条件に合う観測が来るまで loop をくり返す（loop_timeout 秒まで）"""
    TYPE: ClassVar[str] = "until"
    loop_timeout: Optional[float] = None
    loop: List[Event] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        return {**super()._fields_from(data), "loop_timeout": data.get("loop_timeout"),
                "loop": parse_events(data.get("loop"))}


@dataclass(kw_only=True)
class RepeatEvent(Event):
    """subevents を times 回くり返す"""
    TYPE: ClassVar[str] = "repeat"
    times: int = 1
    variable: str = "rep"
    subevents: List[Event] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        return {"times": data.get("times", 1), "variable": data.get("variable", "rep"),
                "subevents": parse_events(data.get("subevents"))}


@dataclass(kw_only=True)
class RandomEvent(Event):
    """choices から weights の重みで1つ選んで実行する"""
    TYPE: ClassVar[str] = "random"
    choices: List[List[Event]] = field(default_factory=list)
    weights: Optional[List[float]] = None  # 無ければすべて 1

    @classmethod
    def _fields_from(cls, data):
        return {"choices": [parse_events(choice) for choice in data.get("choices") or []],
                "weights": data.get("weights")}

    def pick_index(self) -> Optional[int]:
        """weights の重みで choices から1つ選ぶ（weights がなければ同じ確率）。選べない（空、weights の数が違う）なら None"""
        weights = self.weights if self.weights is not None else [1] * len(self.choices)
        if not self.choices or len(weights) != len(self.choices):
            return None
        return random.choices(range(len(self.choices)), weights=weights, k=1)[0]


@dataclass(kw_only=True)
class ShuffleEvent(Event):
    """choices（イベント列の集まり）を、順番をシャッフルして全部実行する（random と違い、どれも1回ずつ実行する）"""
    TYPE: ClassVar[str] = "shuffle"
    choices: List[List[Event]] = field(default_factory=list)

    @classmethod
    def _fields_from(cls, data):
        return {"choices": [parse_events(choice) for choice in data.get("choices") or []]}

    def pick_order(self) -> List[int]:
        """choices を実行する順番（choices の番号を並べ替えたもの）"""
        return random.sample(range(len(self.choices)), len(self.choices))



@dataclass(kw_only=True)
class FacePersonEvent(Event):
    """止まったあと、体をその人の方へ回す（観測にある、頭のカメラから見た位置で。首は正面の前提）"""
    TYPE: ClassVar[str] = "face_person"
    instance_id: Any = None           # 例: "{triggered[instance_id]}"。その人の観測だけを使う（省略可）
    min_angle_deg: float = 15.0       # これより小さい角度なら回らない

    @classmethod
    def _fields_from(cls, data):
        return {"instance_id": data.get("instance_id"),
                "min_angle_deg": float(data.get("min_angle_deg", 15.0))}


@dataclass(kw_only=True)
class IncludeEvent(Event):
    """別のシナリオ（サブシナリオでもよい、status は問わない）のイベントを、その場で実行する（部品の使い回し）"""
    TYPE: ClassVar[str] = "include"
    scenario: str = ""  # シナリオかサブシナリオの ID

    @classmethod
    def _fields_from(cls, data):
        return {"scenario": str(data.get("scenario") or "")}


@dataclass(kw_only=True)
class UnknownEvent(Event):
    """知らない種類のイベント（実行せずに飛ばす）"""
