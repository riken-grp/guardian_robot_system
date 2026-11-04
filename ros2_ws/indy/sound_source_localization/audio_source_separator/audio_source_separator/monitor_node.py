"""ROS2 node for monitoring speech segments: level display, speaker playback, and WAV saving."""

import math
import os
import wave

import numpy as np
import rclpy
from rclpy.node import Node

from ssl_msgs.msg import SpeechSegment

BAR_WIDTH = 40
DB_MIN = -60.0
DB_MAX = 0.0


def _level_bar(rms_dbfs: float, peak_dbfs: float) -> str:
    """Build a terminal level bar string like channel_monitor_node."""
    clamped = max(DB_MIN, min(DB_MAX, rms_dbfs))
    filled = round((clamped - DB_MIN) / (DB_MAX - DB_MIN) * BAR_WIDTH)
    filled = max(0, min(BAR_WIDTH, filled))
    bar = '\u2588' * filled + ' ' * (BAR_WIDTH - filled)
    return f'[{bar}] {rms_dbfs:6.1f} dBFS (peak: {peak_dbfs:6.1f} dBFS)'


class MonitorNode(Node):
    """Play speech segments through speakers and optionally save as WAV files."""

    def __init__(self) -> None:
        super().__init__('monitor_node')

        self.declare_parameter('play', True)
        self.declare_parameter('save_dir', '')

        self._segment_count = 0
        self._pa = None

        save_dir = self.get_parameter('save_dir').value
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            self.get_logger().info(f'Saving segments to: {save_dir}')

        if self.get_parameter('play').value:
            self._init_audio()

        self.sub_speech = self.create_subscription(
            SpeechSegment, 'in_speech_segments', self._on_speech, 10,
        )

        self.get_logger().info('MonitorNode started.')

    def _init_audio(self) -> None:
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
            self.get_logger().info('Speaker playback enabled.')
        except ImportError:
            self.get_logger().warn('pyaudio not installed, playback disabled.')
        except Exception as e:
            self.get_logger().warn(f'Failed to initialize audio: {e}')

    def _on_speech(self, msg: SpeechSegment) -> None:
        audio = np.array(msg.audio_data, dtype=np.float32)
        if len(audio) == 0:
            return

        sample_rate = msg.sample_rate

        # Compute level
        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        rms_dbfs = 20.0 * math.log10(rms) if rms > 1e-10 else -100.0
        peak_dbfs = 20.0 * math.log10(peak) if peak > 1e-10 else -100.0

        bar = _level_bar(rms_dbfs, peak_dbfs)
        self.get_logger().info(
            f'#{self._segment_count:04d} person={msg.person_id} '
            f'{msg.duration:.2f}s {bar}'
        )

        if self.get_parameter('play').value and self._pa is not None:
            self._play(audio, sample_rate)

        save_dir = self.get_parameter('save_dir').value
        if save_dir:
            self._save_wav(audio, sample_rate, save_dir)

        self._segment_count += 1

    def _play(self, audio: np.ndarray, sample_rate: int) -> None:
        import pyaudio

        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                output=True,
            )
            stream.write(pcm)
            stream.stop_stream()
            stream.close()
        except Exception as e:
            self.get_logger().warn(
                f'Playback failed: {e}', throttle_duration_sec=5.0,
            )

    def _save_wav(self, audio: np.ndarray, sample_rate: int, save_dir: str) -> None:
        filename = os.path.join(save_dir, f'segment_{self._segment_count:04d}.wav')
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(filename, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        self.get_logger().info(f'Saved: {filename}')

    def destroy_node(self) -> None:
        if self._pa is not None:
            self._pa.terminate()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MonitorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
