#!/bin/bash
# motor_release_tool を起動するスクリプト
# Usage: ./02_motor_release.sh [device_path] [motor_num]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL="${SCRIPT_DIR}/../tools/motor_release_tool"

if [ ! -f "${TOOL}" ]; then
    echo "Error: motor_release_tool not found: ${TOOL}"
    echo "Please build it first:"
    echo "  cd $(dirname ${TOOL})"
    echo "  g++ motor_release_tool.cpp -o motor_release_tool"
    exit 1
fi

echo "Starting motor_release_tool"

"${TOOL}"
