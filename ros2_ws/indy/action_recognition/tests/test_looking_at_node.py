import rclpy
import pytest
from action_recognition.looking_at_node import LookingAtNode


def test_looking_at_node_initialization():
    rclpy.init()
    try:
        node = LookingAtNode()
        node.destroy_node()
    finally:
        rclpy.shutdown()