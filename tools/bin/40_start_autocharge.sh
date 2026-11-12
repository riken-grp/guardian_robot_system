#!/bin/bash

ros2 topic pub -1 /$ROBOT_NAME/auto_charge/dock_start std_msgs/msg/Empty "{}"
