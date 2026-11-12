#!/usr/bin/env bash

#DEVICE="alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo.monitor"
DEVICE="${AUDIO_SEND_DEVICE:-$(pactl get-default-sink)}.monitor"
EXECUTABLE=("$GUARDIAN_ROBOT_PATH/modules/indy_modules/pa_send_audio_server/bin/pa_send_audio_server" 0.0.0.0 7777 "$DEVICE")

# Error codes that require user interaction before retry
WAIT_FOR_KEY_CODES=(1)

# Function to check if a value is in an array
contains() {
    local value="$1"
    shift
    for item in "$@"; do
        [[ "$item" == "$value" ]] && return 0
    done
    return 1
}

while true; do
    echo "Running $EXECUTABLE..."
    "${EXECUTABLE[@]}"
    EXIT_CODE=$?

    echo "Program exited with code: $EXIT_CODE"

    if [[ $EXIT_CODE -eq 0 ]]; then
        echo "PulseAudio server exited normally. Restarting. Use Ctrl-C to exit loop."
        continue
    fi

    if contains "$EXIT_CODE" "${WAIT_FOR_KEY_CODES[@]}"; then
        echo "Error code $EXIT_CODE. Probably init or hardware error (see messages above)."
        read -n 1 -s -r -p "Press any key to retry, or press Ctrl-C to exit loop."
        echo
    fi

done
