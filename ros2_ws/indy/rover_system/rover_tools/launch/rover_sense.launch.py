import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

import launch
from launch.actions import GroupAction, DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    rover_launch_file_dir = get_package_share_directory('rover_tools')
    lidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_launch_file_dir + "/lidar_nav_launch.py"]),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_launch_file_dir + "/rs_camera_nav_launch.py"]),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    vel_filter_share_dir = get_package_share_directory("vel_filter")
    vel_filter_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([vel_filter_share_dir + "/vel_filter.launch.py"])
    )

    return launch.LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        lidar_launch,
        realsense_launch,
        vel_filter_launch,
    ])
