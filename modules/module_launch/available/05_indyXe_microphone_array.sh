#!/bin/bash
# マイクアレイ(RASP-ZX 16ch)の音声を取得するノード(microphone_array)を起動する。

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

# ALSAの入力デバイスは引数、無ければ環境変数 MIC_ARRAY_DEVICE から取得する(未設定の場合は plughw:RASPZX16ch.0)
MIC_ARRAY_DEVICE=${1:-${MIC_ARRAY_DEVICE:-plughw:RASPZX16ch.0}}

if echo "$tmux_sessions" | grep -q "^$filename$"; then
    echo "$filename" already exists
else
    echo "$filename" is launching...
    tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                        ros2 launch microphone_array microphone_array.launch.py device:=$MIC_ARRAY_DEVICE"
    echo "sleep: $SLEEP_SEC [s]"
    sleep $SLEEP_SEC
    echo "$filename" started
fi
