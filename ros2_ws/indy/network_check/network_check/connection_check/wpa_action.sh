#!/bin/sh

IFNAME=$1
CMD=$2

ACTION_PATH="$(dirname "$0")"

DATE=`date '+%Y-%m-%d %H:%M:%S.%3N'`

echo $DATE, $CMD
command="python3 ${ACTION_PATH}/connection_change.py ${CMD}"
eval $command