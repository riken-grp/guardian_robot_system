#!/bin/bash

# guardian_robot_system のパスは環境変数から取得する
: "${GUARDIAN_ROBOT_PATH:?GUARDIAN_ROBOT_PATH is not set. e.g. export GUARDIAN_ROBOT_PATH=<guardian_robot_system path>}"

SCRIPT_DIR="$GUARDIAN_ROBOT_PATH/modules/module_launch/enable"

tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

for file in "$SCRIPT_DIR"/*.sh;
do
    if [ -f "$file" ]; then
        session_name=$(basename "$file" .sh)

        if echo "$tmux_sessions" | grep -q "^$session_name$"; then
          echo Running: "$session_name"
        else
          echo !!!NOT Running!!!: "$session_name"
        fi
    else
      echo No script file in "$SCRIPT_DIR"
    fi
done