"""scenario_history.py - シナリオの実行履歴と会話履歴"""
from collections import deque
from datetime import datetime
from logging import getLogger
from typing import Dict, Any, Optional

from bson import ObjectId


class ScenarioHistory:
    """
    シナリオ実行履歴（scenario_history）の記録と参照。

    会話履歴（dialogue_history）はロボット側（rosWatchdog）が実際に話したときに書くので、ここでは書かない。

    実行したイベントはメモリ（finished_events、最新 N 件）にも残す。
    """

    def __init__(self, scenario_history_collection, finished_queue_length: int = 100):
        self._logger = getLogger(__name__)
        self.scenario_history_db = scenario_history_collection
        self.finished_events = deque([], maxlen=finished_queue_length)

    def add_to_finished_events(self, event: Dict[str, Any]) -> None:
        """
        イベントをfinished_eventsに追加（メモリのみ、recall機能で使用）

        Args:
            event: 実行されたイベントデータ
        """
        try:
            self.finished_events.append(event)
            self._logger.debug(f"Added event to finished_events: actor={event.get('actor', 'unknown')}")
        except Exception as e:
            self._logger.error(f"Failed to add to finished_events: {e}", exc_info=True)

    def start_scenario_in_history(
        self,
        scenario_id: str,
        scenario_name: str,
        is_interruption: bool = False,
        parent_history_id: Optional[str] = None,
        depth: int = 0,
        robot: Optional[str] = None
    ) -> Optional[str]:
        """
        シナリオ開始をscenario_historyに記録

        Args:
            scenario_id: シナリオID
            scenario_name: シナリオ名
            is_interruption: 割り込みシナリオかどうか
            parent_history_id: 割り込まれたシナリオの scenario_history の _id（文字列）。メインシナリオは None
            depth: 割り込みの深さ（メイン 0、割り込み 1、割り込みの中の割り込み 2 ...）
            robot: ロボット名（複数のロボットを区別するため）

        Returns:
            挿入されたレコードのID（ObjectId文字列）
        """
        self._logger.info(
            f"[DEBUG] start_scenario_in_history called: "
            f"scenario_id={scenario_id}, scenario_name={scenario_name}, "
            f"is_interruption={is_interruption}"
        )

        try:
            history_record = {
                "scenario_id": scenario_id,
                "scenario_name": scenario_name,
                "is_interruption": is_interruption,
                "parent_history_id": str(parent_history_id) if parent_history_id else None,
                "depth": depth,
                "robot": robot,
                "start_timestamp": datetime.now(),
                "end_timestamp": None,
                "exit_status": None
            }

            self._logger.info(f"[DEBUG] Inserting history_record: {history_record}")

            result = self.scenario_history_db.insert_one(history_record)

            self._logger.info(
                f"[DEBUG] MongoDB insert result: "
                f"inserted_id={result.inserted_id}, acknowledged={result.acknowledged}"
            )
            self._logger.info(
                f"Started scenario in history: {scenario_name} "
                f"(ID: {scenario_id}, interruption: {is_interruption})"
            )

            return str(result.inserted_id)

        except Exception as e:
            self._logger.error(f"Failed to start scenario in history: {e}", exc_info=True)
            return None

    def finish_scenario_in_history(
        self, history_record_id: str, exit_status: Optional[dict] = None
    ) -> bool:
        """
        シナリオ完了をscenario_historyに記録

        Args:
            history_record_id: scenario_historyのレコードID
            exit_status: シナリオ終了ステータス

        Returns:
            成功した場合True
        """
        self._logger.info(
            f"[DEBUG] finish_scenario_in_history called with "
            f"history_record_id={history_record_id}, exit_status={exit_status}"
        )

        try:
            update_data = {"end_timestamp": datetime.now()}
            if exit_status:
                update_data["exit_status"] = exit_status

            self._logger.info(f"[DEBUG] update_data={update_data}")

            result = self.scenario_history_db.update_one(
                {"_id": ObjectId(history_record_id)},
                {"$set": update_data}
            )

            self._logger.info(
                f"[DEBUG] MongoDB update result: "
                f"matched_count={result.matched_count}, modified_count={result.modified_count}"
            )

            if result.matched_count > 0:
                if exit_status:
                    exit_code = exit_status.get("exit_code", "unknown")
                    self._logger.info(
                        f"Finished scenario in history: {history_record_id} (exit_code={exit_code})"
                    )
                else:
                    self._logger.info(f"Finished scenario in history: {history_record_id}")
                return True
            else:
                self._logger.warning(f"Scenario history record not found: {history_record_id}")
                return False

        except Exception as e:
            self._logger.error(f"Failed to finish scenario in history: {e}", exc_info=True)
            return False
