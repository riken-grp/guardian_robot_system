#!/bin/bash

# WAV_FILE="Firebird.wav"
DEVICE="alsa_output.usb-MosArt_MosArt_USB_Audio_Device-00.analog-stereo"

# Infinite loop to continuously play the WAV file
while true; do
    echo "Playing $WAV_FILE"
    paplay --device="$DEVICE" "$1"
    sleep 3
done
