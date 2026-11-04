#!/bin/bash
# hv_watch.sh - 異常検知時に hv_to_rescue.sh を呼び出す監視スクリプト
#
# 【動作フロー】
#   1. 通信状況・セッション起動状況を定期チェック
#   2. 異常検知時に hv_to_rescue.sh をフォアグラウンドで呼び出す
#   3. hv_to_rescue.sh（→ hv_to_normal.sh）完了後、監視ループを再開する
#
# 【チェック条件の追加方法】
#   1. check_*() 関数を追加し、異常時に trigger_rescue "理由" を呼ぶ
#   2. run_checks() 内に その関数呼び出しを1行追加する
#   それだけでOK。設定値はこのファイル上部の「設定」セクションで管理する。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HV_TO_RESCUE="${SCRIPT_DIR}/hv_to_rescue.sh"

# ============================================================
# 設定
# ============================================================
WATCH_INTERVAL=5                        # 監視間隔 [秒]

# MongoDBの接続先は引数、無ければ環境変数から取得する
# hv_to_rescue.sh / hv_to_normal.sh にも引き継ぐため export する
export MONGO_URI="${1:-${MONGO_URI:-}}"
export MONGO_PORT="${2:-${MONGO_PORT:-}}"
: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"
ROBOT_NAME="${ROBOT_NAME:-}"            # 環境変数から取得

# ============================================================
# 共通処理
# ============================================================
trigger_rescue() {
    local reason="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESCUE triggered: ${reason}"
    bash "${SCRIPT_DIR}/tools/send_slack_msg.sh" "[${ROBOT_NAME:-unknown}] レスキューモードに移行します。理由: ${reason}" || true
    # フォアグラウンドで実行し、通常モード復帰完了まで待機してからループを再開する
    bash "${HV_TO_RESCUE}"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rescue completed. Resuming watch loop..."
    PING_FAIL_COUNT=0
}

log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ============================================================
# チェック関数 (条件を追加する場合はここに関数を追加)
# ============================================================

# pingの応答時間チェック（3連続失敗でレスキュー）
# 宛先はMongoDBが動作しているマシン
PING_TARGET="${MONGO_URI}"
PING_TIMEOUT_MS=1000    # ping応答の閾値 [ms]
PING_FAIL_COUNT=0       # 連続失敗カウンター
PING_FAIL_THRESHOLD=3   # 連続失敗閾値
check_ping() {
    local ping_ms
    ping_ms=$(ping -c 1 -W $((PING_TIMEOUT_MS / 1000 + 1)) "${PING_TARGET}" 2>/dev/null \
        | grep 'time=' | sed 's/.*time=\([0-9.]*\).*/\1/' | awk '{print int($1)}')

    if [ -z "${ping_ms}" ] || [ "${ping_ms}" -gt "${PING_TIMEOUT_MS}" ]; then
        PING_FAIL_COUNT=$((PING_FAIL_COUNT + 1))
        log_info "ping failed (${PING_FAIL_COUNT}/${PING_FAIL_THRESHOLD}): ${PING_TARGET} ${ping_ms:+${ping_ms}ms}"
        if [ "${PING_FAIL_COUNT}" -ge "${PING_FAIL_THRESHOLD}" ]; then
            trigger_rescue "ping to ${PING_TARGET} failed ${PING_FAIL_THRESHOLD} times consecutively"
        fi
    else
        PING_FAIL_COUNT=0
    fi
}

# tmuxセッション停止数チェック
CHECK_SESSIONS="${SCRIPT_DIR}/../check_sessions.sh"
STOPPED_THRESHOLD=3      # 停止セッション数の閾値
check_sessions() {
    local stopped_count
    stopped_count=$(bash "${CHECK_SESSIONS}" 2>/dev/null | grep -c '!!!NOT Running!!!')

    if [ "${stopped_count}" -ge "${STOPPED_THRESHOLD}" ]; then
        trigger_rescue "${stopped_count} sessions are not running (threshold: ${STOPPED_THRESHOLD})"
    fi
}

# MongoDBナビゲーション連続失敗チェック
CHECK_NAV_FAILURES="${SCRIPT_DIR}/tools/check_nav_failures.py"
NAV_FAIL_THRESHOLD=3     # 連続失敗とみなす件数
check_nav_failures() {
    if [ -z "${ROBOT_NAME}" ]; then
        log_info "Warning: ROBOT_NAME not set, skipping nav failure check."
        return
    fi
    local result
    result=$(python3 "${CHECK_NAV_FAILURES}" \
        "${MONGO_URI}" "${MONGO_PORT}" "${ROBOT_NAME}" "${NAV_FAIL_THRESHOLD}" 2>&1)
    local exit_code=$?
    if [ "${exit_code}" -eq 1 ]; then
        trigger_rescue "Navigation failed ${NAV_FAIL_THRESHOLD} times consecutively"
    fi
}

# ============================================================
# メインループ
# ============================================================
run_checks() {
    check_ping
    check_sessions
    check_nav_failures
    # 条件を追加する場合はここに check_xxx を1行追加
}

log_info "hv_watch.sh started."

# 起動時: 直近のナビゲーション結果が failed なら canceled に書き換えて誤検知を防ぐ
if [ -n "${ROBOT_NAME}" ]; then
    init_result=$(python3 "${CHECK_NAV_FAILURES}" --init "${MONGO_URI}" "${MONGO_PORT}" "${ROBOT_NAME}" 2>&1)
fi

while true; do
    run_checks
    sleep "${WATCH_INTERVAL}"
done
