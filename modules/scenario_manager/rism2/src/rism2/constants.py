"""constants.py - 共通定数定義モジュール

RISM2 プロジェクト全体で共有する定数を一元管理する。
"""
from enum import Enum

# RISM が観測を受け取った時刻（time.time()）。キャッシュに入れたときに観測に書く（DB には書かない）
RECEIVED_AT_KEY = "rism_received_at"


class _StrEnum(str, Enum):
    """文字列としても使える Enum。比較、ログ、JSON、DB にはそのまま値（"success" など）が出る"""

    def __str__(self) -> str:
        return self.value


class ExitCode(_StrEnum):
    """シナリオの終了コード"""
    SUCCESS = "success"         # 正常完了（メインシナリオのデフォルト）
    FAILURE = "failure"         # 失敗
    CANCELLED = "cancelled"     # キャンセル
    TIMEOUT = "timeout"         # タイムアウト
    RETURN = "return"           # 元のシナリオに戻る（割り込みのデフォルト）
    EXIT_MAIN = "exit_main"     # 元のシナリオを終了
    REDIRECT = "redirect"       # 指定した別シナリオに移る


class NavigationInterruptMode(_StrEnum):
    """移動中に割り込みが来たときの navigation の扱い"""
    PARALLEL = "parallel"                   # 止めずに並行して割り込みを実行
    WAIT = "wait_completion"                # 移動が終わるのを待ってから割り込む
    SUSPEND = "suspend_and_resume"          # 止めて割り込み、終わったら再開


class ResumeAfter(_StrEnum):
    """サブシナリオが終わったあと、元のシナリオをどうするか"""
    RESUME = "resume"           # 割り込まれたところから続ける
    TERMINATE = "terminate"     # 元のシナリオを終える
    NEXT_EVENT = "next_event"   # 割り込まれたイベントを飛ばして次から続ける
    RESTART = "restart"         # 割り込まれたイベントをやり直す


# アクションが取り消された／止められたことを表すステータス
# （RISMは cancelled、pyindy の cancel_all は canceled、ロボットは stop で stopped と書く）
ACTION_CANCELLED_STATUSES = ("cancelled", "canceled", "stopped")
