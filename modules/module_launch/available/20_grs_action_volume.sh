#!/bin/bash
# スピーカーの音量を ROS (robot/set_volume) から変更する機能(rosVolume)を起動する。

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                    ros2 launch robot volume_launch.py"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi
