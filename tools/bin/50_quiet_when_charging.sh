#!/bin/bash

while :; do
	current=$(ros2 topic echo --once /$ROBOT_NAME/rover/battery | grep current | awk '{print $2}')
	echo $current
	if [ $(echo "$current < 0.01" | bc -l) -eq 1 ]; then
		echo "Charging! Be quiet";
		"${GUARDIAN_ROBOT_PATH}/tools/bin/20_set_volume.sh" 5% off ;
	else
		echo "Not charging.";
		"${GUARDIAN_ROBOT_PATH}/tools/bin/20_set_volume.sh" 20% off ;
	fi;
	sleep 60;
done
