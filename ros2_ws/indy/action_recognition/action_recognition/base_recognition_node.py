import json

import cv2
import numpy as np
import rclpy
from common_msgs.msg import StringStamped
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons
from sensor_msgs.msg import CompressedImage


def normalize_keypoints(data):
    """Center 3D keypoints (flattened N x 3) by the mean of the valid points.

    Keypoints with missing depth are (0, 0, 0) (z <= 0) and are excluded from
    the mean.  After centering they are set to 0 so that the feature layout
    and dimension are unchanged (compatible with models trained on the same
    features).  When no keypoint is valid, all zeros are returned.
    """
    p = np.asarray(data, dtype=float).reshape(-1, 3)
    valid = (p[:, 2] > 0) & np.all(np.isfinite(p), axis=1)
    norm = np.zeros_like(p)
    if np.any(valid):
        norm[valid] = p[valid] - p[valid].mean(axis=0)
    return norm.reshape(-1)


class BaseRecognitionNode(Node):
    """
    Base class for ROS2 nodes that perform action recognition.
    Encapsulates common functionalities like parameter declaration,
    subscriber/publisher setup and result publishing.

    Recognition runs in the Persons callback only (no time synchronization
    with the image), so results are never dropped because of the upstream
    latency.  The image topic is used only for the visualization: the latest
    CompressedImage message is cached (not decoded), and it is decoded, drawn
    and re-encoded as JPEG only when the visualization topic has subscribers.
    """

    def __init__(
        self,
        node_name,
        image_topic="in_topic",
        persons_topic="in_person_topic",
        output_topic="out_topic",
        vis_topic="vis_topic",
    ):  # Removed recognition_class argument
        super().__init__(node_name)
        self.image_topic = image_topic
        self.persons_topic = persons_topic
        self.output_topic = output_topic
        self.vis_topic = vis_topic

        self.get_logger().info(f"Node Name: {node_name}")
        self.get_logger().info(f"Output Topic: {self.output_topic}")
        self.get_logger().info(f"Visualization Topic: {self.vis_topic}")
        self.get_logger().info(f"Input Image Topic: {self.image_topic}")
        self.get_logger().info(f"Input Persons Topic: {self.persons_topic}")

        sdq = qos.qos_profile_system_default
        self.pub = self.create_publisher(
            StringStamped, self.output_topic, qos_profile=sdq
        )
        # visualization is published as a JPEG CompressedImage
        # (the topic is named ".../visualized/compressed")
        self.vis_pub = self.create_publisher(
            CompressedImage, self.vis_topic, qos_profile=sdq
        )

        self._latest_image = None  # latest CompressedImage msg (not decoded)
        # only the latest image is needed for the visualization
        img_qos = qos.QoSProfile(
            depth=1, reliability=qos.ReliabilityPolicy.BEST_EFFORT
        )
        self.sub_img = self.create_subscription(
            CompressedImage, self.image_topic, self._image_callback, img_qos
        )
        self.sub_persons = self.create_subscription(
            Persons, self.persons_topic, self.callback, sdq
        )

        # The actual recognition logic will be instantiated by the inheriting class
        # after its specific parameters are declared.
        self.state_recognizer = None
        self._create_recognizer()  # Call the method that inheriting class implements

    def _create_recognizer(self):
        """
        Abstract method to be implemented by inheriting classes to instantiate
        their specific recognition logic (e.g., WavingHandRecognizer).
        """
        raise NotImplementedError(
            "Inheriting classes must implement _create_recognizer method."
        )

    def _image_callback(self, imgmsg):
        self._latest_image = imgmsg

    def callback(self, persons):
        results = self.state_recognizer(persons)
        self.publish(persons.header, persons, results)
        if self.vis_pub.get_subscription_count() > 0 and self._latest_image is not None:
            self.publish_visualization(self._latest_image, persons, results)

    def publish(self, header, persons, recognition_results):
        results = StringStamped()
        results.header = header

        # persons without an associated track (instance_id < 0, possibly
        # several per frame) cannot be keyed by instance_id -> skipped
        data = {}
        for p, e in zip(persons.persons, recognition_results):
            if int(p.instance_id) < 0:
                continue
            data[int(p.instance_id)] = int(e)

        results.data = json.dumps(data)
        self.pub.publish(results)

    def publish_visualization(self, imgmsg, persons, recognition_results):
        img = cv2.imdecode(np.frombuffer(imgmsg.data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self.get_logger().warn("Failed to decode the image for visualization")
            return

        # Draw bounding boxes and results
        for p, e in zip(persons.persons, recognition_results):
            if len(p.body_location) >= 4:
                self._bb_draw(p.body_location, e, img)
            if len(p.face_location) >= 4:
                self._bb_draw(p.face_location, e, img)

        ok, buf = cv2.imencode(".jpg", img)
        if not ok:
            return
        vmsg = CompressedImage()
        vmsg.header = imgmsg.header
        vmsg.format = "jpeg"
        vmsg.data = buf.tobytes()
        self.vis_pub.publish(vmsg)

    def _bb_draw(self, location, e, img):
        x, y, w, h = map(int, location)  # assuming body_location for drawing
        l, t, r, b = x, y, x + w, y + h
        e = int(e)
        color = (
            (0, 255, 0) if e == 1 else (255, 0, 0)
        )  # Green for recognized, Red for not
        cv2.rectangle(img, (l, t), (r, b), color, 3)


def recognition_node_main(node_class):  # Removed recognition_class argument
    rclpy.init()
    node = node_class()  # Removed recognition_class argument
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
