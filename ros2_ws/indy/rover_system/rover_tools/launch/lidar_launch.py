import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

import launch
from launch.actions import GroupAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    rover_tools_launch_file_dir = get_package_share_directory('rover_tools')
    lidar_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_tools_launch_file_dir, '/urg_node2_2lidar.launch.py'])
    )
    ht_lidar_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_tools_launch_file_dir, '/urg_node2_ht_lidar.launch.py'])
    )

    laser_tools_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_tools_launch_file_dir, '/laserscan_multi_merger_launch.py'])
    )

    return launch.LaunchDescription([
        GroupAction([
            laser_tools_launch,
            PushRosNamespace(robot_name),
            lidar_launch,
            ht_lidar_launch,
        ])
    ])
