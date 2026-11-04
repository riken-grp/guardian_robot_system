#!/bin/bash

SLEEP_SEC=0

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)


if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename bash -c "/home/indy3e/tools/sh/pa_send_audio_server.sh"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi
