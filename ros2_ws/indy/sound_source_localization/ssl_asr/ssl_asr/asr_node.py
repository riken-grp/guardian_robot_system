"""ROS2 node that transcribes SpeechSegment audio using Whisper."""

import json

import numpy as np
import rclpy
from rclpy.node import Node

from common_msgs.msg import StringStamped
from ssl_msgs.msg import SpeechSegment


class AsrNode(Node):
    """Subscribe to speech segments, run Whisper, publish transcription."""

    def __init__(self) -> None:
        super().__init__('asr_node')

        self.declare_parameter('model_size', 'large-v3')
        self.declare_parameter('language', 'ja')
        self.declare_parameter('device', 'cuda')
        self.declare_parameter('compute_type', 'float16')

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
        audio = np.array(msg.audio_data, dtype=np.float32)
        if len(audio) == 0:
            return

        language = self.get_parameter('language').value

        segments, info = self._model.transcribe(
            audio, language=language, beam_size=5,
        )
        text = ''.join(s.text for s in segments).strip()

        if not text:
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
