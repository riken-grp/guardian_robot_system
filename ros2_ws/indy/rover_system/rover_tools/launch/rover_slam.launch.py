from launch import LaunchDescription
from launch_ros.actions import PushRosNamespace, Node
from launch.actions import IncludeLaunchDescription, GroupAction,Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    rover_tools_share_dir = get_package_share_directory("rover_tools")

    return LaunchDescription([
        GroupAction([
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_tools_share_dir + "/localization_launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_tools_share_dir + "/navigation_launch.py"]
                )
            ),
        ])
    ])
