import json
import os

from evdev import InputDevice, categorize, ecodes, list_devices
from pyindy.mongo import CyberDBWriter

current_input = ""


def monitor_device(device_path):
    global current_input
    device = InputDevice(device_path)
    device_name = device.name
    current_input = ""

    for event in device.read_loop():
        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            if key_event.keystate == key_event.key_down:
                if key_event.keycode == "KEY_ENTER":
                    on_enter_event(device_path, device_name)
                elif key_event.keycode == "KEY_BACKSPACE":
                    current_input = current_input[:-1]
                else:
                    if hasattr(key_event, "keycode") and isinstance(
                        key_event.keycode, list
                    ):
                        keycode = key_event.keycode[0]
                    else:
                        keycode = key_event.keycode
                    if keycode.startswith("KEY_") and len(keycode) == 5:
                        char = keycode[-1].lower()
                        current_input += char


def on_enter_event(device_path, device_name):
    env_mongo_uri = os.getenv("MONGO_URI")
    env_mongo_port = os.getenv("MONGO_PORT")

    if env_mongo_uri is None:
        print("error: failed to get mongo_uri")
        return

    if env_mongo_port is None:
        print("error: failed to get mongo_port")
        return

    global current_input
    if current_input != "":
        try:
            decoded = json.loads(current_input)
            writer = CyberDBWriter(env_mongo_uri, int(env_mongo_port), "tBlackBoard", "event")
            writer.insert(decoded)
        except json.JSONDecodeError as e:
            print(e)
        current_input = ""


def get_devices():
    devices = [InputDevice(path) for path in list_devices()]
    return [device.path for device in devices if "Barcode Reader" in device.name]


if __name__ == "__main__":
    """
    Note: only one Barcode Reader works.
    """
    device = get_devices()
    if len(device) == 0:
        print("No barcode reader is connected")
        quit()

    monitor_device(device[0])
