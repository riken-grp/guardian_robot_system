"""
Time-Based Condition Module for RISM2

時間ベースの割り込み条件を処理するモジュール
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional
from logging import Logger, getLogger


class TimeBasedConditionType(Enum):
    """時間ベース条件のタイプ"""
    ELAPSED = "elapsed"      # 経過時間（シナリオ開始から）
    ABSOLUTE = "absolute"    # 絶対時刻
    TIMEOUT = "timeout"      # タイムアウト（特定トリガーから）


class TimeBasedCondition:
    """
    時間ベース条件クラス

    3つのタイプをサポート：
    1. elapsed: シナリオ開始からの経過時間
    2. absolute: 特定の時刻
    3. timeout: 特定のトリガーからの経過時間
    """

    def __init__(self, condition_data: Dict[str, Any], logger: Optional[Logger] = None):
        """
        初期化

        Args:
            condition_data: YAML条件データの "time_based" セクション
            logger: ロガー（オプション）

        Raises:
            ValueError: 不正な条件データの場合
        """
        self._logger = logger or getLogger(__name__)

        # 条件タイプの解析
        try:
            self.type = TimeBasedConditionType(condition_data["type"])
        except KeyError:
            raise ValueError("time_based condition must have 'type' field")
        except ValueError:
            raise ValueError(f"Invalid time_based type: {condition_data.get('type')}")

        # once制御: 一度発動したら再発動させない（デフォルト: False で後方互換性維持）
        self.once = condition_data.get("once", False)
        self._triggered = False
        self._trigger_time: Optional[datetime] = None

        # reset_after_seconds: 指定秒数後に発動状態をリセット（オプション）
        self.reset_after_seconds: Optional[float] = condition_data.get("reset_after_seconds")
        if self.reset_after_seconds is not None:
            try:
                self.reset_after_seconds = float(self.reset_after_seconds)
                if self.reset_after_seconds < 0:
                    self._logger.warning(f"Negative reset_after_seconds: {self.reset_after_seconds}, ignoring")
                    self.reset_after_seconds = None
            except (ValueError, TypeError):
                self._logger.warning(f"Invalid reset_after_seconds value: {condition_data.get('reset_after_seconds')}, ignoring")
                self.reset_after_seconds = None

        # タイプ別の初期化
        if self.type == TimeBasedConditionType.ELAPSED:
            self._init_elapsed(condition_data)
        elif self.type == TimeBasedConditionType.ABSOLUTE:
            self._init_absolute(condition_data)
        elif self.type == TimeBasedConditionType.TIMEOUT:
            self._init_timeout(condition_data)

    def _init_elapsed(self, condition_data: Dict[str, Any]) -> None:
        """経過時間条件の初期化"""
        try:
            self.seconds = float(condition_data["seconds"])
            if self.seconds < 0:
                self._logger.warning(f"Negative seconds for elapsed condition: {self.seconds}")
                self.seconds = 0
        except KeyError:
            raise ValueError("elapsed condition must have 'seconds' field")
        except (ValueError, TypeError):
            raise ValueError(f"Invalid seconds value: {condition_data.get('seconds')}")

    def _init_absolute(self, condition_data: Dict[str, Any]) -> None:
        """絶対時刻条件の初期化"""
        if "time" in condition_data:
            # HH:MM:SS形式（時刻のみ）
            try:
                self.target_time = datetime.strptime(
                    condition_data["time"], "%H:%M:%S"
                ).time()
                self.target_datetime = None
            except ValueError:
                raise ValueError(f"Invalid time format: {condition_data['time']} (expected HH:MM:SS)")

        elif "datetime" in condition_data:
            # YYYY-MM-DD HH:MM:SS形式（日時）
            try:
                self.target_datetime = datetime.strptime(
                    condition_data["datetime"], "%Y-%m-%d %H:%M:%S"
                )
                self.target_time = None
            except ValueError:
                raise ValueError(f"Invalid datetime format: {condition_data['datetime']} (expected YYYY-MM-DD HH:MM:SS)")

        else:
            raise ValueError("absolute condition must have either 'time' or 'datetime' field")

    def _init_timeout(self, condition_data: Dict[str, Any]) -> None:
        """タイムアウト条件の初期化"""
        try:
            self.trigger = condition_data["trigger"]
            if self.trigger not in ["last_utterance", "last_observation", "scenario_start"]:
                raise ValueError(f"Invalid trigger type: {self.trigger}")
        except KeyError:
            raise ValueError("timeout condition must have 'trigger' field")

        try:
            self.seconds = float(condition_data["seconds"])
            if self.seconds < 0:
                self._logger.warning(f"Negative seconds for timeout condition: {self.seconds}")
                self.seconds = 0
        except KeyError:
            raise ValueError("timeout condition must have 'seconds' field")
        except (ValueError, TypeError):
            raise ValueError(f"Invalid seconds value: {condition_data.get('seconds')}")

    def check(self, context: Dict[str, Any]) -> bool:
        """
        条件チェック

        Args:
            context: チェックコンテキスト（タイムスタンプを含む）
                {
                    "scenario_start_time": datetime or None,
                    "last_utterance_time": datetime or None,
                    "last_observation_time": datetime or None
                }

        Returns:
            条件が成立する場合True、そうでない場合False
        """
        # once制御: 発動済みの場合
        if self.once and self._triggered:
            # reset_after_seconds が設定されている場合、経過時間をチェック
            if self.reset_after_seconds is not None and self._trigger_time is not None:
                elapsed = (datetime.now() - self._trigger_time).total_seconds()
                if elapsed >= self.reset_after_seconds:
                    self._logger.debug(
                        f"Auto-reset triggered after {elapsed:.1f}s "
                        f"(reset_after_seconds={self.reset_after_seconds})"
                    )
                    self.reset()
                else:
                    self._logger.debug(
                        f"Once condition already triggered, returning False "
                        f"(will reset in {self.reset_after_seconds - elapsed:.1f}s)"
                    )
                    return False
            else:
                self._logger.debug("Once condition already triggered, returning False")
                return False

        # 実際の条件チェック
        result = self._do_check(context)

        # once=True で条件成立した場合、発動状態を記録
        if result and self.once and not self._triggered:
            self._triggered = True
            self._trigger_time = datetime.now()
            self._logger.debug(f"Once condition triggered at {self._trigger_time}")

        return result

    def _do_check(self, context: Dict[str, Any]) -> bool:
        """
        実際の条件チェック（内部メソッド）

        Args:
            context: チェックコンテキスト

        Returns:
            条件が成立する場合True、そうでない場合False
        """
        if self.type == TimeBasedConditionType.ELAPSED:
            return self._check_elapsed(context)
        elif self.type == TimeBasedConditionType.ABSOLUTE:
            return self._check_absolute(context)
        elif self.type == TimeBasedConditionType.TIMEOUT:
            return self._check_timeout(context)
        else:
            self._logger.error(f"Unknown time_based condition type: {self.type}")
            return False

    def _check_elapsed(self, context: Dict[str, Any]) -> bool:
        """
        経過時間条件のチェック

        Args:
            context: チェックコンテキスト

        Returns:
            シナリオ開始から指定秒数経過している場合True
        """
        start_time = context.get("scenario_start_time")

        if start_time is None:
            self._logger.debug("scenario_start_time not available for elapsed condition")
            return False

        elapsed = (datetime.now() - start_time).total_seconds()
        result = elapsed >= self.seconds

        if result:
            self._logger.debug(f"Elapsed condition met: {elapsed:.1f}s >= {self.seconds}s")

        return result

    def _check_absolute(self, context: Dict[str, Any]) -> bool:
        """
        絶対時刻条件のチェック

        Args:
            context: チェックコンテキスト

        Returns:
            現在時刻が指定時刻を過ぎている場合True
        """
        now = datetime.now()

        if self.target_time is not None:
            # 時刻のみの比較
            current_time = now.time()
            result = current_time >= self.target_time

            if result:
                self._logger.debug(f"Absolute time condition met: {current_time} >= {self.target_time}")

        else:
            # 日時の完全比較
            result = now >= self.target_datetime

            if result:
                self._logger.debug(f"Absolute datetime condition met: {now} >= {self.target_datetime}")
            elif self.target_datetime < now:
                self._logger.warning(f"Target datetime is in the past: {self.target_datetime}")

        return result

    def _check_timeout(self, context: Dict[str, Any]) -> bool:
        """
        タイムアウト条件のチェック

        Args:
            context: チェックコンテキスト

        Returns:
            トリガー時刻から指定秒数経過している場合True
        """
        # トリガー時刻の取得
        trigger_time = None

        if self.trigger == "last_utterance":
            trigger_time = context.get("last_utterance_time")
        elif self.trigger == "last_observation":
            trigger_time = context.get("last_observation_time")
        elif self.trigger == "scenario_start":
            trigger_time = context.get("scenario_start_time")

        if trigger_time is None:
            self._logger.debug(f"Trigger time '{self.trigger}' not available for timeout condition")
            return False

        elapsed = (datetime.now() - trigger_time).total_seconds()
        result = elapsed >= self.seconds

        if result:
            self._logger.debug(f"Timeout condition met: {self.trigger} {elapsed:.1f}s >= {self.seconds}s")

        return result

    def reset(self) -> None:
        """
        発動状態をリセット

        once=True の条件が発動済みの場合、再度発動可能にする。
        シナリオ切り替え時などに呼び出す。
        """
        self._triggered = False
        self._trigger_time = None
        self._logger.debug("TimeBasedCondition reset")

    def __repr__(self) -> str:
        """文字列表現"""
        once_info = ""
        if self.once:
            triggered_info = ", triggered" if self._triggered else ""
            reset_info = f", reset_after={self.reset_after_seconds}s" if self.reset_after_seconds else ""
            once_info = f", once=True{triggered_info}{reset_info}"

        if self.type == TimeBasedConditionType.ELAPSED:
            return f"TimeBasedCondition(elapsed: {self.seconds}s{once_info})"
        elif self.type == TimeBasedConditionType.ABSOLUTE:
            if self.target_time:
                return f"TimeBasedCondition(absolute time: {self.target_time}{once_info})"
            else:
                return f"TimeBasedCondition(absolute datetime: {self.target_datetime}{once_info})"
        elif self.type == TimeBasedConditionType.TIMEOUT:
            return f"TimeBasedCondition(timeout: {self.trigger} + {self.seconds}s{once_info})"
        else:
            return f"TimeBasedCondition(unknown type: {self.type})"


# ヘルパー関数（後方互換性のため）


