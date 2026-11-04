from launch import LaunchDescription
from launch_ros.actions import Node
import launch

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    return LaunchDescription([
        Node(
            package='auto_charge',
            executable='auto_charge',
            namespace=robot_name,
            on_exit = launch.actions.Shutdown()
        ),
        Node(
            package='auto_charge',
            executable='lidar_marker_finder',
            namespace=robot_name,
            on_exit = launch.actions.Shutdown()
        ),
        Node(
            package='auto_charge',
            executable='navigate_to_charge_server',
            namespace=robot_name,
            on_exit = launch.actions.Shutdown()
        ),
    ])