"""
Interrupt Queue Tracker for RISM2

割り込みキューの状態と履歴をMongoDBに保存するクラス
"""

from typing import Dict, Any, Optional
from datetime import datetime
from pymongo import MongoClient
from pymongo.collection import Collection
from logging import Logger, getLogger


class InterruptQueueTracker:
    """
    割り込みキューのトラッキングクラス

    MongoDBに以下のデータを保存します：
    1. キュー状態（interrupt_queue_status）- 現在のキュー内容
    2. 割り込み履歴（interrupt_history）- 実行された割り込みの記録
    """

    def __init__(self, mongo_client: MongoClient, db_name: str = "tBlackBoard",
                 enabled: bool = True, logger: Optional[Logger] = None):
        """
        初期化

        Args:
            mongo_client: MongoDBクライアント
            db_name: データベース名（デフォルト: tBlackBoard）
            enabled: トラッキングを有効にするか（デフォルト: True）
            logger: ロガー（オプション）
        """
        self.enabled = enabled
        self._logger = logger or getLogger(__name__)

        if not self.enabled:
            self._logger.info("Interrupt queue tracking is disabled")
            self.status_collection = None
            self.history_collection = None
            return

        # コレクションの初期化
        db = mongo_client[db_name]
        self.status_collection: Collection = db.interrupt_queue_status
        self.history_collection: Collection = db.interrupt_history

        self._logger.info(f"Interrupt queue tracker initialized (db: {db_name})")

        # インデックスの作成
        self._create_indexes()

    def _create_indexes(self) -> None:
        """インデックスを作成"""
        if not self.enabled:
            return

        # status collection: timestamp降順（最新を素早く取得）
        self.status_collection.create_index([("timestamp", -1)])

        # history collection: 複数のインデックス
        self.history_collection.create_index([("executed_at", -1)])  # 実行時刻
        self.history_collection.create_index([("priority", 1)])  # 優先度
        self.history_collection.create_index([("scenario_id", 1)])  # シナリオID

        self._logger.debug("Created indexes for interrupt tracking collections")

    def save_queue_status(self, status: Dict[str, Any],
                         low_priority_count: int = 0) -> Optional[str]:
        """
        キュー状態をMongoDBに保存

        Args:
            status: get_status()から取得したキュー状態
            low_priority_count: Low優先度キューのサイズ

        Returns:
            保存されたドキュメントのID（文字列）、無効化されている場合はNone
        """
        if not self.enabled:
            return None

        # ドキュメント作成
        doc = {
            "timestamp": datetime.fromtimestamp(status["timestamp"]),
            "queue_size": status["queue_size"],
            "low_priority_count": low_priority_count,
            "total_count": status["queue_size"] + low_priority_count,
            "items": status["items"]
        }

        # 保存
        try:
            result = self.status_collection.insert_one(doc)
            self._logger.debug(f"Saved queue status: {result.inserted_id}")
            return str(result.inserted_id)
        except Exception as e:
            self._logger.error(f"Failed to save queue status: {e}")
            return None

    def record_interrupt_execution(self, scenario_id: str, scenario_name: str,
                                   priority: int, priority_str: str,
                                   added_at: datetime, executed_at: datetime,
                                   condition: Dict[str, Any],
                                   status: str = "executed") -> Optional[str]:
        """
        割り込み実行を履歴に記録

        Args:
            scenario_id: シナリオID
            scenario_name: シナリオ名
            priority: 優先度レベル
            priority_str: 優先度文字列
            added_at: キューに追加された時刻
            executed_at: 実行された時刻
            condition: 条件
            status: ステータス（executed, cancelled, failed）

        Returns:
            保存されたドキュメントのID（文字列）、無効化されている場合はNone
        """
        if not self.enabled:
            return None

        # 待機時間を計算
        wait_time_ms = int((executed_at - added_at).total_seconds() * 1000)

        # ドキュメント作成
        doc = {
            "scenario_id": scenario_id,
            "scenario_name": scenario_name,
            "priority": priority,
            "priority_str": priority_str,
            "added_at": added_at,
            "executed_at": executed_at,
            "wait_time_ms": wait_time_ms,
            "condition": condition,
            "status": status
        }

        # 保存
        try:
            result = self.history_collection.insert_one(doc)
            self._logger.debug(f"Recorded interrupt execution: {scenario_name} ({priority_str})")
            return str(result.inserted_id)
        except Exception as e:
            self._logger.error(f"Failed to record interrupt execution: {e}")
            return None
