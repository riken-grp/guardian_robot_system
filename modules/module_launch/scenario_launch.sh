#!/bin/bash

# guardian_robot_system のパス、ロボット名、MongoDB の接続先は環境変数から取得する
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"
: "${ROBOT_NAME:?ROBOT_NAME is not set. e.g. export ROBOT_NAME=<robot name>}"
: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

echo "ROBOT_NAME: $ROBOT_NAME, MONGO_URI: $MONGO_URI, MONGO_PORT: $MONGO_PORT"

tmux new -d -s scenario_manager bash -c "cd $GUARDIAN_ROBOT_PATH/modules/scenario_manager/rism;
                                         python3 main.py --robots $ROBOT_NAME --host $MONGO_URI --port $MONGO_PORT"
