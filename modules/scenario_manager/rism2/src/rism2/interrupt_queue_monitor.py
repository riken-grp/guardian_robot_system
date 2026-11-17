"""interrupt_queue_monitor.py - 割り込みキューの様子を画面に出し、MongoDB に残す"""
from datetime import datetime
from typing import Any, Dict, Optional

from .interrupt_queue import InterruptEntry
from .interrupt_queue_tracker import InterruptQueueTracker
from .interrupt_queue_visualizer import InterruptQueueVisualizer


class InterruptQueueMonitor:
    """
    デバッグ用に割り込みキューを見せる・残す

    visualizer が None なら画面には出さない。tracker は無効（enabled=False）なら何も書かない。
    """

    def __init__(self, visualizer: Optional[InterruptQueueVisualizer], tracker: InterruptQueueTracker):
        self.visualizer = visualizer
        self.tracker = tracker

    def show(self, status: Dict[str, Any]) -> None:
        """キューの状態（InterruptQueue.get_status()）を表示し、保存する"""
        if self.visualizer is not None:
            self.visualizer.display_queue_status(status)
        self.tracker.save_queue_status(status)

    def record_execution(self, entry: InterruptEntry, succeeded: bool) -> None:
        """割り込みを実行したことを残す"""
        self.tracker.record_interrupt_execution(
            scenario_id=entry.scenario_id,
            scenario_name=entry.scenario_name,
            priority=entry.priority,
            priority_str=entry.priority_str,
            added_at=datetime.fromtimestamp(entry.timestamp),
            executed_at=datetime.now(),
            condition=entry.condition,
            status="executed" if succeeded else "failed"
        )
