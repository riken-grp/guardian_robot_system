#!/usr/bin/python3
"""Speaker volume control node (ROS version of 20_set_volume.sh).

Subscribes:
    robot/set_volume (std_msgs/Int32): volume [%], 0-100 (clamped to max_volume)
Publishes:
    robot/volume (std_msgs/Int32, transient local): volume [%] read back from
    PulseAudio after each change (-1 if it could not be read)

The volume is set with ``pactl set-sink-volume <sink> <N>%``.  Note that the
value must have the ``%`` suffix: a bare number is a raw PulseAudio volume
(65536 = 100%), so ``pactl set-sink-volume <sink> 50`` is almost mute.

Parameters:
    sink: PulseAudio sink name (default: the USB speaker of the robot)
    fallback_to_default_sink: use the current default sink when ``sink`` is
        not connected (otherwise the request is rejected)
    set_default_sink: make ``sink`` the default sink (as the shell script did)
    initial_volume: volume set on startup (-1: unchanged)
    max_volume: upper limit of the volume [%]
    play_check_sound / check_sound: play a wav file after a change

pactl is run in a worker thread; when several requests arrive while one is
being applied, only the latest one is applied.  The node must run in the
user session that owns the PulseAudio / PipeWire server (XDG_RUNTIME_DIR).
"""

import os
import re
import subprocess
import threading

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Int32

DEFAULT_SINK = "alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo"
PACTL_TIMEOUT = 5.0


def run(cmd, timeout=PACTL_TIMEOUT):
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return p.returncode, p.stdout, p.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(cmd)} timed out"


def parse_sinks(text):
    """Sink names from ``pactl list short sinks``."""
    sinks = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2:
            sinks.append(cols[1])
    return sinks


def parse_volume_percent(text):
    """Average volume [%] from ``pactl get-sink-volume`` (None if not found)."""
    values = [int(v) for v in re.findall(r"(\d+)%", text)]
    if not values:
        return None
    return round(sum(values) / len(values))


def clamp_volume(value, max_volume=100):
    return max(0, min(int(value), int(max_volume)))


class VolumeController:
    """pactl wrapper (``runner`` is replaceable for testing)."""

    def __init__(self, sink, fallback_to_default_sink=True, set_default_sink=True,
                 runner=run, logger=None):
        self.sink = sink
        self.fallback = fallback_to_default_sink
        self.set_default = set_default_sink
        self.run = runner
        self.logger = logger

    def _warn(self, text):
        if self.logger is not None:
            self.logger.warn(text)

    def resolve_sink(self):
        """Sink to control, or None.  Checked every time (USB hot plug)."""
        code, out, err = self.run(["pactl", "list", "short", "sinks"])
        if code != 0:
            self._warn(f"pactl list failed: {err}")
            return None
        if self.sink and self.sink in parse_sinks(out):
            return self.sink
        if self.fallback:
            self._warn(f"sink '{self.sink}' not found, using the default sink")
            return "@DEFAULT_SINK@"
        self._warn(f"sink '{self.sink}' not found")
        return None

    def set_volume(self, percent):
        """Set the volume; returns the volume read back (None on failure)."""
        sink = self.resolve_sink()
        if sink is None:
            return None
        if self.set_default and sink != "@DEFAULT_SINK@":
            # pactl (not pacmd) also works with PipeWire
            code, _, err = self.run(["pactl", "set-default-sink", sink])
            if code != 0:
                self._warn(f"set-default-sink failed: {err}")
        code, _, err = self.run(["pactl", "set-sink-volume", sink, f"{percent}%"])
        if code != 0:
            self._warn(f"set-sink-volume failed: {err}")
            return None
        return self.get_volume(sink)

    def get_volume(self, sink=None):
        sink = sink or self.resolve_sink()
        if sink is None:
            return None
        code, out, _ = self.run(["pactl", "get-sink-volume", sink])
        return parse_volume_percent(out) if code == 0 else None

    def play(self, wav):
        sink = self.resolve_sink()
        cmd = ["paplay", wav] if sink in (None, "@DEFAULT_SINK@") else [
            "paplay", f"--device={sink}", wav]
        code, _, err = self.run(cmd, timeout=30.0)
        if code != 0:
            self._warn(f"paplay failed: {err}")


class VolumeNode(Node):
    def __init__(self):
        super().__init__("ros_volume")
        self.declare_parameter("sink", DEFAULT_SINK)
        self.declare_parameter("fallback_to_default_sink", True)
        self.declare_parameter("set_default_sink", True)
        self.declare_parameter("initial_volume", -1)
        self.declare_parameter("max_volume", 100)
        self.declare_parameter("play_check_sound", True)
        self.declare_parameter("check_sound", "")

        p = lambda name: self.get_parameter(name).value  # noqa: E731
        self.max_volume = clamp_volume(p("max_volume"), 100)
        self.check_sound = p("check_sound") if p("play_check_sound") else ""
        if self.check_sound and not os.path.isfile(self.check_sound):
            self.get_logger().warn(f"check_sound not found: {self.check_sound}")
            self.check_sound = ""
        self.controller = VolumeController(
            p("sink"),
            fallback_to_default_sink=bool(p("fallback_to_default_sink")),
            set_default_sink=bool(p("set_default_sink")),
            logger=self.get_logger(),
        )
        self.get_logger().info(
            f"sink: {p('sink')}, max_volume: {self.max_volume}, "
            f"check_sound: {self.check_sound or '(none)'}"
        )

        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub = self.create_publisher(Int32, "robot/volume", latched)
        self.sub = self.create_subscription(
            Int32, "robot/set_volume", self.volume_callback, 10
        )

        # worker thread: pactl may take a while, never block the executor
        self._cond = threading.Condition()
        self._request = None
        self._running = True
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

        initial = int(p("initial_volume"))
        if initial >= 0:
            self._submit(clamp_volume(initial, self.max_volume), play=False)
        else:
            self._submit(None, play=False)  # publish the current volume

    def volume_callback(self, msg):
        volume = clamp_volume(msg.data, self.max_volume)
        if volume != msg.data:
            self.get_logger().warn(
                f"volume {msg.data} is out of range, clamped to {volume}"
            )
        self._submit(volume, play=True)

    def _submit(self, volume, play):
        with self._cond:
            self._request = (volume, play)  # only the latest request is kept
            self._cond.notify()

    def _work(self):
        while True:
            with self._cond:
                while self._request is None and self._running:
                    self._cond.wait()
                if not self._running:
                    return
                volume, play = self._request
                self._request = None
            try:
                if volume is None:
                    current = self.controller.get_volume()
                else:
                    current = self.controller.set_volume(volume)
                    self.get_logger().info(f"volume: {volume}% (read back: {current})")
                    if play and self.check_sound and current is not None:
                        self.controller.play(self.check_sound)
                self.pub.publish(Int32(data=-1 if current is None else int(current)))
            except Exception as e:  # keep the worker alive
                self.get_logger().error(f"failed to set the volume: {e}")

    def destroy_node(self):
        with self._cond:
            self._running = False
            self._cond.notify()
        self._worker.join(timeout=PACTL_TIMEOUT + 1.0)
        return super().destroy_node()


def main():
    rclpy.init()
    node = VolumeNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
