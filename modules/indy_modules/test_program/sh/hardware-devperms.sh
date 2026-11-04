#!/bin/bash

# check if device is in /dev, and optionally its permissions
# (though can be used for any file)
# Usage: first argument is hardware, e.g. /dev/ttyUSB0

# Check if at least the file argument is given
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 [file] [optional: permissions]" >&2
    echo "Example: $0 /dev/null 665" >&2
    exit 1
fi

# Assign the file argument to a variable
FILE=$1

# Check if the file exists. If permissions not specified, this is enough.
if [ ! -e "$FILE" ]; then
    echo "The file does not exist." >&2
    exit 1
elif [ -z "$2" ]; then
    echo "The file exists."
fi

# If permissions argument is provided, check permissions
if [ "$#" -eq 2 ]; then
    PERMISSIONS=$2
    ACTUAL_PERMISSIONS=$(stat -c "%a" "$FILE")

    if [ "$ACTUAL_PERMISSIONS" == "$PERMISSIONS" ]; then
        echo "The file '$FILE' exists and has the expected permissions ($PERMISSIONS)."
        exit 0
    else
        echo "The file '$FILE' does not have the expected permissions ($PERMISSIONS)." >&2
        echo "Actual permissions are $ACTUAL_PERMISSIONS." >&2
        exit 1
    fi
fi
