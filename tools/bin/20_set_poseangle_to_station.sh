#!/usr/bin/bash

ros2 topic pub /$ROBOT_NAME/rover/set_initialpose common_msgs/msg/PoseAngle "header:
    stamp:
        sec: 0
        nanosec: 0
    frame_id: ''
position:
    x: 20.59
    y: -4.5
    z: 0.0
angle: -1.5708" -1