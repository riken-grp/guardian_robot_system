"""ROS2 node that overwrites SpeechSegment.person_id with association_node's person ID.

Matches SpeechSegment (azimuth, distance; microphone-array frame) against
Person.body_location_sensor (camera frame, typically an optical frame:
x right, y down, z forward).  Both are transformed with tf2 into a common
frame (``base_frame``, the robot base by default) and compared by Euclidean
distance in its x-y (ground) plane.
"""

import math
import os

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time

from recognition_msgs.msg import Persons
from ssl_msgs.msg import SpeechSegment

from .tf_utils import transform_points

try:
    from tf2_ros import Buffer, TransformListener
except ImportError:  # pragma: no cover - tf2_ros is part of ROS 2 desktop
    Buffer = None
    TransformListener = None


def _default_base_frame() -> str:
    robot_name = os.getenv('ROBOT_NAME', '')
    return f'{robot_name}_base_link' if robot_name else 'base_link'


class SpeakerIdNode(Node):
    """Re-identify speech segments using visual person tracking IDs."""

    def __init__(self) -> None:
        super().__init__('speaker_id_node')

        self.declare_parameter('match_distance_threshold', 1.0)
        # Common comparison frame (robot base; x-y = ground plane)
        self.declare_parameter('base_frame', _default_base_frame())
        # Fallbacks used only when the message header has no frame_id
        self.declare_parameter('speech_frame', 'microphone_array_base')
        self.declare_parameter('persons_frame', '')

        self._latest_persons: Persons | None = None
        self._tf_buffer = Buffer() if Buffer is not None else None
        self._tf_listener = (TransformListener(self._tf_buffer, self)
                             if self._tf_buffer is not None else None)

        # Subscribers
        self.sub_persons = self.create_subscription(
            Persons, 'in_persons', self._on_persons, 10,
        )
        self.sub_speech = self.create_subscription(
            SpeechSegment, 'in_speech_segments', self._on_speech, 10,
        )

        # Publisher
        self.pub_speech = self.create_publisher(
            SpeechSegment, 'out_speech_segments', 10,
        )

        self.get_logger().info(
            f'SpeakerIdNode started (base_frame='
            f'{self.get_parameter("base_frame").value}).')

    def _on_persons(self, msg: Persons) -> None:
        self._latest_persons = msg

    def _lookup(self, target: str, source: str):
        """Latest transform source -> target, or None (throttled warning)."""
        if self._tf_buffer is None:
            self.get_logger().warn(
                'tf2_ros not available; cannot match speakers',
                throttle_duration_sec=10.0)
            return None
        try:
            return self._tf_buffer.lookup_transform(
                target, source, Time(), timeout=Duration(seconds=0.0))
        except Exception as e:  # noqa: BLE001 (tf2 raises several types)
            self.get_logger().warn(
                f'TF {source} -> {target} unavailable: {e}',
                throttle_duration_sec=5.0)
            return None

    def _on_speech(self, msg: SpeechSegment) -> None:
        persons_msg = self._latest_persons
        if persons_msg is None or not persons_msg.persons:
            self.pub_speech.publish(msg)
            return

        threshold = self.get_parameter('match_distance_threshold').value
        base = self.get_parameter('base_frame').value
        speech_frame = (msg.header.frame_id
                        or self.get_parameter('speech_frame').value)
        persons_frame = (persons_msg.header.frame_id
                         or self.get_parameter('persons_frame').value)

        candidates = [p for p in persons_msg.persons
                      if len(p.body_location_sensor) >= 3]
        if not candidates or not persons_frame:
            if candidates:
                self.get_logger().warn(
                    'Persons message has no frame_id and persons_frame is '
                    'not set; skipping speaker matching',
                    throttle_duration_sec=10.0)
            self.pub_speech.publish(msg)
            return

        tf_speech = self._lookup(base, speech_frame)
        tf_persons = self._lookup(base, persons_frame)
        if tf_speech is None or tf_persons is None:
            # Cannot compare in a common frame: keep the original person_id
            self.pub_speech.publish(msg)
            return

        # Speech position: polar (azimuth, distance) in the array frame
        seg = transform_points(tf_speech, np.array([[
            msg.distance * math.cos(msg.azimuth),
            msg.distance * math.sin(msg.azimuth),
            0.0,
        ]]))[0]
        pts = transform_points(
            tf_persons,
            np.array([list(p.body_location_sensor[:3]) for p in candidates]))

        d = np.hypot(pts[:, 0] - seg[0], pts[:, 1] - seg[1])
        best = int(np.argmin(d))
        best_dist = float(d[best])

        if best_dist <= threshold:
            msg.person_id = candidates[best].instance_id
        else:
            self.get_logger().debug(
                f'No person matched within {threshold}m '
                f'(closest={best_dist:.2f}m), keeping original person_id',
                throttle_duration_sec=5.0,
            )

        self.pub_speech.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = SpeakerIdNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
