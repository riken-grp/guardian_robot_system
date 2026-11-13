import numpy as np
import rclpy
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons, Pointing, Pointings


class ArmStateRecognizer:
    def __init__(self, keypoint_indices, confidence_threshold):
        self.keypoint_indices = keypoint_indices
        self.confidence_threshold = confidence_threshold

    def __call__(self, persons):
        hands = []
        for p in persons.persons:
            kps = np.array(p.pose_sensor.keypoints).reshape((-1, 3))
            confs = p.pose_sensor.confidences

            left_hand_raising = False
            right_hand_raising = False

            if len(confs) != 0:
                left_hand_raising = self.check_raising(
                    kps[self.keypoint_indices["l_ear"]],
                    kps[self.keypoint_indices["l_wrist"]],
                    confs[self.keypoint_indices["l_ear"]],
                    confs[self.keypoint_indices["l_wrist"]],
                )
                right_hand_raising = self.check_raising(
                    kps[self.keypoint_indices["r_ear"]],
                    kps[self.keypoint_indices["r_wrist"]],
                    confs[self.keypoint_indices["r_ear"]],
                    confs[self.keypoint_indices["r_wrist"]],
                )
            hands.append((left_hand_raising, right_hand_raising))

        return hands

    def check_raising(self, ear, wrist, ear_conf, wrist_conf):
        if (
            ear_conf > self.confidence_threshold
            and wrist_conf > self.confidence_threshold
        ):
            if ear[0] == 0.0 and ear[1] == 0.0:
                return False
            if wrist[0] == 0.0 and wrist[1] == 0.0:
                return False
            if ear[1] > wrist[1]:
                return True
        return False


class ArmStateNode(Node):
    def __init__(self, name="ArmStateNode"):
        super().__init__(name)

        # Declare parameters
        self.declare_parameter("keypoint_indices.l_ear", 1)
        self.declare_parameter("keypoint_indices.l_wrist", 9)
        self.declare_parameter("keypoint_indices.r_ear", 2)
        self.declare_parameter("keypoint_indices.r_wrist", 10)
        self.declare_parameter("confidence_threshold", 0.8)

        # Get parameters
        keypoint_indices = {
            "l_ear": self.get_parameter("keypoint_indices.l_ear")
            .get_parameter_value()
            .integer_value,
            "l_wrist": self.get_parameter("keypoint_indices.l_wrist")
            .get_parameter_value()
            .integer_value,
            "r_ear": self.get_parameter("keypoint_indices.r_ear")
            .get_parameter_value()
            .integer_value,
            "r_wrist": self.get_parameter("keypoint_indices.r_wrist")
            .get_parameter_value()
            .integer_value,
        }
        confidence_threshold = (
            self.get_parameter("confidence_threshold")
            .get_parameter_value()
            .double_value
        )

        input_persons_topic = "in_person_topic"
        output_topic = "out_topic"
        self.get_logger().info(f"Output Topic: {output_topic}")
        self.get_logger().info(f"Input Persons Topic: {input_persons_topic}")
        self.get_logger().info(f"Keypoint Indices: {keypoint_indices}")
        self.get_logger().info(f"Confidence Threshold: {confidence_threshold}")

        self.state_recognizer = ArmStateRecognizer(
            keypoint_indices=keypoint_indices, confidence_threshold=confidence_threshold
        )
        self.pub = self.create_publisher(
            Pointings, output_topic, qos_profile=qos.qos_profile_system_default
        )
        self.sub = self.create_subscription(
            Persons,
            input_persons_topic,
            self.callback,
            qos_profile=qos.qos_profile_system_default,
        )

    def callback(self, persons):
        results = self.state_recognizer(persons)
        self.publish(persons.header, persons, results)

    def publish(self, header, persons, hands):
        results = Pointings()
        results.header = header

        for p, h in zip(persons.persons, hands):
            pointing = Pointing()
            pointing.header = header
            pointing.instance_id = p.instance_id
            pointing.name = p.name
            pointing.class_id = p.class_id
            pointing.raising_left_hand = h[0]
            pointing.raising_right_hand = h[1]
            results.pointings.append(pointing)

        self.pub.publish(results)


def main():
    rclpy.init()
    node = ArmStateNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
