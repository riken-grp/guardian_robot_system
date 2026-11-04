#!/bin/bash

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
    tmux new -d -s $filename bash -c "cd $GUARDIAN_ROBOT_PATH/ros2_ws/indy/mic2sock/mic2sock_ka.rs; cargo run --release"
  # sleep 5
  echo "$filename" started
fi