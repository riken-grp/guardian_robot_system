"""condition_waiter.py - イベント駆動型観測条件待機クラス

ObservationWatcher のコールバック機構を活用し、ポーリング不要の条件待機を実現する。
"""
import threading
import uuid
from typing import Dict, List, Any, Optional, Callable
from logging import getLogger


class ConditionWaiter:
    """
    ObservationWatcher のコールバック機構を利用して、
    観測データの条件待機をイベント駆動で実現するクラス

    従来のポーリング方式（time.sleep(0.1)の繰り返し）を排除し、
    新しい観測データが到着した時点で即座に条件チェックを行う。

    使用例:
        waiter = ConditionWaiter(scenario_manager.observations)
        watcher.register_callback(waiter)

        result = waiter.wait_for_condition(
            condition={"asr": None},
            timeout=5.0
        )

        if result.matched:
            print(f"Matched: {result.observations}")
        else:
            print("Timeout")
    """

    def __init__(self, observations):
        """
        Args:
            observations: get_recent_observations() を持つもの（ObservationStore）
        """
        self._logger = getLogger(__name__)
        self.observations = observations

        # 待機中の条件を管理
        # {wait_id: WaitRequest}
        self._waiting: Dict[str, "WaitRequest"] = {}
        self._lock = threading.Lock()

        self._logger.info("ConditionWaiter initialized")

    def on_observation(self, observation: Dict[str, Any]) -> None:
        """
        ObservationCallback プロトコルの実装

        新しい観測データが到着した時に ObservationWatcher から呼ばれる。
        待機中の全条件をチェックし、マッチした条件の待機を解除する。

        Args:
            observation: 新しい観測データ
        """
        with self._lock:
            waiting_copy = list(self._waiting.items())

        if not waiting_copy:
            return

        # 最新の観測データを取得（コールバック時点のデータ全体）
        try:
            observations = self.observations.get_recent_observations()
        except Exception as e:
            self._logger.error(f"Failed to get observations: {e}", exc_info=True)
            return

        # 待機中の各条件をチェック
        for wait_id, wait_req in waiting_copy:
            if wait_req.is_completed:
                continue

            try:
                # 条件チェック関数を実行
                is_match, matched_obs = wait_req.check_condition(observations)

                if is_match:
                    self._logger.debug(
                        f"Condition matched for wait_id={wait_id}: "
                        f"{len(matched_obs)} observation(s)"
                    )

                    # マッチした観測データをセットして待機を解除
                    wait_req.set_result(matched=True, observations=matched_obs)

            except Exception as e:
                self._logger.error(
                    f"Error checking condition for wait_id={wait_id}: {e}",
                    exc_info=True
                )

    def wait_for_condition(
        self,
        check_condition: Callable[[Dict[str, List[Dict[str, Any]]]], tuple],
        timeout: float
    ) -> "WaitResult":
        """
        条件が満たされるまで待機（イベント駆動）

        ポーリングを使わず、ObservationWatcher からのコールバック通知で
        条件を検知する。既存の観測データも即座にチェックする。

        Args:
            check_condition: 条件チェック関数
                observations を受け取り (is_match, matched_obs) を返す
            timeout: タイムアウト秒数

        Returns:
            WaitResult オブジェクト（matched, observations を含む）
        """
        wait_id = str(uuid.uuid4())
        wait_req = WaitRequest(check_condition)

        with self._lock:
            self._waiting[wait_id] = wait_req

        self._logger.debug(f"Started waiting for condition (wait_id={wait_id}, timeout={timeout}s)")

        try:
            # 既存の観測データを即座にチェック
            try:
                observations = self.observations.get_recent_observations()
                is_match, matched_obs = check_condition(observations)

                if is_match:
                    self._logger.debug(f"Condition matched immediately (wait_id={wait_id})")
                    wait_req.set_result(matched=True, observations=matched_obs)
                    return WaitResult(matched=True, observations=matched_obs)
            except Exception as e:
                self._logger.error(f"Error in initial condition check: {e}", exc_info=True)

            # イベント駆動待機（コールバックで通知される）
            if wait_req.event.wait(timeout=timeout):
                # 条件マッチで通知された
                result = wait_req.get_result()
                self._logger.debug(
                    f"Condition matched via callback (wait_id={wait_id}, "
                    f"observations={len(result.observations)})"
                )
                return result
            else:
                # タイムアウト
                self._logger.debug(f"Condition wait timed out (wait_id={wait_id})")
                wait_req.set_result(matched=False, observations=[])
                return WaitResult(matched=False, observations=[])

        finally:
            # 待機終了、リストから削除
            with self._lock:
                self._waiting.pop(wait_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            統計情報の辞書
        """
        with self._lock:
            return {
                "waiting_count": len(self._waiting),
                "waiting_ids": list(self._waiting.keys())
            }


class WaitRequest:
    """
    待機リクエストを表すクラス

    条件チェック関数、待機状態、結果を管理する。
    """

    def __init__(self, check_condition: Callable):
        """
        Args:
            check_condition: 条件チェック関数
                observations を受け取り (is_match, matched_obs) を返す
        """
        self.check_condition = check_condition
        self.event = threading.Event()
        self.is_completed = False

        # 結果を格納
        self._result: Optional["WaitResult"] = None
        self._result_lock = threading.Lock()

    def set_result(self, matched: bool, observations: List[Dict[str, Any]]) -> None:
        """
        結果をセットして待機を解除

        Args:
            matched: 条件にマッチしたかどうか
            observations: マッチした観測データのリスト
        """
        with self._result_lock:
            if self.is_completed:
                return

            self._result = WaitResult(matched=matched, observations=observations)
            self.is_completed = True
            self.event.set()

    def get_result(self) -> "WaitResult":
        """
        結果を取得

        Returns:
            WaitResult オブジェクト
        """
        with self._result_lock:
            if self._result is None:
                return WaitResult(matched=False, observations=[])
            return self._result


class WaitResult:
    """
    待機結果を表すクラス
    """

    def __init__(self, matched: bool, observations: List[Dict[str, Any]]):
        """
        Args:
            matched: 条件にマッチしたかどうか
            observations: マッチした観測データのリスト
        """
        self.matched = matched
        self.observations = observations

    def __repr__(self) -> str:
        return f"WaitResult(matched={self.matched}, observations={len(self.observations)})"
