#!/bin/bash


# Infinite loop and waits for 5 secs
while true; do
    parec --format=s16le --channels=1 --rate=16000 --raw --latency=1 --process-time=320 --device=alsa_output.usb-MosArt_MosArt_USB_Audio_Device-00.analog-stereo.monitor | dd bs=320 | nc 192.168.5.38 5660
    echo "Audio send exited/failed. Restarting in 5 seconds..."
    sleep 5
done

