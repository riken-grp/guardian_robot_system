import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class CompressedImageFlipNode(Node):
    def __init__(self):
        super().__init__("compressed_image_flip_node")
        self.subscription = self.create_subscription(
            CompressedImage,
            "/input_compressed",
            self.callback,
            qos_profile=qos.qos_profile_system_default,
        )

        self.publisher = self.create_publisher(
            CompressedImage,
            "/output_compressed",
            qos_profile=qos.qos_profile_system_default,
        )

        self.bridge = CvBridge()

    def callback(self, msg: CompressedImage):
        np_arr = np.frombuffer(msg.data, np.uint8)
        cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        flipped_image = cv2.flip(cv_image, 1)

        flipped_msg = CompressedImage()
        flipped_msg.header = msg.header
        flipped_msg.format = msg.format
        flipped_msg.data = np.array(cv2.imencode(".jpg", flipped_image)[1]).tobytes()

        # 配信
        self.publisher.publish(flipped_msg)


def main(args=None):
    rclpy.init(args=args)
    node = CompressedImageFlipNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
