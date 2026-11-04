#!/usr/bin/env python
# coding: utf-8 -*-

import cv2
import message_filters
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import SceneText
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from . import configs as cfg
from .mapper import Sensor3DMapper
from .scenetextrecog import SceneTextRecognizer


class SceneTextReadingNode(Node):
    def __init__(self, name="SceneTextReading"):
        super().__init__(name)
        self.declare_parameter("world_frame_id", "map")
        self.declare_parameter("threshold", 0.70)
        world_frame_id = self.get_parameter("world_frame_id").value
        threshold = self.get_parameter("threshold").value

        self.bridge = CvBridge()
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.mapper = Sensor3DMapper(self.tf_buffer, world_frame_id)

        self.scene_text_recog = SceneTextRecognizer(threshold)

        self.pub = self.create_publisher(
            SceneText, "out_topic", qos_profile=qos.qos_profile_system_default
        )
        _default_vis = self.get_namespace().rstrip("/") + "/vis_topic"
        if self.resolve_topic_name("vis_topic") != _default_vis:
            self.pub_vis = self.create_publisher(
                CompressedImage, "vis_topic", qos_profile=qos.qos_profile_system_default
            )
        else:
            self.pub_vis = None

        # Camera info (subscribe once and cache)
        self.camera_info = None
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            "cinfo_topic",
            self.camera_info_callback,
            qos_profile=qos.qos_profile_system_default,
        )

        sub_image = message_filters.Subscriber(
            self, Image, "in_color_topic", qos_profile=qos.qos_profile_system_default
        )
        sub_depth = message_filters.Subscriber(
            self, Image, "in_depth_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub = message_filters.ApproximateTimeSynchronizer(
            [sub_image, sub_depth], 100, 0.1
        )
        self.sub.registerCallback(self.callback)

    def camera_info_callback(self, msg: CameraInfo) -> None:
        """Receive camera info once and cache it."""
        self.camera_info = msg
        self.get_logger().info("Camera info received and cached.")
        # Unsubscribe after receiving once
        self.destroy_subscription(self.camera_info_sub)

    def callback(self, image, depth):
        # Skip if camera info not yet received
        if self.camera_info is None:
            return

        if not self.mapper.update_tf(image.header.frame_id, image.header.stamp):
            return

        img = self.bridge.imgmsg_to_cv2(image, "bgr8")
        dimg = self.bridge.imgmsg_to_cv2(depth)

        texts, vis_img = self.scene_text_recog(img, dimg)
        try:
            locations_3d, is_3d = self.get_3d(texts, dimg, self.camera_info)
        except Exception as e:
            self.get_logger().warn(f"Failed to compute 3D locations: {e}")
            return
        self.publish(depth.header, vis_img, texts, locations_3d, is_3d)

    def get_3d(self, texts, dimg, cinfo):
        if len(texts) == 0:
            return [], []
        centers = []

        for d in texts:
            bb, _, _ = d
            centers.append(np.mean(bb, axis=0))

        centers = np.array(centers)
        return self.mapper.get_3d(centers, dimg, cinfo)

    def publish(self, header, vis_img, texts, locations_3d, is_3d):
        if self.pub_vis is not None:
            success, encoded_image = cv2.imencode(
                ".jpg", vis_img, [cv2.IMWRITE_JPEG_QUALITY, 90]
            )
            if not success:
                self.get_logger().error("Failed to encode image")
                return
            mimg = CompressedImage()
            mimg.header = header
            mimg.format = "jpeg"
            mimg.data = encoded_image.tobytes()
            self.pub_vis.publish(mimg)

        omsg = SceneText()
        omsg.header = header
        for d, loc3d, flag in zip(texts, locations_3d, is_3d):
            if not flag:
                continue
            bb, content, conf = d
            omsg.texts.append(content)
            omsg.locations.extend(sum(bb, []))
            omsg.confidences.append(conf)
            omsg.xyz.extend(loc3d.tolist())
        self.pub.publish(omsg)


def main():
    rclpy.init()
    node = SceneTextReadingNode()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()
