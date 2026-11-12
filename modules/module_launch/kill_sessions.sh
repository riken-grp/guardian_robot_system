#!/bin/bash

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping module_launch sessions..."

# hv_watchセッションが存在する場合は先に停止
HV_WATCH_SESSION="00_hv_watch"
if tmux has-session -t "${HV_WATCH_SESSION}" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sent Ctrl+C to session: ${HV_WATCH_SESSION}"
    tmux send-keys -t "${HV_WATCH_SESSION}" C-c
    sleep 2
fi

# guardian_robot_system のパスは環境変数から取得する
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"

MODULE_ENABLE_DIR="${GUARDIAN_ROBOT_PATH}/modules/module_launch/enable"
for script in "${MODULE_ENABLE_DIR}"/*.sh;
do
    session_name="$(basename "${script}" .sh)"
    tmux send-keys -t "${session_name}" C-c 2>/dev/null \
        && echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sent Ctrl+C to session: ${session_name}" \
        || true
done
tmux send-keys -t scenario C-c 2>/dev/null || true
"${GUARDIAN_ROBOT_PATH}/tools/bin/50_cancel_all.py"

echo kill_sessions completed