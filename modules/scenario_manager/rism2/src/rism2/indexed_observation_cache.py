"""indexed_observation_cache.py - イベントキーでインデックス化された観測データキャッシュ"""
import time
from collections import deque
from typing import Dict, List, Any

from .constants import RECEIVED_AT_KEY


class IndexedObservationCache:
    """
    イベントキーでインデックス化された観測データキャッシュ

    従来のdequeによる線形走査（O(n)）を、イベントキーによる
    O(1)検索に改善するためのデータ構造。

    特徴:
    - イベントキーによるO(1)検索
    - 挿入順序の維持（古いデータの自動削除）
    - メモリ効率を考慮した設計

    注意:
    - このクラスはスレッドセーフではない
    - スレッドセーフが必要な場合は外部でロックを使用すること
    """

    def __init__(self, max_size: int = 10000):
        """
        Args:
            max_size: キャッシュの最大サイズ（デフォルト: 10000）
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")

        self.max_size = max_size

        # プライマリインデックス: event_key -> {obs_id: observation}
        # O(1)でイベントキーから観測データを取得・削除
        self.index: Dict[str, Dict[Any, Dict[str, Any]]] = {}

        # 挿入順序維持用: 古いデータの自動削除に使用
        self.insertion_order: deque = deque()

        # IDからイベントキーへのマッピング: 削除時に必要
        self.id_to_event: Dict[Any, str] = {}

        # 統計情報
        self._stats = {
            "total_adds": 0,
            "total_evictions": 0,
            "total_gets": 0,
            "cache_hits": 0,
            "cache_misses": 0
        }

    def add(self, obs: Dict[str, Any]) -> None:
        """
        観測データを追加（O(1)）

        Args:
            obs: 観測データ辞書（"event"と"_id"キーが必須）

        Raises:
            KeyError: "event"キーが存在しない場合
        """
        if "event" not in obs:
            raise KeyError("Observation must have 'event' key")

        event_key = obs["event"]
        obs_id = obs.get("_id")
        # 受け取った時刻（入れ直しのときは、前に受け取った時刻を引き継いだものが入っている）
        obs.setdefault(RECEIVED_AT_KEY, time.time())

        # プライマリインデックスに追加
        if event_key not in self.index:
            self.index[event_key] = {}
        if obs_id is not None:
            self.index[event_key][obs_id] = obs
        else:
            # _idなし観測はイベントキーのみでインデックス（上書き）
            self.index[event_key][id(obs)] = obs

        # 挿入順序を記録（_idがある場合のみ）
        if obs_id is not None:
            self.insertion_order.append(obs_id)
            self.id_to_event[obs_id] = event_key

        # 統計更新
        self._stats["total_adds"] += 1

        # max_size超過時は古いものを削除
        while len(self.insertion_order) > self.max_size:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        """
        最も古いデータを削除（内部メソッド）
        """
        if not self.insertion_order:
            return

        # 最古のIDを取得
        oldest_id = self.insertion_order.popleft()

        # イベントキーを取得
        event_key = self.id_to_event.pop(oldest_id, None)
        if event_key is None:
            return

        # インデックスから削除（O(1)）
        if event_key in self.index:
            self.index[event_key].pop(oldest_id, None)
            if not self.index[event_key]:
                del self.index[event_key]

        self._stats["total_evictions"] += 1

    def get_by_event(self, event_key: str) -> List[Dict[str, Any]]:
        """
        イベントキーで検索（O(1)）

        Args:
            event_key: 検索するイベントキー

        Returns:
            該当する観測データのリスト（見つからない場合は空リスト）
        """
        self._stats["total_gets"] += 1

        obs_dict = self.index.get(event_key)
        if obs_dict:
            self._stats["cache_hits"] += 1
            return list(obs_dict.values())
        else:
            self._stats["cache_misses"] += 1
            return []

    def get_all_unmentioned(self) -> List[Dict[str, Any]]:
        """
        mentioned=False の観測データのみ取得

        Returns:
            mentioned=False の観測データのリスト
        """
        result = []
        for obs_dict in self.index.values():
            for obs in obs_dict.values():
                if not obs.get("mentioned", False):
                    result.append(obs)
        return result

    def update_mentioned(self, obs_ids: List[Any]) -> int:
        """
        指定されたIDの観測データのmentionedフラグをTrueに更新

        Args:
            obs_ids: 更新する観測データのIDリスト

        Returns:
            更新された件数
        """
        updated_count = 0
        obs_id_set = set(obs_ids)

        for obs_dict in self.index.values():
            for obs in obs_dict.values():
                if obs.get("_id") in obs_id_set:
                    obs["mentioned"] = True
                    updated_count += 1

        return updated_count

    def contains(self, obs_id: Any) -> bool:
        """
        指定されたIDの観測データが存在するか確認（O(1)）

        Args:
            obs_id: 確認する観測データのID

        Returns:
            存在する場合True
        """
        return obs_id in self.id_to_event

    def clear(self) -> None:
        """
        キャッシュをクリア
        """
        self.index.clear()
        self.insertion_order.clear()
        self.id_to_event.clear()

    def __len__(self) -> int:
        """
        キャッシュ内の観測データ数を返す
        """
        return len(self.insertion_order)

    def __contains__(self, obs_id: Any) -> bool:
        """
        in演算子のサポート
        """
        return self.contains(obs_id)

    @property
    def event_count(self) -> int:
        """
        ユニークなイベントキーの数を返す
        """
        return len(self.index)

    def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            統計情報の辞書
        """
        return {
            **self._stats,
            "current_size": len(self),
            "max_size": self.max_size,
            "unique_events": self.event_count,
            "hit_rate": (
                self._stats["cache_hits"] / self._stats["total_gets"]
                if self._stats["total_gets"] > 0 else 0.0
            )
        }
