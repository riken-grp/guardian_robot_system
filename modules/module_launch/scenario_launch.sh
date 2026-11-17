#!/bin/bash

# シナリオマネージャ（modules/scenario_manager/rism2）を tmux セッション scenario_manager で起動する。
# 接続先は設定DB（rism_configs）。各ロボットの DB の場所は、設定DB の robot_list / demo_list に書いてある。
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"

# シナリオ対象のロボット名（空白区切りで複数指定可）。未設定の場合は ROBOT_NAME を使用する
SCENARIO_ROBOTS=${SCENARIO_ROBOTS:-$ROBOT_NAME}
: "${SCENARIO_ROBOTS:?SCENARIO_ROBOTS (or ROBOT_NAME) is not set. e.g. export ROBOT_NAME=<robot name>}"

# デモの ID（設定DB の demo_list のキー）。未設定の場合は <先頭のロボット名>_demo
first_robot=${SCENARIO_ROBOTS%% *}
SCENARIO_DEMO=${SCENARIO_DEMO:-${first_robot}_demo}

# 設定DB の場所。未設定の場合は MONGO_URI と 9100
RISM_CONFIG_HOST=${RISM_CONFIG_HOST:-$MONGO_URI}
RISM_CONFIG_PORT=${RISM_CONFIG_PORT:-9100}
: "${RISM_CONFIG_HOST:?RISM_CONFIG_HOST (or MONGO_URI) is not set. e.g. export MONGO_URI=<hostname>}"

command -v uv >/dev/null || { echo "uv is not installed. see docs/手順書/サーバマシン構築.md" >&2; exit 1; }

echo "SCENARIO_ROBOTS: $SCENARIO_ROBOTS, SCENARIO_DEMO: $SCENARIO_DEMO, RISM_CONFIG: $RISM_CONFIG_HOST:$RISM_CONFIG_PORT"

tmux new -d -s scenario_manager bash -c "cd $GUARDIAN_ROBOT_PATH/modules/scenario_manager/rism2;
                                         uv run main.py --robots $SCENARIO_ROBOTS --demo $SCENARIO_DEMO --host $RISM_CONFIG_HOST --port $RISM_CONFIG_PORT"
