#!/bin/bash

# check if device is listed by lsusb
# Usage: first argument is hardware to be identified as string

RESULT=$(lsusb | grep "$1")

if [ -z "$RESULT" ]; then
    echo "Hardware $1 not found." >&2
    exit 1
else
    echo $RESULT
fi
