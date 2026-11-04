#!/bin/bash

# simple network ping with timeout
# Usage: first argument is target machine

# ping -i 0.15 -c 5 $1
ping -i 0.2 -c 5 $1 | awk -F '/' 'END {print $5}'
