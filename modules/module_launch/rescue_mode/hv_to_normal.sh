#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROBOT_NAME="${ROBOT_NAME:-}"
# ping宛先はMongoDBが動作しているマシン（hv_watch.sh から引き継ぐ）
SERVER_NAME="${MONGO_URI:-}"

if [ -z "${ROBOT_NAME}" ]; then
    echo "Error: ROBOT_NAME is not set."
    exit 1
fi

if [ -z "${SERVER_NAME}" ]; then
    echo "Error: MONGO_URI is not set."
    exit 1
fi

# hv_play_audio セッションを確実に削除
while tmux list-sessions 2>/dev/null | grep -q '^hv_play_audio:'; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Killing hv_play_audio session..."
    tmux send-keys -t hv_play_audio C-c 2>/dev/null || true
    sleep 1
done

# MongoDBマシンへのpingの平均値が20ms以下になるまで待機
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for stable connection..."
while true; do
    avg_ms=$(ping -c 5 -q "${SERVER_NAME}" 2>/dev/null \
        | grep 'rtt' | sed 's|.*= [0-9.]*/\([0-9.]*\)/.*|\1|' | awk '{print int($1)}')
    if [ -n "${avg_ms}" ] && [ "${avg_ms}" -le 20 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Connection stable (avg=${avg_ms}ms). Proceeding..."
        break
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Connection unstable (avg=${avg_ms:-N/A}ms). Retrying..."
    sleep 5
done

# 復帰音声を1回だけ再生
aplay "${SCRIPT_DIR}/tools/return_to_normal.wav" 2>/dev/null &

"${GUARDIAN_ROBOT_PATH}/tools/bin/50_cancel_all.py"
sleep 2

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting module_launch.sh..."
${GUARDIAN_ROBOT_PATH}/modules/module_launch/module_launch.sh

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for hv_play_audio session to start..."
sleep 3


CHECK_SESSIONS="${GUARDIAN_ROBOT_PATH}/modules/module_launch/check_sessions.sh"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for sessions to be ready..."
RETRY_COUNT=0
MAX_RETRIES=6
while [ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]; do
    # hv_play_audio が起動しているか確認
    if ! tmux list-sessions 2>/dev/null | grep -q '^hv_play_audio:'; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] hv_play_audio not running. Retrying module_launch.sh... (${RETRY_COUNT}/${MAX_RETRIES})"
        ${GUARDIAN_ROBOT_PATH}/modules/module_launch/module_launch.sh
        sleep 5
        RETRY_COUNT=$((RETRY_COUNT+1))
        continue
    fi
    
    stopped_count=$(bash "${CHECK_SESSIONS}" 2>/dev/null | grep -c '!!!NOT Running!!!')
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopped sessions: ${stopped_count}"
    if [ "${stopped_count}" -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] All sessions ready. Publishing initial pose..."
        break
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sessions not ready. Retrying module_launch.sh... (${RETRY_COUNT}/${MAX_RETRIES})"
    ${GUARDIAN_ROBOT_PATH}/modules/module_launch/module_launch.sh
    sleep 5
    RETRY_COUNT=$((RETRY_COUNT+1))
done

# 暫定で充電ステーションの位置に初期位置をセットしている。必要に応じて変更すること。
source ${GUARDIAN_ROBOT_PATH}/ros2_ws/install/setup.bash
ros2 topic pub -1 /${ROBOT_NAME}/rover/set_initialpose common_msgs/msg/PoseAngle "header:
  stamp:
    sec: 0
    nanosec: 0
  frame_id: ''
position:
  x: 20.6261
  y: -4.726
  z: 0.0
angle: -1.57"

bash "${SCRIPT_DIR}/tools/send_slack_msg.sh" "[${ROBOT_NAME}] 通常モードに戻りました。"
