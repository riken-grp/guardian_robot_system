"""
time_utils.py - タイムゾーン対応のユーティリティモジュール

タイムゾーン設定を一元管理し、timezone-aware な datetime を提供する。
デフォルトは system モードで、既存の動作と後方互換性を維持する。

Usage:
    from rism2.time_utils import now, configure_timezone

    # システムローカル時刻を取得（デフォルト）
    current_time = now()

    # UTC モードに切り替え
    configure_timezone(mode="utc")

    # 明示的なタイムゾーン指定（IANA の名前）
    configure_timezone(mode="explicit", explicit="Asia/Tokyo")
"""

from datetime import datetime, timezone as tz, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo
import logging

_logger = logging.getLogger(__name__)

# グローバルタイムゾーン設定
_timezone: Optional[tzinfo] = None
_timezone_mode: str = "system"


def configure_timezone(mode: str = "system", explicit: Optional[str] = None) -> None:
    """
    グローバルタイムゾーン設定を構成する

    Args:
        mode: タイムゾーンモード
            - "system": システムローカルタイムゾーン（デフォルト）
            - "utc": UTC タイムゾーン
            - "explicit": 明示的なタイムゾーン指定（explicit 引数が必要）
        explicit: mode="explicit" の場合のタイムゾーン名（例: "Asia/Tokyo"）

    Raises:
        ValueError: mode が不正、または mode="explicit" で explicit が未指定の場合
    """
    global _timezone, _timezone_mode

    if mode == "utc":
        _timezone = tz.utc
        _timezone_mode = "utc"
        _logger.info("Timezone configured: UTC")

    elif mode == "explicit":
        if not explicit:
            raise ValueError("explicit timezone name is required when mode='explicit'")
        try:
            _timezone = ZoneInfo(explicit)
        except Exception as e:
            raise ValueError(f"Invalid timezone name: {explicit}") from e
        _timezone_mode = "explicit"
        _logger.info(f"Timezone configured: {explicit}")

    elif mode == "system":
        _timezone = None
        _timezone_mode = "system"
        _logger.info("Timezone configured: system local")

    else:
        raise ValueError(f"Invalid timezone mode: {mode}. Use 'system', 'utc', or 'explicit'")




def now() -> datetime:
    """
    現在時刻を timezone-aware な datetime として取得する

    Returns:
        datetime: 現在時刻（設定されたタイムゾーン付き）
    """
    if _timezone:
        return datetime.now(_timezone)
    # system モード: ローカルタイムゾーン付きで返す
    return datetime.now().astimezone()






