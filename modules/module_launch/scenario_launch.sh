#!/bin/bash

# guardian_robot_system のパス、ロボット名、MongoDB の接続先は環境変数から取得する
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"
: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

# シナリオ対象のロボット名（空白区切りで複数指定可）。未設定の場合は ROBOT_NAME を使用する
SCENARIO_ROBOTS=${SCENARIO_ROBOTS:-$ROBOT_NAME}
: "${SCENARIO_ROBOTS:?SCENARIO_ROBOTS (or ROBOT_NAME) is not set. e.g. export ROBOT_NAME=<robot name>}"

echo "SCENARIO_ROBOTS: $SCENARIO_ROBOTS, MONGO_URI: $MONGO_URI, MONGO_PORT: $MONGO_PORT"

tmux new -d -s scenario_manager bash -c "cd $GUARDIAN_ROBOT_PATH/modules/scenario_manager/rism;
                                         python3 main.py --robots $SCENARIO_ROBOTS --host $MONGO_URI --port $MONGO_PORT"
