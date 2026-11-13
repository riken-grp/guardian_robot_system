#!/usr/bin/env python
# coding: utf-8

import json

import cv2
import message_filters
import numpy as np
import rclpy
from common_msgs.msg import StringStamped
from cv_bridge import CvBridge
from rclpy import qos
from rclpy.node import Node
from recognition_msgs.msg import Persons
from sensor_msgs.msg import Image

from action_recognition.base_recognition_node import (BaseRecognitionNode,
                                                      recognition_node_main)
from action_recognition.model_loader import (declare_model_parameters,
                                             load_model_from_node)


class LookingAtRecognizer:
    def __init__(self, node_instance):  # Accept node instance
        self.lookingat_recognizer = load_model_from_node(node_instance)

    def __call__(self, persons):
        if len(persons.persons) == 0:
            return []
        features = np.array(
            [p.face_location + p.face_orientation for p in persons.persons]
        )
        rets = self.lookingat_recognizer.predict(features)

        return rets


class LookingAtNode(BaseRecognitionNode):
    def __init__(self, name="LookingAtNode"):
        super().__init__(
            node_name=name,
            image_topic="in_topic",
            persons_topic="in_person_topic",
            output_topic="out_topic",
            vis_topic="vis_topic",
        )

    def _create_recognizer(self):
        # Declare specific parameters for this node here, after super().__init__ has run
        declare_model_parameters(self, "models/looking_at_model.joblib")
        # Note: Common topics parameters are declared in BaseRecognitionNode

        self.state_recognizer = LookingAtRecognizer(
            node_instance=self  # Pass the node instance
        )


def main():
    recognition_node_main(LookingAtNode)
