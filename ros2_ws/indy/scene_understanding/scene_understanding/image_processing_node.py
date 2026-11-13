import struct
import time
from typing import Optional

import cv2
import numpy as np
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import (HistoryPolicy, QoSProfile, ReliabilityPolicy,
                       qos_profile_system_default)
from sensor_msgs.msg import CameraInfo, CompressedImage

from .rgbd_matcher import RgbdMatcher

# QoS for camera image / depth subscriptions: BEST_EFFORT with a small queue so
# that a slow node always processes the latest frames instead of a backlog of
# stale ones.  BEST_EFFORT subscribers match both RELIABLE and BEST_EFFORT
# publishers.
IMAGE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=2,
)


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
            # Match color and depth by stamp (see rgbd_matcher.py; robust to a
            # depth stream arriving later than the color stream)
            self.declare_parameter("rgbd_slop", 0.1)  # max stamp difference [s]
            self.declare_parameter("rgbd_buffer_duration", 2.0)  # [s]
            self.declare_parameter("rgbd_stats_period", 10.0)  # [s], <= 0: no log
            self.rgbd_matcher = RgbdMatcher(
                slop_sec=float(self.get_parameter("rgbd_slop").value),
                buffer_sec=float(self.get_parameter("rgbd_buffer_duration").value),
            )
            self.image_sub = self.create_subscription(
                CompressedImage,
                image_topic,
                self._rgbd_color_callback,
                qos_profile=IMAGE_QOS,
            )
            self.depth_sub = self.create_subscription(
                CompressedImage,
                depth_topic,
                self._rgbd_depth_callback,
                qos_profile=IMAGE_QOS,
            )
            period = float(self.get_parameter("rgbd_stats_period").value)
            self._rgbd_stats_t0 = time.monotonic()
            if period > 0:
                self.create_timer(period, self._log_rgbd_stats)
        else:
            # Individual subscriptions when not synchronizing
            if subscribe_image:
                self.image_sub = self.create_subscription(
                    CompressedImage,
                    image_topic,
                    self._image_callback,
                    qos_profile=IMAGE_QOS,
                )
            else:
                self.image_sub = None

            if subscribe_depth:
                self.depth_sub = self.create_subscription(
                    CompressedImage,
                    depth_topic,
                    self._depth_callback,
                    qos_profile=IMAGE_QOS,
                )
            else:
                self.depth_sub = None

        self.get_logger().info(f"'{node_name}' node has been initialized.")

    def _decode_compressed_depth(self, compressed_depth_msg):
        """Decode a compressedDepth message to a numpy array.

        Returns a uint16 image in millimeters for ``16UC1`` and a float32 image
        in meters for ``32FC1``, or None if decoding fails.
        """
        fmt = compressed_depth_msg.format.lower()
        data = bytes(compressed_depth_msg.data)
        if "rvl" in fmt:
            self.get_logger().error(
                f"Unsupported compressedDepth format '{compressed_depth_msg.format}'; use png.",
                throttle_duration_sec=5.0,
            )
            return None
        # compressedDepthメッセージには12バイトのヘッダー(format, depthQuantA, depthQuantB)がある
        # PNGシグネチャを探してヘッダー以降をデコード
        start = data.find(b"\x89PNG")
        if start < 0:
            start = 12
        depth_img = cv2.imdecode(np.frombuffer(data[start:], np.uint8), cv2.IMREAD_UNCHANGED)
        if depth_img is None:
            self.get_logger().error(
                "Failed to decode compressedDepth image.", throttle_duration_sec=5.0
            )
            return None
        if "32fc1" in fmt and depth_img.dtype == np.uint16 and start >= 12:
            # 32FC1 is quantized as inverse depth: depth = quantA / (value - quantB)
            quant_a, quant_b = struct.unpack("<ff", data[4:12])
            inv = depth_img.astype(np.float32)
            depth_m = np.zeros_like(inv)
            valid = inv > 0
            depth_m[valid] = quant_a / (inv[valid] - quant_b)
            depth_img = depth_m
        return depth_img

    def _depth_callback(self, msg: CompressedImage):
        """Store the latest depth message for later processing (used when not synchronizing)."""
        cv_depth = self._decode_compressed_depth(msg)
        if cv_depth is None:
            return
        self.process_depth(msg.header, cv_depth)

    @staticmethod
    def _stamp_ns(msg):
        return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec

    def _rgbd_color_callback(self, msg: CompressedImage):
        pair = self.rgbd_matcher.add_color(self._stamp_ns(msg), msg, time.monotonic())
        if pair is not None:
            self._rgbd_callback(*pair)

    def _rgbd_depth_callback(self, msg: CompressedImage):
        pair = self.rgbd_matcher.add_depth(self._stamp_ns(msg), msg, time.monotonic())
        if pair is not None:
            self._rgbd_callback(*pair)

    def _log_rgbd_stats(self):
        now = time.monotonic()
        stats = self.rgbd_matcher.reset_stats()
        self.get_logger().info(
            stats.format(
                now - self._rgbd_stats_t0,
                len(self.rgbd_matcher.colors),
                len(self.rgbd_matcher.depths),
            )
        )
        self._rgbd_stats_t0 = now

    def _rgbd_callback(self, img_msg: CompressedImage, depth_msg: CompressedImage):
        """Callback for synchronized image and depth messages.

        Decodes the depth image and forwards both the color image and depth to the
        dedicated processing method.
        """
        # Decode depth
        cv_depth = self._decode_compressed_depth(depth_msg)
        if cv_depth is None:
            return
        # Reuse existing image handling logic to get cv_image
        try:
            cv_image = self.bridge.compressed_imgmsg_to_cv2(
                img_msg, desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(
                f"Error converting image: {e}", throttle_duration_sec=5.0
            )
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
        if self.cinfo_cache is not None and self.camera_info is None:
            self.get_logger().warn(
                "Waiting for camera info...", throttle_duration_sec=5.0
            )
            return
        try:
            cv_image = self.bridge.compressed_imgmsg_to_cv2(
                msg, desired_encoding="bgr8"
            )
        except Exception as e:
            self.get_logger().error(
                f"Error converting image: {e}", throttle_duration_sec=5.0
            )
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

    @staticmethod
    def has_subscribers(publisher) -> bool:
        """True if ``publisher`` exists and somebody subscribes to it.

        Check this before building visualization images to skip the copy /
        drawing / encoding when nobody watches them.
        """
        return publisher is not None and publisher.get_subscription_count() > 0

    def publish_compressed_image(self, publisher, header, cv_image, quality=90):
        if not self.has_subscribers(publisher):
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
