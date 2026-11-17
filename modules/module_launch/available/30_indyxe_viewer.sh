#!/bin/bash
# ロボットの状態表示・操作画面(indyxe_viewer)を起動する。
# ロボット名・MongoDB(ロボットDB)の接続先・ROSドメインは ~/indy.env の値を使う。
# 画面は http://<このマシン>:${INDYXE_VIEWER_PORT:-8000}/ で開く(認証なし。信頼できるネットワーク内でのみ使用すること)。

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

# MongoDBの接続先は引数、無ければ環境変数から取得する
MONGO_URI=${1:-$MONGO_URI}
MONGO_PORT=${2:-$MONGO_PORT}

: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"
: "${ROBOT_NAME:?ROBOT_NAME is not set. e.g. export ROBOT_NAME=<robot name>}"
: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

# Webページのポート番号(任意。未設定の場合は8000)と、main.py に追加で渡すオプション(任意。e.g. "--battery-qos sensor_data")
INDYXE_VIEWER_PORT=${INDYXE_VIEWER_PORT:-8000}
INDYXE_VIEWER_OPTS=${INDYXE_VIEWER_OPTS:-}

command -v uv >/dev/null || { echo "uv is not installed. see modules/indy_modules/indyxe_viewer/Readme.md" >&2; exit 1; }

if echo "$tmux_sessions" | grep -q "^$filename$"; then
    echo "$filename" already exists
else
    echo "$filename" is launching...
    tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                        cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/indyxe_viewer;
                                        uv run main.py --robot $ROBOT_NAME --web-port $INDYXE_VIEWER_PORT --db-host $MONGO_URI --db-port $MONGO_PORT $INDYXE_VIEWER_OPTS"
    echo "sleep: $SLEEP_SEC [s]"
    sleep $SLEEP_SEC
    echo "$filename" started
fi
