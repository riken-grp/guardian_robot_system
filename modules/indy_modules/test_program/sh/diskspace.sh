#!/bin/bash

# simple disk space usage checker. returns % used
# Usage: first argument is a string identifying target volume

df -k | grep $1 | awk '{print $5+0}'
