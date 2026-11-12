#!/bin/bash

current=$(ros2 topic echo --once /$ROBOT_NAME/rover/battery | grep current | awk '{print $2}')
echo $current

if [ $(echo "$current < 0.01" | bc -l) -eq 1 ]; then
    echo "充電中です"
    echo "move 0.0"
    ros2 topic pub -1 /$ROBOT_NAME/rover/cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.1, y: 0.0, z: 0.0}, angular: { x: 0.0, y: 0.0, z: 0.0}}'
else
    echo "充電中ではありません"
fi

ros2 topic pub /$ROBOT_NAME/robot/action_ctl std_msgs/msg/String "{data: activate nav}" -1
