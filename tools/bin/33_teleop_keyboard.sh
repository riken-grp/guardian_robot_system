#!/bin/bash
# キーボードでローバを操作する(teleop_twist_keyboard)
# 速度指令を /$ROBOT_NAME/rover/cmd_vel に送る

if [ -z "$ROBOT_NAME" ]; then
    echo "error: ROBOT_NAME is not set"
    exit 1
fi

if ! ros2 pkg prefix teleop_twist_keyboard > /dev/null 2>&1; then
    echo "error: teleop_twist_keyboard is not installed"
    echo "       sudo apt install -y ros-humble-teleop-twist-keyboard"
    exit 1
fi

ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/${ROBOT_NAME}/rover/cmd_vel
