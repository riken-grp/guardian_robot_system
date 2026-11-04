#!/bin/bash

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

if echo "$tmux_sessions" | grep -q "^$filename$"; then
    echo "$filename" already exists
else
    echo "$filename" is launching...
    tmux new -d -s $filename bash -c "cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/chat_monitor/chat_monitor;
                                        node chat-bubble/getData.js"
    echo "sleep: $SLEEP_SEC [s]"
    sleep $SLEEP_SEC
    echo "$filename" started
fi