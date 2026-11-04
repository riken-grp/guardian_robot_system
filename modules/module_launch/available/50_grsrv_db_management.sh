#!/bin/bash

ROS_WORKSPACE=ros2_ws
SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

# MongoDBの接続先は引数、無ければ環境変数から取得する
MONGO_URI=${1:-$MONGO_URI}
MONGO_PORT=${2:-$MONGO_PORT}

: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename apptainer exec --nv $GUARDIAN_ROBOT_PATH/setup/container_image/ros2_12-6-3_on_server.sif \
                                      bash -c "\
                                      cd $GUARDIAN_ROBOT_PATH/$ROS_WORKSPACE; 
                                      source ~/.bashrc; 
                                      source /opt/ros/humble/setup.bash;
                                      source install/setup.bash; 
                                      ros2 launch db_management db_management.launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi