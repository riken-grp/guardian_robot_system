#!/usr/bin/env python3
import json

import cv2
import numpy as np
import rclpy
from common_msgs.msg import StringStamped
from cv2 import aruco
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage


class QRCodeReader(Node):
    def __init__(self):
        super().__init__("qr_code_reader")

        self.pub = self.create_publisher(
            StringStamped,
            "out_topic",
            qos_profile=qos.qos_profile_system_default,
        )

        # 可視化画像Publisher
        self.vis_pub = self.create_publisher(
            CompressedImage,
            "vis_topic",
            qos_profile=qos.qos_profile_system_default,
        )

        # 購読
        self.create_subscription(
            CompressedImage,
            "in_color_topic",
            self.image_callback,
            qos_profile=qos.qos_profile_system_default,
        )

        # OpenCV Bridge
        self.bridge = CvBridge()

        self.qcd = cv2.QRCodeDetector()

    def image_callback(self, msg: CompressedImage):
        frame = self.bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="bgr8")
        try:
            retval, decoded_info, points, straight_qrcode = (
                self.qcd.detectAndDecodeMulti(frame)
            )
        except Exception as e:
            self.get_logger().error(f"QR code detection failed: {e}")
            retval = False

        if retval:
            frame = cv2.polylines(frame, points.astype(int), True, (0, 255, 0), 3)
            outmsg = StringStamped()
            outmsg.header.stamp = msg.header.stamp
            outmsg.data = json.dumps(decoded_info)

            for s, p in zip(decoded_info, points):
                if s:
                    cv2.putText(
                        frame,
                        s,
                        tuple(p[0].astype(int)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2,
                        cv2.LINE_AA,
                    )

            self.pub.publish(outmsg)

        # 検出画像をCompressedImageに変換してPublish
        self._publish_visualization(msg.header, frame)

    def _publish_visualization(self, header, show_img):
        success, encoded_image = cv2.imencode(
            ".jpg", show_img, [cv2.IMWRITE_JPEG_QUALITY, 90]
        )
        if not success:
            self.get_logger().error("Failed to encode image")
            return

        mimg = CompressedImage()
        mimg.header = header
        mimg.format = "jpeg"
        mimg.data = encoded_image.tobytes()
        self.vis_pub.publish(mimg)


def main(args=None):
    rclpy.init(args=args)
    node = QRCodeReader()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
