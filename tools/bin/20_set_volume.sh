#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLAY_WAV=${2:-on}

echo "default_device (before):"
pactl get-default-sink

echo ""
echo "available devices:"
pactl list short sinks | awk '{print $2}'

pacmd set-default-sink alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo
pactl set-sink-volume alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo $1

echo ""
echo "set_device:"
pactl get-default-sink

if [ "$PLAY_WAV" = "on" ]; then
	paplay "$SCRIPT_DIR/tools/volume_check.wav"
fi
