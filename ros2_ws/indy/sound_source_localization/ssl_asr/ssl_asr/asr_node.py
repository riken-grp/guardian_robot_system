"""ROS2 node that transcribes SpeechSegment audio using Whisper."""

import json
import math
import os

import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time

from common_msgs.msg import StringStamped
from ssl_msgs.msg import SpeechSegment

try:
    from scipy.signal import resample_poly
except ImportError:  # pragma: no cover
    resample_poly = None

try:
    from tf2_ros import Buffer, TransformListener
except ImportError:  # pragma: no cover - tf2_ros is part of ROS 2 desktop
    Buffer = None
    TransformListener = None

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
    # From kad/asr REJECT_WORDS (only the full hallucination phrases)
    'ご清聴ありがとうございました',
    'ご利用いただきありがとうございます',
    '最後まで視聴してくださって本当にありがとうございます',
    'また見てね',
    '次回へ続く',
    '次の動画でお会いしましょう',
    '字幕作成',
    'by H.',
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


def transcript_confidence(segments) -> float:
    """Confidence in [0, 1] of the kept Whisper segments.

    Mean word probability when word timestamps were computed (same as
    kad/asr), otherwise the token-weighted geometric mean token probability
    ``exp(avg_logprob)``.  0.0 for no segments.
    """
    probs = [w.probability for s in segments
             for w in (getattr(s, 'words', None) or [])]
    if probs:
        return float(np.mean(probs))
    weights = [max(len(getattr(s, 'tokens', None) or []), 1) for s in segments]
    if not weights:
        return 0.0
    avg = sum(w * s.avg_logprob for w, s in zip(weights, segments)) / sum(weights)
    return float(min(1.0, math.exp(avg)))


def quaternion_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """Rotation matrix (3, 3) of a unit quaternion (x, y, z, w)."""
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    xx, yy, zz = x * x * s, y * y * s, z * z * s
    xy, xz, yz = x * y * s, x * z * s, y * z * s
    wx, wy, wz = w * x * s, w * y * s, w * z * s
    return np.array([
        [1.0 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1.0 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1.0 - (xx + yy)],
    ])


def speaker_location(azimuth: float, distance: float, transform=None) -> list[float]:
    """Speaker position [x, y, z] from (azimuth, distance) in the array frame.

    The array frame follows the ROS convention (x forward, y left).  With a
    geometry_msgs/Transform(Stamped) (array -> base), the point is expressed
    in the base frame.
    """
    p = np.array([distance * math.cos(azimuth), distance * math.sin(azimuth), 0.0])
    if transform is not None:
        tf = getattr(transform, 'transform', transform)
        q, t = tf.rotation, tf.translation
        p = quaternion_to_matrix(q.x, q.y, q.z, q.w) @ p + np.array([t.x, t.y, t.z])
    return [float(v) for v in p]


def _default_base_frame() -> str:
    robot_name = os.getenv('ROBOT_NAME', '')
    return f'{robot_name}_base_link' if robot_name else 'base_link'


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
        # Word timestamps: confidence = mean word probability (as kad/asr),
        # slightly slower.  Otherwise confidence = exp(avg_logprob).
        self.declare_parameter('word_timestamps', False)
        # Parallel transcriptions (faster-whisper num_workers = executor threads).
        # At most 2-3 people speak at the same time.
        self.declare_parameter('num_workers', 3)
        # Speaker location in the robot base frame (tf2).  speech_frame is used
        # only when the SpeechSegment header has no frame_id.
        self.declare_parameter('base_frame', _default_base_frame())
        self.declare_parameter('speech_frame', 'microphone_array_base')
        # Hallucination suppression
        self.declare_parameter('vad_filter', True)              # faster-whisper Silero VAD
        self.declare_parameter('vad_min_silence_ms', 500)
        self.declare_parameter('no_speech_threshold', 0.6)
        self.declare_parameter('log_prob_threshold', -1.0)
        self.declare_parameter('compression_ratio_threshold', 2.4)
        self.declare_parameter('min_duration', 0.3)             # s; shorter segments are not transcribed
        self.declare_parameter('hallucination_phrases', DEFAULT_HALLUCINATION_PHRASES)

        self._load_model()

        self._tf_buffer = Buffer() if Buffer is not None else None
        # spin_thread: TF is received even while all executor threads transcribe
        self._tf_listener = (TransformListener(self._tf_buffer, self, spin_thread=True)
                             if self._tf_buffer is not None else None)

        # Subscriber (reentrant: up to num_workers segments are transcribed in parallel)
        self.sub_speech = self.create_subscription(
            SpeechSegment, 'in_speech_segments', self._on_speech, 10,
            callback_group=ReentrantCallbackGroup(),
        )

        # Publisher
        self.pub_result = self.create_publisher(
            StringStamped, 'out_result', 10,
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
            num_workers=max(1, int(self.get_parameter('num_workers').value)),
        )
        self.get_logger().info('Whisper model loaded.')

    def _lookup_base(self, source: str):
        """Latest transform source -> base_frame, or None (throttled warning)."""
        if self._tf_buffer is None or not source:
            return None
        target = self.get_parameter('base_frame').value
        try:
            return self._tf_buffer.lookup_transform(
                target, source, Time(), timeout=Duration(seconds=0.0))
        except Exception as e:  # noqa: BLE001 (tf2 raises several types)
            self.get_logger().warn(
                f'TF {source} -> {target} unavailable: {e}; location is in '
                f'the array frame', throttle_duration_sec=10.0)
            return None

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
            word_timestamps=bool(self.get_parameter('word_timestamps').value),
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
                kept.append(s)
            else:
                dropped.append(s.text)
        text = ''.join(s.text for s in kept).strip()
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

        confidence = transcript_confidence(kept)
        speech_frame = msg.header.frame_id or self.get_parameter('speech_frame').value
        tf_base = self._lookup_base(speech_frame)
        location = speaker_location(msg.azimuth, msg.distance, tf_base)
        location_frame = (self.get_parameter('base_frame').value
                          if tf_base is not None else speech_frame)

        out = StringStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = location_frame
        out.data = json.dumps({
            'person_id': msg.person_id,
            'text': text,
            'confidence': confidence,
            'language': info.language,
            'language_probability': info.language_probability,
            'duration': msg.duration,
            'azimuth': msg.azimuth,
            'distance': msg.distance,
            # Speaker position (x forward, y left) in location_frame
            'location': location,
            'location_frame': location_frame,
            'speech_start_ns': msg.speech_start_ns,
            'speech_end_ns': msg.speech_end_ns,
        }, ensure_ascii=False)

        self.pub_result.publish(out)
        self.get_logger().info(
            f'[person={msg.person_id}] {text} (conf={confidence:.2f})'
        )


def main(args=None):
    rclpy.init(args=args)
    node = AsrNode()
    executor = MultiThreadedExecutor(
        num_threads=max(1, int(node.get_parameter('num_workers').value)))
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
