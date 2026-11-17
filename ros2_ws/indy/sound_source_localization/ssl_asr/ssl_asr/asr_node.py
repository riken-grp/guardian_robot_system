"""ROS2 node that transcribes SpeechSegment audio using Whisper."""

import json
import math

import numpy as np
import rclpy
from rclpy.node import Node

from common_msgs.msg import StringStamped
from ssl_msgs.msg import SpeechSegment

try:
    from scipy.signal import resample_poly
except ImportError:  # pragma: no cover
    resample_poly = None

# faster-whisper expects 16 kHz mono float32 audio
WHISPER_SAMPLE_RATE = 16000

# Phrases Whisper tends to hallucinate on silence / noise (Japanese models are
# trained on subtitled videos).  A result consisting only of these is dropped.
DEFAULT_HALLUCINATION_PHRASES = [
    # Only phrases that are practically never said to the robot; generic
    # ones such as "ありがとうございました" are intentionally not listed.
    'ご視聴ありがとうございました',
    'ご視聴ありがとうございます',
    '最後までご視聴いただきありがとうございました',
    '最後までご視聴ありがとうございました',
    'チャンネル登録よろしくお願いします',
    'チャンネル登録お願いします',
    'チャンネル登録',
    '高評価',
    '字幕視聴ありがとうございました',
]

_STRIP_CHARS = ' 　、。，．,.!！?？…・「」『』()（）[]【】~〜ー-'


def normalize_text(text: str) -> str:
    """Text without spaces / punctuation, for phrase matching."""
    return ''.join(ch for ch in text if ch not in _STRIP_CHARS)


def is_hallucination(text: str, phrases: list[str]) -> bool:
    """True if ``text`` consists only of (repetitions of) known phrases."""
    t = normalize_text(text)
    if not t:
        return True
    norm = sorted({normalize_text(p) for p in phrases if normalize_text(p)},
                  key=len, reverse=True)
    changed = True
    while t and changed:
        changed = False
        for p in norm:
            if t.startswith(p):
                t = t[len(p):]
                changed = True
                break
    return t == ''


def keep_segment(no_speech_prob: float, avg_logprob: float,
                 compression_ratio: float, no_speech_threshold: float,
                 log_prob_threshold: float,
                 compression_ratio_threshold: float) -> bool:
    """Whisper segment filter (same criteria as openai-whisper's fallback).

    Drop when the model thinks it is silence (high no_speech_prob *and* low
    confidence), or when the text is highly repetitive.
    """
    if no_speech_prob > no_speech_threshold and avg_logprob < log_prob_threshold:
        return False
    if compression_ratio > compression_ratio_threshold:
        return False
    return True


def to_whisper_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray | None:
    """Resample ``audio`` to 16 kHz; None if impossible (no scipy / bad rate)."""
    if sample_rate == WHISPER_SAMPLE_RATE:
        return audio
    if sample_rate <= 0 or resample_poly is None:
        return None
    g = math.gcd(int(sample_rate), WHISPER_SAMPLE_RATE)
    up, down = WHISPER_SAMPLE_RATE // g, int(sample_rate) // g
    return resample_poly(audio, up, down).astype(np.float32)


