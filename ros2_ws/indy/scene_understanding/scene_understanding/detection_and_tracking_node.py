#!/usr/bin/env python3
import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.qos import qos_profile_system_default
from recognition_msgs.msg import Objects
from sensor_msgs.msg import CompressedImage
from tf2_ros import TransformBroadcaster
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from . import configs as cfg
from .image_processing_node import ImageProcessingNode
from .mapper import Sensor3DMapper
from .message_builders import ObjectMessageBuilder
from .object_detector import RTDetrTracker


class DetectionAndTrackingNode(ImageProcessingNode):
    def __init__(self, name="ObjectDetectionNode"):
        super().__init__(
            name, subscribe_camera_info=True, subscribe_depth=True, rgbd_sync=True
        )
        self._declare_parameters()
        self._initialize_components()
        self._initialize_publishers_and_subscribers()

    def _declare_parameters(self):
        self.declare_parameter("model", "PekingU/rtdetr_r101vd_coco_o365")
        self.declare_parameter("thresh", 0.7)
        self.declare_parameter("track_thresh", 0.5)
        self.declare_parameter("track_buffer", 300)
        self.declare_parameter("match_thresh", 0.8)
        self.declare_parameter("world_frame_id", "map")

    def _initialize_components(self):
        model = self.get_parameter("model").value
        self.thresh = self.get_parameter("thresh").value
        track_thresh = self.get_parameter("track_thresh").value
        track_buffer = self.get_parameter("track_buffer").value
        match_thresh = self.get_parameter("match_thresh").value
        world_frame_id = self.get_parameter("world_frame_id").value

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.mapper = Sensor3DMapper(self.tf_buffer, world_frame_id)

        self.det_proc = RTDetrTracker(
            model,
            track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=match_thresh,
        )

        self.message_builder = ObjectMessageBuilder(self.det_proc.names)

        # TF Broadcaster
        self.br = TransformBroadcaster(self)

    def _initialize_publishers_and_subscribers(self):
        self.pub = self.create_publisher(
            Objects, "out_topic", qos_profile=qos_profile_system_default
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

        Uses the cached CameraInfo from the base class and the most recent depth
        message stored by ``_depth_callback``.
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
        # Run detection
        detections = self.det_proc.track(cv_image, conf=self.thresh)
        if len(detections) == 0 or len(detections[0]) < 7:
            return
        detections = detections[detections[:, cfg.CONFIDENCE_COLUMN] > self.thresh]
        detections[:, 2] = detections[:, 2] - detections[:, 0]
        detections[:, 3] = detections[:, 3] - detections[:, 1]
        detections3d = self.mapper.get_3d_value(detections, mdimg, cinfo)
        self.publish(header, detections3d, cv_image)

    def _tf_broadcast(self, header, detections):
        for det in detections:
            lo_sensor = det[cfg.LOCATION_SENSOR_COLUMN]
            if lo_sensor[2] < 0.01:
                continue
            t = TransformStamped()
            t.header.stamp = header.stamp
            t.header.frame_id = header.frame_id
            t.child_frame_id = f"object_{int(det[cfg.INSTANCE_ID_COLUMN])}"
            t.transform.translation.x = float(lo_sensor[0])
            t.transform.translation.y = float(lo_sensor[1])
            t.transform.translation.z = float(lo_sensor[2])
            t.transform.rotation.x = 0.0
            t.transform.rotation.y = 0.0
            t.transform.rotation.z = 0.0
            t.transform.rotation.w = 1.0
            self.br.sendTransform(t)

    def publish(self, header, detections, img):
        msg, jsondata, markers, oimg = self.message_builder.build_from_tracklets(
            header, detections, img, self.pub_vis is not None
        )

        if self.pub_vis is not None:
            encoded_image = self._encode_image(oimg)
            if encoded_image is None:
                return
            mimg = CompressedImage()
            mimg.header = header
            mimg.format = "jpeg"
            mimg.data = encoded_image.tobytes()
            self.pub_vis.publish(mimg)

        self.pub.publish(msg)

    def _encode_image(self, oimg):
        success, encoded_image = cv2.imencode(
            ".jpg", oimg, [cv2.IMWRITE_JPEG_QUALITY, 90]
        )
        if not success:
            self.get_logger().error("Failed to encode image")
            return None
        return encoded_image


def main():
    rclpy.init()
    node = DetectionAndTrackingNode()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()
