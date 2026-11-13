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

from .image_processing_node import IMAGE_QOS


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
            qos_profile=IMAGE_QOS,
        )

        # OpenCV Bridge
        self.bridge = CvBridge()

        self.qcd = cv2.QRCodeDetector()

    def detect_and_decode(self, frame):
        """Detect and decode the QR codes: (retval, decoded_info, points).

        detectAndDecodeMulti raises cv2.error when one of the candidates
        cannot be decoded (e.g. "mode 14 ... not implemented": an invalid /
        unsupported mode, usually a false detection), and then the other
        codes in the frame are lost too.  In that case the candidates are
        decoded one by one; the ones that fail get "" (as
        detectAndDecodeMulti does for undecodable codes).
        """
        try:
            retval, decoded_info, points, _ = self.qcd.detectAndDecodeMulti(frame)
            return retval, decoded_info, points
        except cv2.error as e:
            self.get_logger().debug(f"QR code decoding failed, decoding one by one: {e}")

        retval, points = self.qcd.detectMulti(frame)
        if not retval:
            return False, (), None
        decoded_info = []
        for p in points:
            try:
                # one candidate: points of shape (1, 4, 2)
                _, texts, _ = self.qcd.decodeMulti(frame, p.reshape(1, 4, 2))
                text = texts[0] if texts else ""
            except cv2.error:
                text = ""
            decoded_info.append(text or "")
        return True, tuple(decoded_info), points

    def image_callback(self, msg: CompressedImage):
        frame = self.bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="bgr8")
        try:
            retval, decoded_info, points = self.detect_and_decode(frame)
        except Exception as e:
            self.get_logger().error(
                f"QR code detection failed: {e}", throttle_duration_sec=5.0
            )
            retval = False

        if retval:
            outmsg = StringStamped()
            outmsg.header.stamp = msg.header.stamp
            outmsg.data = json.dumps(decoded_info)
            self.pub.publish(outmsg)

        # 検出画像をCompressedImageに変換してPublish (購読者がいる場合のみ)
        if self.vis_pub.get_subscription_count() == 0:
            return
        if retval:
            frame = cv2.polylines(frame, points.astype(int), True, (0, 255, 0), 3)
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
