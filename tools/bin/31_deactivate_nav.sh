#!/bin/bash
ros2 topic pub /$ROBOT_NAME/robot/action_ctl std_msgs/msg/String "{data: deactivate nav}" -1
