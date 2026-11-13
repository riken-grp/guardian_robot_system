import joblib
import numpy as np
import rclpy
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons


class GazeDataSaverNode(Node):
    def __init__(self, name="GazeDataSaver"):
        super().__init__(name)

        # Declare parameters
        self.declare_parameter("class_id", 0)
        self.declare_parameter("output_file", "gaze_data.joblib")

        # Get parameters
        self.class_id = (
            self.get_parameter("class_id").get_parameter_value().integer_value
        )
        self.output_file = (
            self.get_parameter("output_file").get_parameter_value().string_value
        )

        input_persons_topic = "in_person_topic"
        self.get_logger().info(f"Class ID: {self.class_id}")
        self.get_logger().info(f"Output File: {self.output_file}")
        self.get_logger().info(f"Input Persons Topic: {input_persons_topic}")

        self.data = []

        self.sub = self.create_subscription(
            Persons,
            input_persons_topic,
            self.callback,
            qos_profile=qos.qos_profile_system_default,
        )

    def callback(self, persons):
        for p in persons.persons:
            self.data.append(p.face_location + p.face_orientation)

    def save(self):
        data = np.array(self.data)
        labels = [self.class_id] * len(data)
        joblib.dump((data, labels), self.output_file)


def main():
    rclpy.init()
    node = GazeDataSaverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.save()
    node.destroy_node()
    rclpy.shutdown()
