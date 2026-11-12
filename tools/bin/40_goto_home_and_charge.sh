#!/bin/bash

# 目的地座標
X=20.64
Y=-4.3
Ym=-5.2
YAW=0.7   # rad

echo "Sending navigation goal..."

ros2 action send_goal \
  /$ROBOT_NAME/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{
    pose: {
      header: {frame_id: 'map'},
      pose: {
        position: {x: ${X}, y: ${Ym}, z: 0.0},
        orientation: { z: ${YAW}, w: -${YAW} }
      }
    }
  }" \
  --feedback

RESULT=$(ros2 action send_goal \
  /$ROBOT_NAME/navigate_to_pose \
  nav2_msgs/action/NavigateToPose \
  "{
    pose: {
      header: {frame_id: 'map'},
      pose: {
        position: {x: ${X}, y: ${Y}, z: 0.0},
        orientation: { z: -${YAW}, w: ${YAW} }
      }
    }
  }" \
  --feedback)

echo "$RESULT"


RESULT=$(ros2 action send_goal \
  /$ROBOT_NAME/navigate_to_charge \
  nav2_msgs/action/NavigateToPose \
  "{}" \
  --feedback)

echo "$RESULT"

if [ $? -eq 0 ]; then
	python3 ${GUARDIAN_ROBOT_PATH}/tools/bin/41_say_something.py バッテリー充電開始
else
	python3 ${GUARDIAN_ROBOT_PATH}/tools/bin/41_say_something.py バッテリー充電失敗
fi

