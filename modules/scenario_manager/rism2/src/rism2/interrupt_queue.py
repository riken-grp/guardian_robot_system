"""
Interrupt Queue Manager for RISM2

割り込みシナリオの優先度管理を行うキュークラス
スレッドセーフな実装で、検知スレッドと実行スレッド間の同期をサポート
"""

import heapq
import random
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime


class InterruptPriority:
    """
    シナリオ・割り込みサブシナリオの優先度

    0〜1000 の整数で、大きいほど優先する。0 は「ほかに候補がないときだけ選ぶ」（重み 0）。
    - サブシナリオ: キューにたまった割り込みを実行する順番と、同時に条件が合ったときに選ぶ重み
    - メインシナリオ: 次に実行するシナリオを選ぶときの重み

    目安（docs/SCENARIO_SCHEMA.md）:
        0        ほかに選べるものがないときだけ（待機の埋め草など）
        1〜99    ロボット自身の小さな動き、移動の指示など
        100〜499 あいさつ、音声コマンド、QRコードなど
        500〜999 挙手への反応、音声対話など
        1000     安全・電池の緊急
    範囲外の値は範囲に収め、数値でない値は DEFAULT として扱う。
    """
    MIN = 0
    MAX = 1000
    DEFAULT = 1

    @staticmethod
    def pick(weights: List[float]) -> int:
        """
        priority を重みにして1つ選ぶ（添字を返す）

        重みが正のものがあればその中から重みに比例して選び、priority 0 のものは選ばない。
        全部 0 なら同じ確率で選ぶ。
        """
        if any(w > 0 for w in weights):
            return random.choices(range(len(weights)), weights=weights, k=1)[0]
        return random.randrange(len(weights))

    @staticmethod
    def of(doc: Dict[str, Any], default: int = DEFAULT) -> int:
        """文書の priority（範囲に収めた整数）"""
        priority = doc.get("priority", default) if isinstance(doc, dict) else default
        if isinstance(priority, bool) or not isinstance(priority, (int, float)):
            priority = default
        return max(InterruptPriority.MIN, min(InterruptPriority.MAX, int(priority)))


class InterruptEntry:
    """割り込みエントリー"""

    def __init__(self, priority: int, scenario_id: str, scenario_data: Any,
                 condition: Dict[str, Any], matched_observations: List[Dict[str, Any]] = None,
                 timestamp: float = None):
        """
        初期化

        Args:
            priority: 優先度（1〜1000、大きいほど先に実行）
            scenario_id: シナリオID
            scenario_data: サブシナリオ（Scenario。DB の文書でもよい）
            condition: 条件データ
            matched_observations: マッチした観測データのリスト
            timestamp: トリガー時刻（Unixタイムスタンプ）
        """
        self.priority = priority
        self.scenario_id = scenario_id
        self.scenario_data = scenario_data
        self.condition = condition
        self.matched_observations = matched_observations or []
        self.timestamp = timestamp or time.time()
        self.priority_str = str(priority)

    @property
    def scenario_name(self) -> str:
        data = self.scenario_data
        name = data.get("name") if isinstance(data, dict) else getattr(data, "name", None)
        return name or "Unknown"

    def __lt__(self, other):
        """
        比較演算子（heapqでソートするために必要）
        優先度が大きいほど先、同じ優先度の場合は古いものを先にする
        """
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.timestamp < other.timestamp

    def __repr__(self):
        """文字列表現"""
        scenario_name = self.scenario_name
        timestamp_str = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]
        return f"InterruptEntry(priority={self.priority_str}, scenario={scenario_name}, timestamp={timestamp_str})"


