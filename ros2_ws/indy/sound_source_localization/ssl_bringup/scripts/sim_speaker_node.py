#!/usr/bin/env python3
"""Simulation node: injects a virtual person into real sensor data.

Subscribes to real LaserScan and AudioDataMultiChannel, injects a
simulated person (LiDAR cluster + directional speech audio), and
republishes the modified data on separate topics.

Reads microphone positions from audio/array_info (published by the
real microphone_array_node) so that delay simulation matches SRP-PHAT.

Press Enter in the terminal to trigger speech playback.

Parameters:
  speaker_x:       Speaker X position in metres (forward, default 1.0)
  speaker_y:       Speaker Y position in metres (left-positive, default -0.5)
  text:            Utterance text for TTS (default 'こんにちは')
  sample_rate:     Audio sample rate (default 16000)
  speech_duration: Duration of synthetic fallback speech (default 1.5)
"""

import math
import sys
import threading

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data

from sensor_msgs.msg import LaserScan
from microphone_array.msg import AudioDataMultiChannel, MicrophoneArrayInfo

SPEED_OF_SOUND = 343.0


class SimSpeakerNode(Node):

    def __init__(self) -> None:
        super().__init__('sim_speaker_node')

        self.declare_parameter('speaker_x', 1.0)
        self.declare_parameter('speaker_y', -0.5)
        self.declare_parameter('text', 'こんにちは')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('speech_duration', 1.5)

        self._speaker_x = self.get_parameter('speaker_x').value
        self._speaker_y = self.get_parameter('speaker_y').value
        self._text = self.get_parameter('text').value
        self._sample_rate = self.get_parameter('sample_rate').value
        self._speech_duration = self.get_parameter('speech_duration').value

        self._distance = math.sqrt(self._speaker_x ** 2 + self._speaker_y ** 2)
        self._azimuth = math.atan2(self._speaker_y, self._speaker_x)

        # Mic geometry — set when array_info is received
        self._mic_positions = None
        self._n_channels = 0
        self._delay_samples = None

        self.get_logger().info(
            f'Simulating speaker at ({self._speaker_x:.2f}, {self._speaker_y:.2f}) '
            f'= {math.degrees(self._azimuth):.1f}deg, {self._distance:.2f}m, '
            f'text="{self._text}"'
        )

        # Generate speech audio
        self._speech_audio = self._generate_speech()
        self._audio_pos = len(self._speech_audio)  # start silent

        # --- Subscribers ---
        latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._sub_array_info = self.create_subscription(
            MicrophoneArrayInfo, 'audio/array_info',
            self._on_array_info, latched_qos,
        )
        self._sub_scan = self.create_subscription(
            LaserScan, 'in_scan', self._on_scan, qos_profile_sensor_data,
        )
        self._sub_audio = self.create_subscription(
            AudioDataMultiChannel, 'in_audio', self._on_audio,
            qos_profile_sensor_data,
        )

        # --- Publishers ---
        self._pub_scan = self.create_publisher(LaserScan, 'out_scan', 10)
        self._pub_audio = self.create_publisher(
            AudioDataMultiChannel, 'out_audio', qos_profile_sensor_data,
        )

        # Start stdin listener thread
        self._stdin_thread = threading.Thread(target=self._stdin_loop, daemon=True)
        self._stdin_thread.start()

        self.get_logger().info(
            'SimSpeakerNode started. Waiting for audio/array_info ...'
        )

    # ------------------------------------------------------------------
    # Array info callback
    # ------------------------------------------------------------------

    def _on_array_info(self, msg: MicrophoneArrayInfo) -> None:
        n = msg.num_channels
        self._mic_positions = np.array(
            msg.positions, dtype=np.float64
        ).reshape(n, 3)
        self._n_channels = n
        self._precompute_delays()
        self.get_logger().info(
            f'Received MicrophoneArrayInfo: {n} channels. '
            f'Press Enter to speak.'
        )

    # ------------------------------------------------------------------
    # Keyboard input
    # ------------------------------------------------------------------

    def _stdin_loop(self) -> None:
        """Wait for Enter key and trigger speech playback."""
        while rclpy.ok():
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                if self._mic_positions is None:
                    self.get_logger().warn(
                        'array_info not yet received, cannot speak'
                    )
                    continue
                self._audio_pos = 0
                self.get_logger().info(f'Speaking: "{self._text}"')
            except EOFError:
                break

    # ------------------------------------------------------------------
    # Precompute delays
    # ------------------------------------------------------------------

    def _precompute_delays(self) -> None:
        """Compute per-channel delays matching SRP-PHAT convention."""
        d = np.array([self._speaker_x, self._speaker_y, 0.0])
        d = d / np.linalg.norm(d)
        centroid = self._mic_positions.mean(axis=0)
        relative = self._mic_positions - centroid
        delays = -relative @ d / SPEED_OF_SOUND
        self._delay_samples = (delays * self._sample_rate).astype(np.int32)
        self._delay_samples -= self._delay_samples.min()

    # ------------------------------------------------------------------
    # LiDAR: subscribe real scan, inject person cluster, republish
    # ------------------------------------------------------------------

    @property
    def _is_speaking(self) -> bool:
        return self._audio_pos < len(self._speech_audio)

    def _on_scan(self, msg: LaserScan) -> None:
        """Republish scan, injecting a person cluster only while speaking."""
        ranges = list(msg.ranges)
        person_half_width_rad = math.atan2(0.15, self._distance)

        for i in range(len(ranges)):
            angle = msg.angle_min + i * msg.angle_increment
            diff = angle - self._azimuth
            diff = (diff + math.pi) % (2.0 * math.pi) - math.pi

            if abs(diff) <= person_half_width_rad:
                if self._is_speaking:
                    noise = np.random.uniform(-0.02, 0.02)
                    ranges[i] = self._distance + noise
                else:
                    ranges[i] = float('inf')

        out = LaserScan()
        out.header = msg.header
        out.header.stamp = self.get_clock().now().to_msg()
        out.angle_min = msg.angle_min
        out.angle_max = msg.angle_max
        out.angle_increment = msg.angle_increment
        out.time_increment = msg.time_increment
        out.scan_time = msg.scan_time
        out.range_min = msg.range_min
        out.range_max = msg.range_max
        out.ranges = [float(r) for r in ranges]
        out.intensities = list(msg.intensities)
        self._pub_scan.publish(out)

    # ------------------------------------------------------------------
    # Audio: subscribe real audio, mix in simulated speech, republish
    # ------------------------------------------------------------------

    def _on_audio(self, msg: AudioDataMultiChannel) -> None:
        """Mix simulated directional speech into real audio and republish."""
        remaining = len(self._speech_audio) - self._audio_pos

        # No speech active or not yet initialized: pass through
        if remaining <= 0 or self._delay_samples is None:
            msg.stamp = self.get_clock().now().to_msg()
            self._pub_audio.publish(msg)
            return

        n_ch = msg.channels
        n_frames = msg.frames_per_block

        real = np.array(msg.data, dtype=np.int16).reshape(n_frames, n_ch).astype(np.float64)

        n = min(n_frames, remaining)
        mono = np.zeros(n_frames, dtype=np.float64)
        mono[:n] = self._speech_audio[self._audio_pos:self._audio_pos + n]
        self._audio_pos += n

        sim = self._apply_direction(mono, n_ch, n_frames)
        mixed = real + sim

        pcm = np.clip(mixed, -32768, 32767).astype(np.int16).flatten()

        out = AudioDataMultiChannel()
        out.stamp = self.get_clock().now().to_msg()
        out.sample_rate = msg.sample_rate
        out.channels = n_ch
        out.frames_per_block = n_frames
        out.data = pcm.tolist()
        self._pub_audio.publish(out)

    def _apply_direction(self, mono: np.ndarray, n_ch: int,
                         n_frames: int) -> np.ndarray:
        """Apply per-channel delays, return (n_frames, n_ch) float in int16 scale."""
        padded_len = n_frames + self._delay_samples.max()
        output = np.zeros((padded_len, n_ch), dtype=np.float64)

        for ch in range(min(n_ch, self._n_channels)):
            ds = self._delay_samples[ch]
            output[ds:ds + n_frames, ch] = mono

        output = output[:n_frames, :] * 32767.0
        return output

    # ------------------------------------------------------------------
    # Speech generation
    # ------------------------------------------------------------------

    def _generate_speech(self) -> np.ndarray:
        """Generate mono speech audio. Try gTTS, fall back to synthetic."""
        try:
            from gtts import gTTS
            from pydub import AudioSegment
            import io

            tts = gTTS(text=self._text, lang='ja')
            mp3_buf = io.BytesIO()
            tts.write_to_fp(mp3_buf)
            mp3_buf.seek(0)

            seg = AudioSegment.from_mp3(mp3_buf)
            seg = seg.set_channels(1).set_frame_rate(self._sample_rate)
            raw = np.array(seg.get_array_of_samples(), dtype=np.float64)
            audio = raw / 32768.0
            peak = np.max(np.abs(audio))
            if peak > 0:
                audio = audio / peak * 0.9

            self.get_logger().info(
                f'gTTS audio: {len(audio)} samples ({len(audio)/self._sample_rate:.2f}s)'
            )
            return audio

        except Exception as e:
            self.get_logger().warn(f'gTTS failed ({e}), using synthetic speech')
            return self._generate_synthetic_speech()

    def _generate_synthetic_speech(self) -> np.ndarray:
        """Fallback: speech-like signal using modulated harmonics."""
        sr = self._sample_rate
        dur = self._speech_duration
        t = np.arange(int(sr * dur)) / sr

        f0 = 150.0
        signal = np.zeros_like(t)
        for k in range(1, 6):
            signal += (0.5 ** k) * np.sin(2.0 * np.pi * f0 * k * t)

        envelope = np.ones_like(t)
        fade = int(0.05 * sr)
        envelope[:fade] = np.linspace(0, 1, fade)
        envelope[-fade:] = np.linspace(1, 0, fade)
        envelope *= 0.5 + 0.5 * np.sin(2.0 * np.pi * 4.0 * t)

        signal *= envelope * 0.8
        return signal


def main(args=None):
    rclpy.init(args=args)
    node = SimSpeakerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
