#!/usr/bin/env python
# coding: utf-8 -*-

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.qos import qos_profile_system_default
from recognition_msgs.msg import Person, Persons
from sensor_msgs.msg import CompressedImage
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from . import configs as cfg
from .dlib_face_detector import FaceDetector
from .head_pose_estimator import HeadPoseEstimator
from .image_processing_node import ImageProcessingNode
from .mapper import Sensor3DMapper
from .message_builders import PersonMessageBuilder


class HeadPoseEstimationNode(ImageProcessingNode):  # Inherit from ImageProcessingNode
    def __init__(self, name="HeadPoseEstimationNode"):
        super().__init__(
            name,
            subscribe_image=True,
            subscribe_camera_info=True,
            subscribe_depth=True,
            rgbd_sync=True,
        )  # Call base class constructor
        self._declare_parameters()
        self._initialize_components()
        self._initialize_publishers_and_subscribers()

    def _declare_parameters(self):
        self.declare_parameter("model", "hopenet_alpha1.pkl")
        self.declare_parameter("device", "cuda")
        self.declare_parameter("world_frame_id", "map")

    def _initialize_components(self):
        model = self.get_parameter("model").value
        device = self.get_parameter("device").value
        world_frame_id = self.get_parameter("world_frame_id").value

        self.face_detector = FaceDetector()
        self.estimator = HeadPoseEstimator(model, device)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.mapper = Sensor3DMapper(self.tf_buffer, world_frame_id)

        self.person_message_builder = PersonMessageBuilder()
        self.tracking_targets = {}

        self.register_camera_info_ready_callback(self._camera_info_ready)

    def _camera_info_ready(self):
        # This will be called when camera_matrix and dist_coeffs are available from the base class
        self.get_logger().info(
            "HeadPoseEstimationNode: Camera info is now ready from base class."
        )

    def _initialize_publishers_and_subscribers(self):
        self.pub = self.create_publisher(
            Persons, "out_topic", qos_profile=qos_profile_system_default
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
        self.mapper.update_tf(cinfo.header.frame_id, header.stamp)
        # Decode depth
        mdimg = cv2.medianBlur(cv_depth, ksize=5)
        # Face detection
        faces = self.face_detector(cv_image)
        face_bbs = self._extract_face_bounding_boxes(faces)
        if len(face_bbs) == 0:
            self._publish_empty_results(header, cv_image)
            return
        # 3D faces
        faces3d = self.mapper.get_3d_value(face_bbs, mdimg, cinfo)
        persons, vimg = self._process_faces(header, cv_image, face_bbs, faces3d)
        self._publish_results(header, persons, vimg)

    def _extract_face_bounding_boxes(self, faces):
        return np.asarray(
            [
                [
                    face.rect.left(),
                    face.rect.top(),
                    face.rect.right() - face.rect.left(),
                    face.rect.bottom() - face.rect.top(),
                    -1,
                    -1,
                    -1,
                ]
                for face in faces
            ]
        )

    def _publish_empty_results(self, header, img):
        persons = Persons()
        persons.header = header
        self.pub.publish(persons)

        if self.pub_vis:
            self.publish_compressed_image(self.pub_vis, header, img)

    def _process_faces(self, header, img, face_bbs, faces3d):
        persons = Persons()
        persons.header = header
        vimg = np.copy(img)

        for face, face3d in zip(face_bbs, faces3d):
            person, vimg = self._process_single_face(img, face, face3d, vimg)
            persons.persons.append(person)

        return persons, vimg

    def _process_single_face(self, img, face, face3d, vimg):
        x, y, w, h = face[:4]
        r, b = x + w, y + h
        person = Person()
        head_pose = self.estimator.estimate(img, [x, y, r, b])
        person.face_location = list(map(float, [x, y, w, h]))
        person.face_location_sensor = face3d[cfg.LOCATION_SENSOR_COLUMN].tolist()
        person.face_location_global = face3d[cfg.LOCATION_GLOBAL_COLUMN].tolist()
        person.face_orientation = head_pose
        vimg = self.estimator.visualize(vimg, [x, y, r, b], head_pose)
        return person, vimg

    def _publish_results(self, header, persons, vimg):
        self.pub.publish(persons)
        if self.pub_vis:
            self.publish_compressed_image(self.pub_vis, header, vimg)

    # Removed _publish_visualization as base class provides publish_compressed_image


def main():
    rclpy.init()
    node = HeadPoseEstimationNode()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        rclpy.shutdown()
