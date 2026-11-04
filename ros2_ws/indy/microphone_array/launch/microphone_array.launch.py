import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration

ROBOT_NAME = os.getenv("ROBOT_NAME")


def generate_launch_description():
    microphone_array_path = get_package_share_directory("microphone_array")
    array_geometry_file = os.path.join(
        microphone_array_path, "config", "array_geometry.yaml"
    )

    device = LaunchConfiguration("device")
    declare_device = DeclareLaunchArgument("device", default_value="default")

    return LaunchDescription(
        [
            declare_device,
            Node(
                package="microphone_array",
                executable="microphone_array_node",
                name="microphone_array_node",
                namespace=ROBOT_NAME,
                parameters=[
                    {
                        "device": device,
                        "sample_rate": 16000,
                        "channels": 16,
                        "frames_per_block": 512,
                        "array_geometry_file": array_geometry_file,
                        "array_frame_id": f"{ROBOT_NAME}_microphone_array_base",
                    }
                ],
                on_exit=Shutdown(),
            ),
        ]
    )
