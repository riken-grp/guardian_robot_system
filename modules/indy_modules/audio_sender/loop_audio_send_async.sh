#!/bin/bash

PROGRAM="./bin/pa_send_audio"
REMOTE="192.168.0.38"
PORT=5660
# DEVICE="alsa_output.usb-MosArt_MosArt_USB_Audio_Device-00.analog-stereo.monitor"

# Check if the program exists and is executable
if [ ! -x "$PROGRAM" ]; then
    echo "Error: Program '$PROGRAM' does not exist or is not executable." >&2
    echo "If not compiled, compile with 'gcc -o bin/pa_send_audio_async src/pa_send_audio_async.c -lpulse'"
    exit 1
fi

# Infinite loop and waits for 5 secs
while true; do
    "$PROGRAM" "$REMOTE" "$PORT" 0
    echo "Audio send exited/failed. Restarting in 5 seconds..."
    sleep 5
done

