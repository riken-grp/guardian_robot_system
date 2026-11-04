#!/bin/bash
# ros2 setup script sourced info wrapper
# Usage: first argument is sourced, typically a install/setup.bash file.
# second is either "topic" or "node",
# third argument is the name of the topic or node.
# Will return information about the item (to stdout) or if node doesn't exist, stderr
source $1
#echo "ROS domain id:"
#echo $ROS_DOMAIN_ID
ros2 $2 info $3
