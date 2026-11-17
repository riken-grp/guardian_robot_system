"""robot_directory.py - シナリオの actor（robot1 など）とロボットの対応、ロボットの状態"""
from logging import getLogger
from typing import Any, Dict

from .database import shared_client


class RobotDirectory:
    """設定の robots から、actor のロボット名や実行状態を引く"""

    def __init__(self, config: Dict[str, Any]):
        self._logger = getLogger(__name__)
        self.config = config

    def _actions(self, robot_config: Dict[str, Any]):
        """そのロボットの Actions コレクション（action_db が無ければ None）"""
        action_db = robot_config.get("action_db", {})
        if not action_db:
            return None
        client = shared_client(action_db.get("host", "localhost"), action_db.get("port", 27017))
        return client[action_db.get("dbname", "tBlackBoard")][action_db.get("col_name", "Actions")]

    @staticmethod
    def _actor_name(actor_id: str, robot_config: Dict[str, Any]) -> str:
        """Actions の actor 欄に書かれる名前（pyindy のマネージャーと同じく robot の name）"""
        return robot_config.get("name", actor_id)

    def get_all_robots_status(self) -> list:
        """
        全ロボットのActionsコレクションを確認し、実行状態を取得

        Returns:
            ロボットのステータスリスト [{"actor_id": "status"}, ...]
            - actor_id: シナリオ内のactor識別子（robot1, robot2, robot3など）
            - status: "running" (status="is_playing") または "waiting" (それ以外)
        """
        actors_status = []
        for actor_id, robot_config in self.config.get("robots", {}).items():
            actor_name = self._actor_name(actor_id, robot_config)
            status = "waiting"
            try:
                actions = self._actions(robot_config)
                if actions is not None and actions.find_one({"actor": actor_name, "status": "is_playing"}):
                    status = "running"
            except Exception as e:
                self._logger.warning(f"Failed to check Actions for {actor_id} ({actor_name}): {e}")
            self._logger.debug(f"Robot {actor_id} ({actor_name}) is {status}")
            actors_status.append({actor_id: status})
        return actors_status

    def cancel_waiting_actions(self) -> None:
        """まだ始まっていない（waiting の）アクションを cancelled にする。RISM を止めるときに使う"""
        for actor_id, robot_config in self.config.get("robots", {}).items():
            actor_name = self._actor_name(actor_id, robot_config)
            try:
                actions = self._actions(robot_config)
                if actions is None:
                    continue
                result = actions.update_many({"actor": actor_name, "status": "waiting"},
                                             {"$set": {"status": "cancelled"}})
                self._logger.info(f"Cancelled {result.modified_count} waiting action(s) for {actor_id} ({actor_name})")
            except Exception as e:
                self._logger.error(f"Failed to cancel waiting actions for {actor_id} ({actor_name}): {e}")
