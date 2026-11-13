#!/bin/bash
# zenoh-bridge-ros2dds を起動する。役割は ZENOH_MODE で指定する（未設定時は ON_ROBOT から決まる）。
#   listen  : 待ち受け側（ロボット側、robodj）。apt で入れた zenoh-bridge-ros2dds を直接起動し、待ち受ける
#             ZENOH_MODE 未設定で ON_ROBOT=1 の場合はこちら
#   connect : 接続側（サーバ側）。コンテナ内の zenoh-bridge-ros2dds で ZENOH_ROBOT_ADDR に接続する
#             ZENOH_MODE 未設定で ON_ROBOT が 1 以外の場合はこちら
# 設定ファイルは setup/ros2/zenoh/ 配下を編集せずに使い、マシンごとの値は環境変数から渡す。

SLEEP_SEC=5
ZENOH_PORT=${ZENOH_PORT:-7447}
ZENOH_DIR="$GUARDIAN_ROBOT_PATH/setup/ros2/zenoh"
SERVER_SIF="$GUARDIAN_ROBOT_PATH/setup/container_image/ros2_12-6-3_on_server.sif"

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"
: "${ROS_DOMAIN_ID:?ROS_DOMAIN_ID is not set. e.g. export ROS_DOMAIN_ID=<domain id>}"

# ROS_DISTRO が無いとブリッジは iron とみなし、humble では ros_discovery_info の扱いを誤る
BRIDGE_ENV=(env "ROS_DISTRO=${ROS_DISTRO:-humble}")

if [ -z "$ZENOH_MODE" ]; then
    if [ "$ON_ROBOT" = "1" ]; then ZENOH_MODE=listen; else ZENOH_MODE=connect; fi
fi

if [ "$ZENOH_MODE" = "listen" ]; then
    BRIDGE_CMD=("${BRIDGE_ENV[@]}" zenoh-bridge-ros2dds -c "$ZENOH_DIR/bridge_robot.json5" -d "$ROS_DOMAIN_ID")
    # ZENOH_LISTEN 未設定時も -l を付ける（付けないと zenoh 既定の 7447 で待ち受け、ZENOH_PORT が効かない）
    BRIDGE_CMD+=(-l "tcp/${ZENOH_LISTEN:-0.0.0.0}:${ZENOH_PORT}")
elif [ "$ZENOH_MODE" = "connect" ]; then
    : "${ZENOH_ROBOT_ADDR:?ZENOH_ROBOT_ADDR is not set. e.g. export ZENOH_ROBOT_ADDR=<robot IP address>}"
    BRIDGE_CMD=("${BRIDGE_ENV[@]}" apptainer exec "$SERVER_SIF"
                zenoh-bridge-ros2dds -c "$ZENOH_DIR/bridge_server.json5" -d "$ROS_DOMAIN_ID"
                -e "tcp/${ZENOH_ROBOT_ADDR}:${ZENOH_PORT}")
else
    echo "ZENOH_MODE must be 'listen' or 'connect' (got: $ZENOH_MODE)"
    exit 1
fi

if echo "$tmux_sessions" | grep -q "^$filename$"; then
    echo "$filename" already exists
else
    echo "$filename" is launching...
    echo "  ${BRIDGE_CMD[*]}"
    tmux new -d -s "$filename" "$(printf '%q ' "${BRIDGE_CMD[@]}")"

    echo "sleep: $SLEEP_SEC [s]"
    sleep $SLEEP_SEC
    echo "$filename" started
fi
