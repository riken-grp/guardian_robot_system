#!/usr/bin/python3
"""Play audio received on a topic with the robot speaker, as it is (pass-through).

Subscribes:
    robot/play_audio (ssl_msgs/SpeechSegment): audio to play.  Only
        ``sample_rate`` and ``audio_data`` (float32 mono, -1..1) are used.

The audio is not processed (no normalization or effects): it is converted to
int16 (clipped) and played with ``simpleaudio.play_buffer``.  Audios are
played one by one in the order received; the ones waiting are queued and the
oldest are dropped when the queue is full.  The end of playback is detected
by polling ``is_playing()`` with a timer (callbacks never block).

Parameters:
    max_duration (double, 30.0): longer audios are not played
    max_queue (int, 3): max number of audios waiting to be played
    output_sample_rate (int, 0): resample to this rate before playing
        (0: play at the received rate; use 44100 / 48000 only for devices
        that cannot play 16 kHz)

The volume is the PulseAudio sink volume (rosVolume, robot/set_volume).  The
node must run in the user session that owns the PulseAudio / PipeWire server
(XDG_RUNTIME_DIR).  No coordination with TTS: simultaneous sounds overlap.
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from ssl_msgs.msg import SpeechSegment

from audio_play.audio_utils import AudioQueue, resample_linear, to_pcm16, validate_audio

POLL_PERIOD = 0.05


class AudioPlayNode(Node):
    def __init__(self, player=None):
        super().__init__("audio_play")
        self.max_duration = float(self.declare_parameter("max_duration", 30.0).value)
        self.max_queue = int(self.declare_parameter("max_queue", 3).value)
        self.output_sample_rate = int(self.declare_parameter("output_sample_rate", 0).value)

        if player is None:
            import simpleaudio
            player = simpleaudio.play_buffer
        self._play_buffer = player
        self._queue = AudioQueue(self.max_queue)
        # keep the reference: playback may stop when play_obj is garbage-collected
        self._play_obj = None

        self.create_subscription(SpeechSegment, "robot/play_audio", self.on_audio, 10)
        self.create_timer(POLL_PERIOD, self.on_timer)
        self.get_logger().info(
            f"audio_play ready (max_duration={self.max_duration} s, "
            f"max_queue={self.max_queue}, output_sample_rate={self.output_sample_rate})"
        )

    def on_audio(self, msg):
        samples, error = validate_audio(msg.audio_data, msg.sample_rate, self.max_duration)
        if error is not None:
            self.get_logger().warning(f"audio ignored: {error}")
            return
        rate = int(msg.sample_rate)
        dropped = self._queue.push((samples, rate))
        if dropped:
            self.get_logger().warning(f"queue full: dropped {dropped} oldest audio(s)")
        self.get_logger().info(
            f"audio received: {samples.size / rate:.2f} s, {rate} Hz, queue={len(self._queue)}"
        )
        self.on_timer()

    def is_playing(self):
        if self._play_obj is None:
            return False
        try:
            return self._play_obj.is_playing()
        except Exception:  # noqa: BLE001
            return False

    def on_timer(self):
        if self.is_playing():
            return
        self._play_obj = None
        item = self._queue.pop()
        if item is None:
            return
        samples, rate = item
        if self.output_sample_rate > 0 and self.output_sample_rate != rate:
            samples = resample_linear(samples, rate, self.output_sample_rate)
            rate = self.output_sample_rate
        try:
            self._play_obj = self._play_buffer(to_pcm16(samples), 1, 2, rate)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"failed to play audio ({rate} Hz): {e}")
            return
        self.get_logger().info(
            f"playing: {samples.size / rate:.2f} s, {rate} Hz, queue={len(self._queue)}"
        )

    def stop(self):
        if self._play_obj is not None:
            try:
                self._play_obj.stop()
            except Exception:  # noqa: BLE001
                pass
            self._play_obj = None


def main(args=None):
    rclpy.init(args=args)
    node = AudioPlayNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
