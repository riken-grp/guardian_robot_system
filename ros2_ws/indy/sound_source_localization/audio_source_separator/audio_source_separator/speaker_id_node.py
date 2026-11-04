"""ROS2 node that overwrites SpeechSegment.person_id with association_node's person ID.

Matches SpeechSegment (azimuth, distance) against Person.body_location_sensor
using Euclidean distance in the sensor-relative XY plane.
"""

import math

import rclpy
from rclpy.node import Node

from recognition_msgs.msg import Persons
from ssl_msgs.msg import SpeechSegment


class SpeakerIdNode(Node):
    """Re-identify speech segments using visual person tracking IDs."""

    def __init__(self) -> None:
        super().__init__('speaker_id_node')

        self.declare_parameter('match_distance_threshold', 1.0)

        self._latest_persons: Persons | None = None

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

        self.get_logger().info('SpeakerIdNode started.')

    def _on_persons(self, msg: Persons) -> None:
        self._latest_persons = msg

    def _on_speech(self, msg: SpeechSegment) -> None:
        if self._latest_persons is None or not self._latest_persons.persons:
            self.pub_speech.publish(msg)
            return

        threshold = self.get_parameter('match_distance_threshold').value

        # Convert speech segment polar to cartesian (sensor frame)
        seg_x = msg.distance * math.cos(msg.azimuth)
        seg_y = msg.distance * math.sin(msg.azimuth)

        best_id = msg.person_id
        best_dist = float('inf')

        for person in self._latest_persons.persons:
            loc = person.body_location_sensor
            if len(loc) < 2:
                continue
            px, py = loc[0], loc[1]
            d = math.hypot(seg_x - px, seg_y - py)
            if d < best_dist:
                best_dist = d
                best_id = person.instance_id

        if best_dist <= threshold:
            msg.person_id = best_id
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
