"""ROS2 node that adds Janome morphological analysis to ASR results."""

import json

import rclpy
from rclpy.node import Node

from common_msgs.msg import StringStamped

from . import morph


class MorphNode(Node):
    """Subscribe to asr_node results, publish them with a ``morph`` field.

    The output is the input JSON plus ``morph`` (see :func:`morph.analyze`).
    Without Janome the results are passed through unchanged.
    """

    def __init__(self) -> None:
        super().__init__('morph_node')

        if morph.Tokenizer is None:
            self.get_logger().warn(
                'janome is not installed; results are published without morph')

        self.sub_result = self.create_subscription(
            StringStamped, 'in_result', self._on_result, 10,
        )
        self.pub_analyzed = self.create_publisher(
            StringStamped, 'out_analyzed', 10,
        )

        self.get_logger().info('MorphNode started.')

    def _on_result(self, msg: StringStamped) -> None:
        try:
            result = json.loads(msg.data)
        except ValueError:
            self.get_logger().warn(f'Invalid ASR result (not JSON): {msg.data}')
            return
        text = str(result.get('text', '')).strip()
        m = morph.analyze(text) if text else None
        if m is not None:
            result['morph'] = m

        out = StringStamped()
        out.header = msg.header
        out.data = json.dumps(result, ensure_ascii=False)
        self.pub_analyzed.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = MorphNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
