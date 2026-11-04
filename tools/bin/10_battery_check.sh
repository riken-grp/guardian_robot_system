#!/bin/bash
TARGET="02_indyXe_rover_base"

if tmux ls 2>/dev/null | grep -q "$TARGET"; then
    ros2 topic echo --once $ROBOT_NAME/rover/battery
else
    ${GUARDIAN_ROBOT_PATH}/modules/module_launch/rescue_mode/tools/battery_check_tool
fi