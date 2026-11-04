import os

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import Shutdown


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return

    return LaunchDescription(
        [
            Node(
                package="asr",
                executable="asr_metadata",
                namespace=robot_name,
                on_exit=Shutdown()
            ),
        ]
    )
