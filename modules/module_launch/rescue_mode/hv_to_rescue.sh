#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOTOR_RELEASE_TOOL_FOR_RESCUE="${SCRIPT_DIR}/tools/motor_release_tool_for_rescue"
HV_TO_NORMAL="${SCRIPT_DIR}/hv_to_normal.sh"

SESSIONS_STOP_INTERVAL=20  # セッション停止処理実行間隔 [秒]

# ============================================================
# module_launch.sh で起動したセッション停止処理
# ============================================================
stop_module_launch_sessions() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping module_launch sessions..."
    MODULE_ENABLE_DIR="${GUARDIAN_ROBOT_PATH}/modules/module_launch/enable"
    for script in "${MODULE_ENABLE_DIR}"/*.sh;
    do
        session_name="$(basename "${script}" .sh)"
        tmux send-keys -t "${session_name}" C-c 2>/dev/null \
            && echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sent Ctrl+C to session: ${session_name}" \
            || true
    done
    tmux send-keys -t scenario C-c 2>/dev/null || true
    50_cancel_all.py
}

# --------------------------------------------------------
# 1. module_launch.sh で起動したセッションを停止(初回)
# --------------------------------------------------------
stop_module_launch_sessions
sleep 3

# --------------------------------------------------------
# 2. セッション停止処理をバックグラウンドで定期実行
# --------------------------------------------------------
stop_sessions_loop_pid=""

# 終了時にセッション停止処理の定期実行を停止
stop_sessions_loop_cleanup() {
    if [[ -n $stop_sessions_loop_pid \
        && $stop_sessions_loop_pid =~ ^[0-9]+$ ]]; then
        kill "${stop_sessions_loop_pid}" 2>/dev/null || true
        wait "${stop_sessions_loop_pid}" 2>/dev/null || true
    fi
}

trap stop_sessions_loop_cleanup EXIT

(
    while true; do
        stop_module_launch_sessions
        sleep "${SESSIONS_STOP_INTERVAL}"
    done
) &
stop_sessions_loop_pid=$!

# --------------------------------------------------------
# 3. レスキューモード開始: 音声ループ再生
# --------------------------------------------------------
tmux new -d -s hv_play_audio "bash -c '${SCRIPT_DIR}/scripts/01_play_loop_audio_msg.sh'"

# slack通知（充電ステーションへの誘導を依頼）
bash "${SCRIPT_DIR}/tools/send_slack_msg.sh" "[${ROBOT_NAME:-unknown}] レスキューモードに入りました。充電ステーションへの誘導をお願いします。"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rescue mode started. Monitoring battery current..."

# --------------------------------------------------------
# 4. タイヤ解放 + 充電開始（電流値が0以下）を検知したら通常モードに復帰
# --------------------------------------------------------
# motor_release_tool_for_rescueを起動
if [ ! -f "${MOTOR_RELEASE_TOOL_FOR_RESCUE}" ]; then
    echo "Error: motor_release_tool_for_rescue not found: ${MOTOR_RELEASE_TOOL_FOR_RESCUE}"
    echo "Please build it first:"
    echo "  cd $(dirname ${MOTOR_RELEASE_TOOL_FOR_RESCUE})"
    echo "  g++ motor_release_tool_for_rescue.cpp -o motor_release_tool_for_rescue"
    exit 1
fi

echo "Starting motor_release_tool_for_rescue"

"${MOTOR_RELEASE_TOOL_FOR_RESCUE}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Charging detected. Stopping session-kill loop..."
# バックグラウンドのセッション停止ループを停止（hv_to_normalで新規セッション起動するため）
stop_sessions_loop_cleanup
wait $! 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Calling hv_to_normal..."
# 充電検知の発話（「充電状態に入りました。セルフチェックを開始します。」）
aplay "${SCRIPT_DIR}/tools/charging_detected.wav" 2>/dev/null
# exec で現在のプロセスを置き換え（バックグラウンドプロセス残存防止）
exec bash "${HV_TO_NORMAL}"