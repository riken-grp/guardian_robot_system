#!/bin/sh
ACTION_PATH="$(dirname "$0")"

command="sudo -E wpa_cli -a ${ACTION_PATH}/wpa_action.sh"
eval $command
