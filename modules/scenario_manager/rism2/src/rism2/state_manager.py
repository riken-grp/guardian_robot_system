"""
StateManager - current_state MongoDB管理モジュール

ScenarioInterpreterから current_state の MongoDB管理責務を分離。
Phase 4 責務分離の一環。
"""

import datetime
from logging import getLogger
from typing import Any, Dict, Optional

from pymongo.collection import Collection

from .database import shared_client


class StateManager:
    """
    current_state MongoDB管理マネージャー

    責務:
    - current_stateのMongoDB管理
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 設定辞書
        """
        self.config = config
        self._logger = getLogger(__name__)

        # MongoDB接続（current_state用）
        self.current_state_collection: Optional[Collection] = None
        self._setup_current_state_db()

    def _setup_current_state_db(self) -> None:
        """current_state用のデータベース接続を設定"""
        host, port = self._resolve_internalstate_host()
        self.current_state_collection = shared_client(host, port)["tBlackBoard"].current_state
        self._logger.debug(
            f"StateManager: current_state DB connection established ({host}:{port})"
        )

    def _resolve_internalstate_host(self):
        """
        internalstate_db接続先を解決する

        優先順位:
        1. config["robots"][first_robot]["internalstate_db"]["host/port"]
        2. config["demo"]["host/port"]
        """
        robots = self.config.get("robots", {})
        if robots:
            first_robot = next(iter(robots.values()))
            internalstate_config = first_robot.get("internalstate_db", {})
            host = internalstate_config.get("host")
            port = internalstate_config.get("port")
            if host and port:
                robot_name = first_robot.get("name", "?")
                self._logger.debug(
                    f"StateManager: Using robot internalstate_db config: robot={robot_name}, {host}:{port}"
                )
                return host, int(port)
        self._logger.warning(
            "StateManager: No internalstate_db config in robot config, "
            "falling back to config['demo']"
        )
        return self.config["demo"]["host"], self.config["demo"]["port"]

    def update_current_state(self, updates: Dict[str, Any]) -> None:
        """
        current_stateを更新（階層構造対応）

        Args:
            updates: 更新するフィールドの辞書（階層構造可能）
                    例: {"scenario": {"status": "is_playing"}}
                    → MongoDB: {"scenario.status": "is_playing"}
        """
        if self.current_state_collection is None:
            self._logger.warning("current_state_collection not initialized")
            return

        # actorsフィールドは完全置換（配列→辞書への変更に対応）
        update_operations = {}
        if "actors" in updates:
            update_operations["actors"] = updates.pop("actors")

        # 階層構造をフラット化（ドット記法に変換）
        if updates:
            flattened = self._flatten_dict(updates)
            update_operations.update(flattened)

        update_operations["last_updated"] = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

        # upsert操作（存在しない場合は作成、存在する場合は更新）
        self.current_state_collection.update_one(
            {"_id": "current_state_singleton"}, {"$set": update_operations}, upsert=True
        )
        self._logger.debug(f"Updated current_state: {update_operations}")

    def get_current_state(self) -> Dict[str, Any]:
        """
        現在の状態を取得

        Returns:
            current_stateの辞書
        """
        if not self.current_state_collection:
            self._logger.warning("current_state_collection not initialized")
            return {}

        state = self.current_state_collection.find_one(
            {"_id": "current_state_singleton"}
        )
        if state:
            state.pop("_id", None)  # _idフィールドを除外
        return state or {}

    def _flatten_dict(
        self, d: Dict[str, Any], parent_key: str = "", sep: str = "."
    ) -> Dict[str, Any]:
        """
        階層的な辞書をフラット化（MongoDB ドット記法用）

        Args:
            d: 階層的な辞書
            parent_key: 親キー（再帰用）
            sep: セパレータ（デフォルト: '.'）

        Returns:
            フラット化された辞書

        Example:
            {"scenario": {"status": "is_playing"}}
            → {"scenario.status": "is_playing"}
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
