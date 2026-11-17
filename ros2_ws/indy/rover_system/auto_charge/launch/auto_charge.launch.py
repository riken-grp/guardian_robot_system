from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
import launch

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    return LaunchDescription([
        # Overall time limit [s] of the navigate_to_charge action. RISM waits for
        # the dock up to executor.default_dock_timeout (200 s): keep this shorter
        # so that the robot returns failed first
        DeclareLaunchArgument('docking_timeout', default_value='180.0'),
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
            parameters=[{
                'docking_timeout': ParameterValue(
                    LaunchConfiguration('docking_timeout'), value_type=float),
            }],
            on_exit = launch.actions.Shutdown()
        ),
    ])