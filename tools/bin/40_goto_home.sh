#!/bin/bash

ros2 topic pub --once /$ROBOT_NAME/rover/goal_pose geometry_msgs/msg/PoseStamped "
header:
  frame_id: 'map'
pose:
  position:
    x: 20.74
    y: -4.5
    z: 0.0
  orientation:
    x: 0.0
    y: 0.0
    z: -0.707
    w: 0.707
"
