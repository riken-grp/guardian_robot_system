#!/bin/bash

ros2 topic pub /$ROBOT_NAME/rover/bumper_clear std_msgs/msg/UInt8 "data: 1" -1
