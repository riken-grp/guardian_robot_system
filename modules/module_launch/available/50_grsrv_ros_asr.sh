#!/bin/bash

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
    #tmux new -d -s $filename apptainer exec --nv $GUARDIAN_ROBOT_PATH/setup/container_image/ros2_12-6-3_on_server.sif \
    tmux new -d -s $filename apptainer exec --nv $GUARDIAN_ROBOT_PATH/setup/container_image/ros2_12-6-3_on_server.sif \
        bash -c "\
        cd $GUARDIAN_ROBOT_PATH/ros2_ws;
        source ~/.bashrc;
        source /opt/ros/humble/setup.bash;
        source install/setup.bash;
        unset ROS_LOCALHOST_ONLY
        ros2 launch ssl_bringup ssl_server.launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT"
    # sleep 5
    echo "$filename" started
fi