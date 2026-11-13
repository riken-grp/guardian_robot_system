#!/bin/bash
# rviz2の設定ファイル中の __ROBOT_NAME__ を $ROBOT_NAME に置き換えて起動する

if [ -z "$ROBOT_NAME" ]; then
    echo "error: ROBOT_NAME is not set"
    exit 1
fi

TEMPLATE="$(dirname "$(readlink -f "$0")")/../../modules/indy_modules/rviz2/robot_config.rviz"
CONFIG=$(mktemp --suffix=.rviz)
trap 'rm -f "$CONFIG"' EXIT

sed "s/__ROBOT_NAME__/${ROBOT_NAME}/g" "$TEMPLATE" > "$CONFIG"
rviz2 -d "$CONFIG" "$@"
