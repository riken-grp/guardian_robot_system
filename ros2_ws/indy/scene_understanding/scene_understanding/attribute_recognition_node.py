import message_filters
import rclpy
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons
from sensor_msgs.msg import CompressedImage

from .attribute_recognizer import AttributeRecognizer


class AttributeRecognitionNode(Node):
    def __init__(self, name="AttributeRecognitionNode"):
        super().__init__(name)
        # self.declare_parameter("model_file", "attributes.pth")
        self.declare_parameter("model_file", "attributes_pa100kb.pth")
        model_file = self.get_parameter("model_file").value

        self.bridge = CvBridge()

        self.pub = self.create_publisher(
            Persons, "out_topic", qos_profile=qos.qos_profile_system_default
        )
        sub_image = message_filters.Subscriber(
            self, CompressedImage, "in_color_topic", qos_profile=qos.qos_profile_system_default
        )
        sub_person = message_filters.Subscriber(
            self, Persons, "in_person_topic", qos_profile=qos.qos_profile_system_default
        )
        self.sub = message_filters.ApproximateTimeSynchronizer(
            [sub_image, sub_person], 100, 0.5
        )
        self.sub.registerCallback(self.callback)

        self.attribute_recognizer = AttributeRecognizer(model_file)

    def callback(self, imgmsg, persons):
        img = self.bridge.compressed_imgmsg_to_cv2(imgmsg, "bgr8")

        imgs = []
        masks = []
        for person in persons.persons:
            if len(person.pose.confidences) > 0 and self.is_fullbody(person):
                x, y, w, h = map(int, person.body_location)
                x = max(0, x)
                y = max(0, y)
                x2 = min(x + w, img.shape[1] - 1)
                y2 = min(y + h, img.shape[1] - 1)
                pimg = img[y:y2, x:x2]
                imgs.append(pimg)
                masks.append(True)
            else:
                masks.append(False)

        if len(imgs) != 0:
            results_tmp = self.attribute_recognizer(imgs)

        results = []
        j = 0
        for i, m in enumerate(masks):
            if m:
                results.append(results_tmp[j])
                j += 1
            else:
                results.append(None)

        self.publish(persons, results)

    def publish(self, persons, results):
        for p, attributes in zip(persons.persons, results):
            if attributes is None:
                continue
            for att_name, conf in attributes.items():
                p.attributes.append(att_name)
                p.attribute_confidences.append(conf)

        self.pub.publish(persons)

    def is_fullbody(self, person):
        confs = person.pose.confidences

        ears = confs[3] > 0 or confs[4] > 0
        ankles = confs[15] > 0 or confs[16] > 0

        return ears and ankles


def main():
    rclpy.init()
    node = AttributeRecognitionNode()
    rclpy.spin(node)
    rclpy.shutdown()
