#!/bin/bash
# ロボット状態(会話、動作、バッテリー)を監視・記録する(djken)。

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

# MongoDBの接続先は引数、無ければ環境変数から取得する
MONGO_URI=${1:-$MONGO_URI}
MONGO_PORT=${2:-$MONGO_PORT}

: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                    export ROBODJ=True;
                                    export ROBOT_NAME=dj_ken;
                                    ros2 launch robot ros_watchdog_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi
