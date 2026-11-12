#!/bin/bash

pacmd set-default-source alsa_input.usb-SiF_RASP-ZX__16ch__3339_v10b-00.multichannel-input
pactl set-source-volume alsa_input.usb-SiF_RASP-ZX__16ch__3339_v10b-00.multichannel-input $1
