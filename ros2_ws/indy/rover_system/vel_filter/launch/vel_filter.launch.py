from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import Shutdown
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition, UnlessCondition

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    package_path = get_package_share_directory('vel_filter')
    config_file = os.path.join(
        package_path,
        'default_param.yaml'
    )
    vel_filter_node = Node(
        package='vel_filter',
        executable='velfilter_node',
        namespace=robot_name,
        parameters=[config_file] if os.path.exists(config_file) else [],
        on_exit=Shutdown()
    )

    return LaunchDescription([
        vel_filter_node,
    ])