class InterruptQueue:
    """
    割り込みシナリオの優先度キュー（スレッドセーフ）

    優先度順に割り込みシナリオを管理し、
    優先度が高いものから順に取り出す。

    検知スレッドからのadd()と実行スレッドからのget_next()を
    スレッドセーフに処理する。
    """

    def __init__(self):
        """初期化"""
        self._queue = []  # heapqを使った優先度キュー
        self._lock = threading.Lock()  # キューアクセス用ロック
        self._interrupt_event = threading.Event()  # 割り込み追加通知用イベント
        self._pending_observation_ids: Set[str] = set()  # 検知済みだが未処理の観測ID
        self._active_scenario_ids: Set[str] = set()  # 実行中の割り込みシナリオID

    def add(self, priority: int, scenario_id: str, scenario_data: Any,
            condition: Dict[str, Any], matched_observations: List[Dict[str, Any]] = None) -> None:
        """
        割り込みをキューに追加（スレッドセーフ）

        Args:
            priority: 優先度（1〜1000、大きいほど先に実行）
            scenario_id: シナリオID
            scenario_data: シナリオデータ
            condition: 条件データ
            matched_observations: マッチした観測データのリスト
        """
        entry = InterruptEntry(priority, scenario_id, scenario_data, condition, matched_observations)
        with self._lock:
            heapq.heappush(self._queue, entry)
        # キューに追加されたことを通知
        self._interrupt_event.set()

    def get_next(self, above: Optional[int] = None,
                 where: Optional[Callable[[InterruptEntry], bool]] = None) -> Optional[InterruptEntry]:
        """
        次の割り込みを取得（優先度順、スレッドセーフ）

        Args:
            above: 指定すると、優先度がこれより大きいものだけを取り出す（ほかはキューに残す）
            where: 指定すると、これが True になるものだけを取り出す（ほかはキューに残す）

        Returns:
            次のInterruptEntry、キューが空（または条件に合うものがない）場合はNone
        """
        with self._lock:
            if where is None:
                if self._queue and (above is None or self._queue[0].priority > above):
                    return heapq.heappop(self._queue)
                return None
            matches = [e for e in self._queue if (above is None or e.priority > above) and where(e)]
            if not matches:
                return None
            entry = min(matches)
            self._queue.remove(entry)
            heapq.heapify(self._queue)
            return entry

    def has(self, where: Callable[[InterruptEntry], bool]) -> bool:
        """where が True になる割り込みがキューにあるか（スレッドセーフ）"""
        with self._lock:
            return any(where(e) for e in self._queue)

    def scenario_names(self) -> List[str]:
        """キューにある割り込みのサブシナリオ名（優先度の順とは限らない）"""
        with self._lock:
            return [entry.scenario_name for entry in self._queue]

    def clear(self) -> None:
        """キューをクリア（スレッドセーフ）"""
        with self._lock:
            self._queue.clear()
            self._pending_observation_ids.clear()
            self._interrupt_event.clear()

    def is_empty(self) -> bool:
        """
        キューが空かチェック（スレッドセーフ）

        Returns:
            空の場合True
        """
        with self._lock:
            return len(self._queue) == 0

    def __len__(self) -> int:
        """
        キューの長さを取得（スレッドセーフ）

        Returns:
            キュー内の割り込み数
        """
        with self._lock:
            return len(self._queue)

    def add_pending_observation_id(self, obs_id: str) -> None:
        """
        検知済みの観測IDを追加（重複検知防止用）

        Args:
            obs_id: 観測データのID
        """
        with self._lock:
            self._pending_observation_ids.add(obs_id)

    def is_observation_pending(self, obs_id: str) -> bool:
        """
        観測IDが検知済み（未処理）かチェック

        Args:
            obs_id: 観測データのID

        Returns:
            検知済みの場合True
        """
        with self._lock:
            return obs_id in self._pending_observation_ids

    def remove_pending_observation_id(self, obs_id: str) -> None:
        """
        処理済みの観測IDを削除

        Args:
            obs_id: 観測データのID
        """
        with self._lock:
            self._pending_observation_ids.discard(obs_id)

    def pending_observation_ids(self) -> List[str]:
        """検知済み（未処理）の観測IDの一覧（コピー）"""
        with self._lock:
            return list(self._pending_observation_ids)

    def remove_pending_observation_ids(self, obs_ids: List[str]) -> None:
        """
        処理済みの観測IDを一括削除

        Args:
            obs_ids: 観測データのIDリスト
        """
        with self._lock:
            for obs_id in obs_ids:
                self._pending_observation_ids.discard(obs_id)

    def mark_scenario_active(self, scenario_id: str) -> None:
        """
        割り込みシナリオを実行中として登録

        Args:
            scenario_id: シナリオID
        """
        with self._lock:
            self._active_scenario_ids.add(scenario_id)

    def mark_scenario_inactive(self, scenario_id: str) -> None:
        """
        割り込みシナリオの実行中登録を解除

        Args:
            scenario_id: シナリオID
        """
        with self._lock:
            self._active_scenario_ids.discard(scenario_id)

    def is_scenario_active(self, scenario_id: str) -> bool:
        """
        割り込みシナリオが実行中かチェック（実行中の同一割り込みを無視するため）

        Args:
            scenario_id: シナリオID

        Returns:
            実行中の場合True
        """
        with self._lock:
            return scenario_id in self._active_scenario_ids

    def get_status(self) -> Dict[str, Any]:
        """
        キューの現在状態を取得（可視化用、スレッドセーフ）

        Returns:
            キュー状態の辞書:
            {
                "queue_size": int,
                "timestamp": float,
                "pending_observations": int,
                "items": [
                    {
                        "position": int,
                        "priority": str,
                        "priority_value": int,
                        "scenario_id": str,
                        "scenario_name": str,
                        "age_seconds": float,
                        "condition": dict
                    },
                    ...
                ]
            }
        """
        current_time = time.time()
        items = []

        with self._lock:
            sorted_queue = sorted(self._queue)
            pending_count = len(self._pending_observation_ids)

        for position, entry in enumerate(sorted_queue, start=1):
            items.append({
                "position": position,
                "priority": entry.priority_str,
                "priority_value": entry.priority,
                "scenario_id": entry.scenario_id,
                "scenario_name": entry.scenario_name,
                "age_seconds": current_time - entry.timestamp,
                "condition": entry.condition
            })

        return {
            "queue_size": len(items),
            "timestamp": current_time,
            "pending_observations": pending_count,
            "items": items
        }

    def __repr__(self):
        """文字列表現"""
        with self._lock:
            if len(self._queue) == 0:
                return "InterruptQueue(empty)"
            entries_str = "\n  ".join(str(entry) for entry in sorted(self._queue))
            return f"InterruptQueue({len(self._queue)} interrupt(s)):\n  {entries_str}"
