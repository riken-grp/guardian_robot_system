"""scenario_model.py - シナリオ（メイン／割り込みのサブシナリオ）を表すクラス

シナリオDBの文書（dict）を Scenario にする。項目の既定値はここで決める。
イベントは Event（event_model.py）のリストにする。元の文書は raw に残す。

    Scenario.from_doc(doc)   DB の文書から作る
    Scenario.coerce(x)       dict でも Scenario でも Scenario にする
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .event_model import Event, parse_events
from .interrupt_queue import InterruptPriority

ScenarioLike = Union["Scenario", Dict[str, Any]]


@dataclass(kw_only=True)
class Scenario:
    """メインシナリオとサブシナリオに共通の項目と、サブシナリオだけの項目"""
    id: Any = None  # DB の _id（ObjectId のことも文字列のこともある）
    name: str = ""
    status: str = "active"
    priority: int = InterruptPriority.DEFAULT  # 0〜1000 に収めた値
    condition: Dict[str, Any] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    next_scenarios: List[Any] = field(default_factory=list)
    ignore_interruptions: List[str] = field(default_factory=list)  # 実行中は発動させないサブシナリオのID
    exit_conditions: List[Dict[str, Any]] = field(default_factory=list)  # どれかに合う観測が来たら打ち切る
    exit_events: List[Event] = field(default_factory=list)  # 打ち切ったとき、きっかけによらず実行する
    exit_events_by_event: Dict[str, List[Event]] = field(default_factory=dict)  # 打ち切ったきっかけのイベント名ごとに実行する
    ignore_same_observations: bool = False

    # ---- サブシナリオ（割り込み）だけで使う ----
    resume_after: Any = None  # resume / terminate / next_event / restart（古い書き方の真偽も）。None なら resume
    important: bool = False
    force_interrupt: bool = False
    navigation_interrupt_mode: Optional[str] = None  # None なら important かどうかと設定で決める
    navigation_wait_timeout: float = 30.0
    ignore_after_activated: Optional[float] = None  # 発動してからこの秒数は同じ割り込みを無視する
    interruption_probability: Optional[float] = None  # 発動させる確率。None なら rism_config の値
    tags: List[str] = field(default_factory=list)

    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "Scenario":
        """シナリオDBの文書から作る"""
        def as_list(value):
            return list(value) if isinstance(value, (list, tuple)) else []

        condition = doc.get("condition")
        # exit_condition は条件1つか、条件の配列（どれか1つが合えば打ち切る）
        exit_condition = doc.get("exit_condition")
        exit_conditions = exit_condition if isinstance(exit_condition, list) else [exit_condition]
        # exit_events はイベントの配列か、{イベント名: イベントの配列}
        exit_events = doc.get("exit_events")
        by_event = exit_events if isinstance(exit_events, dict) else {}
        return cls(
            id=doc.get("_id"),
            name=doc.get("name", "") or "",
            status=doc.get("status", "active"),
            priority=InterruptPriority.of(doc),
            condition=condition if isinstance(condition, dict) else {},
            events=parse_events(doc.get("events")),
            next_scenarios=as_list(doc.get("next_scenarios")),
            ignore_interruptions=[str(i) for i in as_list(doc.get("ignore_interruptions"))],
            exit_conditions=[c for c in exit_conditions if isinstance(c, dict) and c],
            exit_events=parse_events(exit_events if isinstance(exit_events, list) else None),
            exit_events_by_event={str(name): parse_events(events) for name, events in by_event.items()
                                  if isinstance(events, list)},
            ignore_same_observations=doc.get("ignore_same_observations") is True,
            resume_after=doc.get("resume_after"),
            important=bool(doc.get("important")),
            force_interrupt=bool(doc.get("force_interrupt")),
            navigation_interrupt_mode=doc.get("navigation_interrupt_mode"),
            navigation_wait_timeout=doc.get("navigation_wait_timeout", 30.0),
            ignore_after_activated=doc.get("ignore_after_activated"),
            interruption_probability=doc.get("interruption_probability"),
            tags=as_list(doc.get("tags")),
            raw=doc,
        )

    @classmethod
    def coerce(cls, value: ScenarioLike) -> "Scenario":
        if isinstance(value, Scenario):
            return value
        if isinstance(value, dict):
            return cls.from_doc(value)
        raise TypeError(f"not a scenario: {value!r}")

    @property
    def id_str(self) -> str:
        return str(self.id) if self.id is not None else ""

    def exit_events_for(self, trigger_events: List[str]) -> List[Event]:
        """打ち切ったきっかけのイベント名に応じて実行するイベント（共通のものが先）"""
        events = list(self.exit_events)
        for name in trigger_events:
            if name in self.exit_events_by_event:
                return events + self.exit_events_by_event[name]
        return events

    @property
    def always_interrupts(self) -> bool:
        """important / force_interrupt（移動を止めて、確率によらず割り込む）"""
        return self.important or self.force_interrupt

    def to_dict(self) -> Dict[str, Any]:
        """元の文書"""
        return dict(self.raw)
