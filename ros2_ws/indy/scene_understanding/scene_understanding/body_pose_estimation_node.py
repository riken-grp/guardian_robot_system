#!/usr/bin/env python
# coding: utf-8 -*-

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.qos import qos_profile_system_default
from recognition_msgs.msg import Persons
from sensor_msgs.msg import CompressedImage
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener
from visualization_msgs.msg import MarkerArray

from .image_processing_node import ImageProcessingNode
from .mapper import Sensor3DMapper
from .message_builders import PersonMessageBuilder
from .pose_estimator import RTMPoseEstimator


class PoseProc(ImageProcessingNode):
    def __init__(self, name="pose_and_face_node"):
        super().__init__(
            name,
            subscribe_image=True,
            subscribe_camera_info=True,
            subscribe_depth=True,
            rgbd_sync=True,
        )
        self._declare_parameters()
        self._initialize_components()
        self._initialize_publishers_and_subscribers()

    def _declare_parameters(self):
        self.declare_parameter("model", "balanced")
        self.declare_parameter("thresh", 0.3)
        self.declare_parameter("world_frame_id", "map")

    def _initialize_components(self):
        model = self.get_parameter("model").value
        self.thresh = self.get_parameter("thresh").value
        world_frame_id = self.get_parameter("world_frame_id").value

        self.pose_proc = RTMPoseEstimator(mode=model, score_thr=self.thresh)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.mapper = Sensor3DMapper(self.tf_buffer, world_frame_id)

        self.message_builder = PersonMessageBuilder()

    def _initialize_publishers_and_subscribers(self):
        self.pub = self.create_publisher(
            Persons, "out_topic", qos_profile=qos_profile_system_default
        )
        self.marker_pub = self.create_publisher(
            MarkerArray, "marker_topic", qos_profile=qos_profile_system_default
        )
        _default_vis = self.get_namespace().rstrip("/") + "/vis_topic"
        if self.resolve_topic_name("vis_topic") != _default_vis:
            self.pub_vis = self.create_publisher(
                CompressedImage, "vis_topic", qos_profile=qos_profile_system_default
            )
        else:
            self.pub_vis = None

    def process_image_with_depth(self, header, cv_image, cv_depth):
        """Process color image together with latest depth image.

        Uses cached camera info from base class and the stored depth message.
        """
        if self.pub is None:
            return
        if self.pub.get_subscription_count() == 0:
            if self.pub_vis is None:
                return
            if self.pub_vis.get_subscription_count() == 0:
                return

        cinfo = self.camera_info
        if cinfo is None:
            self.get_logger().warn("CameraInfo not available yet; skipping.")
            return
        # Update TF
        if not self.mapper.update_tf(cinfo.header.frame_id, header.stamp):
            self.get_logger().warn("World TF not available yet; location_global will be (0,0,0).")
        # Decode depth
        mdimg = cv2.medianBlur(cv_depth, ksize=5)
        # Pose estimation
        detections, poses = self._process_poses(cv_image)
        detections3d = self.mapper.get_3d_value(detections, mdimg, cinfo)
        poses3d = self.mapper.get_3d_pose(poses, mdimg, cinfo)
        self.publish(header, detections3d, poses3d, cv_image)

    def _process_poses(self, color_img):
        # Pose Estimation
        detections, poses = self.pose_proc.pose(color_img)

        # detections: xyxy, conf, class
        detections = detections[detections[:, 4] > self.thresh]
        detections[:, 2] = detections[:, 2] - detections[:, 0]
        detections[:, 3] = detections[:, 3] - detections[:, 1]

        return detections, poses

    def publish(self, header, detections3d, poses3d, color_img):
        msg, jsondata, markers, show_img = self.message_builder.build_from_tracklets(
            header, detections3d, poses3d, color_img, self.pub_vis is not None
        )

        self.pub.publish(msg)
        self.marker_pub.publish(markers)
        if self.pub_vis:
            self._publish_visualization(header, show_img)

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
        self.pub_vis.publish(mimg)


def main():
    rclpy.init()
    node = PoseProc()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()
