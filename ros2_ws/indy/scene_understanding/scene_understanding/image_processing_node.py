from typing import Optional

import cv2
import message_filters
import numpy as np
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from rclpy.qos import qos_profile_system_default
from sensor_msgs.msg import CameraInfo, CompressedImage


class CameraInfoCache:
    """Utility to subscribe to a ``CameraInfo`` topic once and cache the first message.

    The subscription is destroyed after the first message is received to avoid unnecessary traffic.
    """

    def __init__(self, node: Node, topic: str) -> None:
        self._node = node
        self._topic = topic
        self._camera_info: Optional[CameraInfo] = None
        self._sub = self._node.create_subscription(
            CameraInfo,
            self._topic,
            self._callback,
            qos_profile=qos_profile_system_default,
        )

    def _callback(self, msg: CameraInfo) -> None:
        self._camera_info = msg
        self._node.get_logger().info("CameraInfo cached; unsubscribing.")
        self._node.destroy_subscription(self._sub)
        self._sub = None  # type: ignore

    def get(self) -> Optional[CameraInfo]:
        return self._camera_info


class ImageProcessingNode(Node):
    def __init__(
        self,
        node_name,
        subscribe_image=True,
        subscribe_camera_info=True,
        image_topic="in_color_topic",
        cinfo_topic="cinfo_topic",
        subscribe_depth=False,
        depth_topic="in_depth_topic",
        rgbd_sync=False,
    ):
        super().__init__(node_name)
        self.bridge = CvBridge()
        self._camera_matrix = None
        self._dist_coeffs = None
        self._camera_info_msg = None
        self._camera_info_ready_callbacks = []
        self._rgbd_sync = rgbd_sync

        # Subscribers
        if subscribe_camera_info:
            # Create a CameraInfoCache which internally subscribes to the cinfo topic
            self.cinfo_cache = CameraInfoCache(self, cinfo_topic)
        else:
            self.cinfo_cache = None

        # Image & depth handling
        if subscribe_image and subscribe_depth and self._rgbd_sync:
            # Use ApproximateTimeSynchronizer to get synchronized image and depth
            sub_img = message_filters.Subscriber(
                self,
                CompressedImage,
                image_topic,
                qos_profile=qos_profile_system_default,
            )
            sub_depth = message_filters.Subscriber(
                self,
                CompressedImage,
                depth_topic,
                qos_profile=qos_profile_system_default,
            )
            self.ts = message_filters.ApproximateTimeSynchronizer(
                [sub_img, sub_depth], 10, 0.1
            )
            self.ts.registerCallback(self._rgbd_callback)
        else:
            # Individual subscriptions when not synchronizing
            if subscribe_image:
                self.image_sub = self.create_subscription(
                    CompressedImage,
                    image_topic,
                    self._image_callback,
                    qos_profile=qos.qos_profile_system_default,
                )
            else:
                self.image_sub = None

            if subscribe_depth:
                self.depth_sub = self.create_subscription(
                    CompressedImage,
                    depth_topic,
                    self._depth_callback,
                    qos_profile=qos.qos_profile_system_default,
                )
            else:
                self.depth_sub = None

        self.get_logger().info(f"'{node_name}' node has been initialized.")

    def _decode_compressed_depth(self, compressed_depth_msg):
        """Decode compressedDepth message to numpy array."""
        # compressedDepthメッセージには12バイトのヘッダーがある
        # ヘッダーをスキップしてPNG圧縮データをデコード
        np_arr = np.frombuffer(compressed_depth_msg.data[12:], np.uint8)
        depth_img = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
        return depth_img

    def _depth_callback(self, msg: CompressedImage):
        """Store the latest depth message for later processing (used when not synchronizing)."""
        cv_depth = self._decode_compressed_depth(msg)
        self.process_depth(msg.header, cv_depth)

    def _rgbd_callback(self, img_msg: CompressedImage, depth_msg: CompressedImage):
        """Callback for synchronized image and depth messages.

        Decodes the depth image and forwards both the color image and depth to the
        dedicated processing method.
        """
        # Decode depth
        cv_depth = self._decode_compressed_depth(depth_msg)
        # Reuse existing image handling logic to get cv_image
        try:
            cv_image = self.bridge.compressed_imgmsg_to_cv2(
                img_msg, desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(f"Error converting image: {e}")
            return
        # Call the depth‑aware processing method
        self.process_image_with_depth(img_msg.header, cv_image, cv_depth)

    @property
    def camera_info(self) -> Optional[CameraInfo]:
        """Expose the cached CameraInfo message (may be None)."""
        if self.cinfo_cache:
            return self.cinfo_cache.get()
        return None

    @property
    def dist_coeffs(self):
        return self._dist_coeffs

    def register_camera_info_ready_callback(self, callback):
        self._camera_info_ready_callbacks.append(callback)
        if self._camera_matrix is not None and self._dist_coeffs is not None:
            callback()

    def _image_callback(self, msg: CompressedImage):
        if self._camera_matrix is None or self._dist_coeffs is None:
            self.get_logger().warn("Waiting for camera info...")
            return
        try:
            cv_image = self.bridge.compressed_imgmsg_to_cv2(
                msg, desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(f"Error converting image: {e}")
            return
        self.process_image(msg.header, cv_image)

    def process_image(self, header, cv_image):
        """Override in subclass to implement processing without depth.

        Called when only a color image is received (non‑sync mode).
        """
        self.get_logger().warn("process_image method not implemented by child class.")
        pass

    def process_depth(self, header, cv_image):
        """Override in subclass to implement processing without depth.

        Called when only a color image is received (non‑sync mode).
        """
        self.get_logger().warn("process_depth method not implemented by child class.")
        pass

    def process_image_with_depth(self, header, cv_image, cv_depth):
        """Override in subclass to implement processing when both color and depth are synchronized.

        The default implementation simply forwards to ``process_image`` for
        backward compatibility.
        """
        self.get_logger().warn(
            "process_image_with_depth method not implemented by child class; falling back to process_image."
        )
        # Fallback – subclasses that only implement ``process_image`` will still work.
        self.process_image(header, cv_image)

    def publish_compressed_image(self, publisher, header, cv_image, quality=90):
        if not publisher.get_subscription_count() > 0:
            return
        success, encoded_image = cv2.imencode(
            ".jpg", cv_image, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        if not success:
            self.get_logger().error("Failed to encode image for visualization.")
            return
        compressed_msg = CompressedImage()
        compressed_msg.header = header
        compressed_msg.format = "jpeg"
        compressed_msg.data = encoded_image.tobytes()
        publisher.publish(compressed_msg)
