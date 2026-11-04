#!/bin/bash

echo module_launch start

# guardian_robot_system のパスは環境変数から取得する
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"

SCRIPT_DIR="$GUARDIAN_ROBOT_PATH/modules/module_launch/enable"

# MongoDB の接続先は環境変数から取得する
: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

echo "MONGO_URI: $MONGO_URI, MONGO_PORT: $MONGO_PORT"

if tmux has-session -t hv_play_audio 2>/dev/null; then
    echo "hv_play_audio already running. skipping module_launch."
    exit 0
fi

for script in "$SCRIPT_DIR"/*.sh;
do
    if [ -f "$script" ]; then
        bash "$script" "$MONGO_URI" "$MONGO_PORT"
    else
      echo No script file in "$SCRIPT_DIR"
    fi
done
echo module_launch completed

echo start hv_watch
tmux has-session -t 00_hv_watch 2>/dev/null \
    && echo "hv_watch already running. skipping." \
    || tmux new-session -d -s 00_hv_watch "$GUARDIAN_ROBOT_PATH/modules/module_launch/rescue_mode/hv_watch.sh ${MONGO_URI} ${MONGO_PORT}"