class AsrNode(Node):
    """Subscribe to speech segments, run Whisper, publish transcription."""

    def __init__(self) -> None:
        super().__init__('asr_node')

        self.declare_parameter('model_size', 'large-v3')
        self.declare_parameter('language', 'ja')
        self.declare_parameter('device', 'cuda')
        self.declare_parameter('compute_type', 'float16')
        # Decoding settings (fast defaults for short utterances)
        self.declare_parameter('beam_size', 1)
        self.declare_parameter('condition_on_previous_text', False)
        self.declare_parameter('without_timestamps', True)
        # Hallucination suppression
        self.declare_parameter('vad_filter', True)              # faster-whisper Silero VAD
        self.declare_parameter('vad_min_silence_ms', 500)
        self.declare_parameter('no_speech_threshold', 0.6)
        self.declare_parameter('log_prob_threshold', -1.0)
        self.declare_parameter('compression_ratio_threshold', 2.4)
        self.declare_parameter('min_duration', 0.3)             # s; shorter segments are not transcribed
        self.declare_parameter('hallucination_phrases', DEFAULT_HALLUCINATION_PHRASES)

        self._load_model()

        # Subscriber
        self.sub_speech = self.create_subscription(
            SpeechSegment, 'in_speech_segments', self._on_speech, 10,
        )

        # Publisher
        self.pub_text = self.create_publisher(
            StringStamped, 'out_raw_text', 10,
        )

        self.get_logger().info('AsrNode started.')

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        model_size = self.get_parameter('model_size').value
        device = self.get_parameter('device').value
        compute_type = self.get_parameter('compute_type').value

        self.get_logger().info(
            f'Loading Whisper model: {model_size} ({device}, {compute_type})'
        )
        self._model = WhisperModel(
            model_size, device=device, compute_type=compute_type,
        )
        self.get_logger().info('Whisper model loaded.')

    def _on_speech(self, msg: SpeechSegment) -> None:
        # array.array('f') -> zero-copy float32 view via the buffer protocol
        audio = np.asarray(msg.audio_data, dtype=np.float32)
        if len(audio) == 0:
            return

        resampled = to_whisper_rate(audio, int(msg.sample_rate))
        if resampled is None:
            self.get_logger().warn(
                f'Cannot resample segment from {msg.sample_rate} Hz to '
                f'{WHISPER_SAMPLE_RATE} Hz (scipy unavailable or invalid '
                f'rate); dropping segment',
                throttle_duration_sec=5.0,
            )
            return
        audio = resampled

        if len(audio) < self.get_parameter('min_duration').value * WHISPER_SAMPLE_RATE:
            return

        language = self.get_parameter('language').value
        nst = float(self.get_parameter('no_speech_threshold').value)
        lpt = float(self.get_parameter('log_prob_threshold').value)
        crt = float(self.get_parameter('compression_ratio_threshold').value)
        kwargs = dict(
            language=language,
            beam_size=int(self.get_parameter('beam_size').value),
            condition_on_previous_text=bool(
                self.get_parameter('condition_on_previous_text').value),
            without_timestamps=bool(
                self.get_parameter('without_timestamps').value),
            no_speech_threshold=nst,
            log_prob_threshold=lpt,
            compression_ratio_threshold=crt,
        )
        if self.get_parameter('vad_filter').value:
            kwargs['vad_filter'] = True
            kwargs['vad_parameters'] = dict(
                min_silence_duration_ms=int(self.get_parameter('vad_min_silence_ms').value))

        segments, info = self._model.transcribe(audio, **kwargs)
        kept, dropped = [], []
        for s in segments:
            if keep_segment(s.no_speech_prob, s.avg_logprob, s.compression_ratio,
                            nst, lpt, crt):
                kept.append(s.text)
            else:
                dropped.append(s.text)
        text = ''.join(kept).strip()
        if dropped:
            self.get_logger().info(
                f'[person={msg.person_id}] dropped low-confidence: {"".join(dropped).strip()}')

        if not text:
            return
        phrases = list(self.get_parameter('hallucination_phrases').value)
        if is_hallucination(text, phrases):
            self.get_logger().info(
                f'[person={msg.person_id}] dropped hallucination: {text}')
            return

        out = StringStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.data = json.dumps({
            'person_id': msg.person_id,
            'text': text,
            'language': info.language,
            'language_probability': info.language_probability,
            'duration': msg.duration,
            'azimuth': msg.azimuth,
            'distance': msg.distance,
            'speech_start_ns': msg.speech_start_ns,
            'speech_end_ns': msg.speech_end_ns,
        }, ensure_ascii=False)

        self.pub_text.publish(out)
        self.get_logger().info(
            f'[person={msg.person_id}] {text}'
        )


def main(args=None):
    rclpy.init(args=args)
    node = AsrNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
