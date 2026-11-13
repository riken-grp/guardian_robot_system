import rclpy
import pytest
from action_recognition.gaze_data_saver_node import GazeDataSaverNode


def test_gaze_data_saver_node_initialization():
    rclpy.init()
    try:
        node = GazeDataSaverNode()
        # If the node is created successfully, the test passes.
        # We are checking for any exceptions during initialization.
        node.destroy_node()
    finally:
        rclpy.shutdown()
