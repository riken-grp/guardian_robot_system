#!/bin/bash
echo $ROBOT_NAME
ros2 topic pub $ROBOT_NAME/right_arm/enable std_msgs/msg/Empty -1
ros2 topic pub $ROBOT_NAME/left_arm/enable std_msgs/msg/Empty -1
ros2 topic pub $ROBOT_NAME/motor_control/enable std_msgs/msg/Empty -1


