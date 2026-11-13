"""Person attribute recognition node.

The model is loaded from ``model_file`` when the file exists.  Otherwise it
is downloaded from the Hugging Face Hub (``model_repo_id``,
``model_filename``, ``model_revision``; requires huggingface_hub) and cached
under ``~/.cache/huggingface`` (or ``$HF_HOME``), so the download happens only
once.  Set ``HF_HUB_OFFLINE=1`` to use the cached file without network access.
"""

import message_filters
import rclpy
from action_recognition.model_loader import (DEFAULT_REPO_ID, DEFAULT_REVISION,
                                             resolve_model_path)
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons
from sensor_msgs.msg import CompressedImage

from .attribute_recognizer import AttributeRecognizer
from .gpu_check import log_torch_device
from .image_processing_node import IMAGE_QOS


class AttributeRecognitionNode(Node):
    def __init__(self, name="AttributeRecognitionNode"):
        super().__init__(name)
        # self.declare_parameter("model_file", "attributes.pth")
        # local model file, used when it exists
        self.declare_parameter("model_file", "attributes_pa100kb.pth")
        # Hugging Face repository to download from ("": no download)
        self.declare_parameter("model_repo_id", DEFAULT_REPO_ID)
        # file name in the repository ("": basename of model_file)
        self.declare_parameter("model_filename", "")
        # branch, tag or commit hash
        self.declare_parameter("model_revision", DEFAULT_REVISION)
        # keypoint confidence above which ears / ankles count as visible
        self.declare_parameter("keypoint_thresh", 0.5)
        model_file = resolve_model_path(
            self.get_parameter("model_file").value,
            repo_id=self.get_parameter("model_repo_id").value,
            filename=self.get_parameter("model_filename").value,
            revision=self.get_parameter("model_revision").value,
            logger=self.get_logger(),
        )
        self.get_logger().info(f"attribute model: {model_file}")
        self.keypoint_thresh = self.get_parameter("keypoint_thresh").value

        self.bridge = CvBridge()

        self.pub = self.create_publisher(
            Persons, "out_topic", qos_profile=qos.qos_profile_system_default
        )
        sub_image = message_filters.Subscriber(
            self, CompressedImage, "in_color_topic", qos_profile=IMAGE_QOS
        )
        sub_person = message_filters.Subscriber(
            self, Persons, "in_person_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub = message_filters.ApproximateTimeSynchronizer(
            [sub_image, sub_person], 100, 0.5
        )
        self.sub.registerCallback(self.callback)

        self.attribute_recognizer = AttributeRecognizer(model_file)
        log_torch_device(
            self.get_logger(), "Attribute recognizer", self.attribute_recognizer.model
        )

    def callback(self, imgmsg, persons):
        targets = [
            i
            for i, person in enumerate(persons.persons)
            if len(person.pose.confidences) > 0 and self.is_fullbody(person)
        ]
        results = [None] * len(persons.persons)
        if targets:
            # decode the image only when somebody needs attributes
            img = self.bridge.compressed_imgmsg_to_cv2(imgmsg, "bgr8")
            img_h, img_w = img.shape[:2]

            imgs = []
            img_indices = []
            for i in targets:
                x, y, w, h = map(int, persons.persons[i].body_location)
                x2 = min(x + w, img_w)
                y2 = min(y + h, img_h)
                x = max(0, x)
                y = max(0, y)
                if x2 <= x or y2 <= y:  # empty crop
                    continue
                imgs.append(img[y:y2, x:x2])
                img_indices.append(i)

            if imgs:
                for i, att in zip(img_indices, self.attribute_recognizer(imgs)):
                    results[i] = att

        self.publish(persons, results)

    def publish(self, persons, results):
        for p, attributes in zip(persons.persons, results):
            if attributes is None:
                continue
            for att_name, conf in attributes.items():
                p.attributes.append(att_name)
                p.attribute_confidences.append(float(conf))

        self.pub.publish(persons)

    def is_fullbody(self, person):
        confs = person.pose.confidences
        if len(confs) < 17:
            return False
        th = self.keypoint_thresh

        ears = confs[3] > th or confs[4] > th
        ankles = confs[15] > th or confs[16] > th

        return ears and ankles


def main():
    rclpy.init()
    node = AttributeRecognitionNode()
    rclpy.spin(node)
    rclpy.shutdown()
