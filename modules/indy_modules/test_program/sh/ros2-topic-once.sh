#!/bin/bash

# ros2 setup script sourced info wrapper
# Usage: first argument is sourced, typically a install/setup.bash file.
# second is name of topic
# third is the timeout value
# Will return first message published, and stderr if topic doesn't exist

source $1
COMMAND="ros2 topic echo $2 --once"
TIMEOUT_DURATION=$3

# Use the timeout command to run the external program
#timeout $TIMEOUT_DURATION $COMMAND 2>&1
timeout $TIMEOUT_DURATION $COMMAND


# Check the exit status of the timeout command
EXIT_STATUS=$?

if [ $EXIT_STATUS -eq 124 ]; then
    echo "The command timed out after $TIMEOUT_DURATION seconds." >&2
elif [ $EXIT_STATUS -ne 0 ]; then
    echo "The command failed with exit status $EXIT_STATUS." >&2
#else
    # echo "The command executed successfully."
fi
