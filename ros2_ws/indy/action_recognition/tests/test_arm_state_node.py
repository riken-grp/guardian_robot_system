import rclpy
import pytest
from action_recognition.arm_state_node import ArmStateNode


def test_arm_state_node_initialization():
    rclpy.init()
    try:
        node = ArmStateNode()
        # If the node is created successfully, the test passes.
        # We are checking for any exceptions during initialization.
        node.destroy_node()
    finally:
        rclpy.shutdown()
