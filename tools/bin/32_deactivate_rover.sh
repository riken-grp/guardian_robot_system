#!/bin/bash
ros2 topic pub /$ROBOT_NAME/rover/motor_release std_msgs/msg/UInt8 "{data: 1}" -1


