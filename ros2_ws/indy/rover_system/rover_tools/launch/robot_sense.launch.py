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

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    rover_launch_file_dir = get_package_share_directory('rover_tools')
    lidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_launch_file_dir + "/lidar_ht_launch.py"]),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([rover_launch_file_dir + "/rs_camera_recog_launch.py"]),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        lidar_launch,
        realsense_launch
    ])
