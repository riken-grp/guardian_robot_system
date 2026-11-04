import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

import launch
from launch.actions import GroupAction, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    lidar_launch_file_dir = get_package_share_directory('urg_node2')
    lidar_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([lidar_launch_file_dir, '/launch/urg_node2_2lidar.launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    laser_tools_launch_file_dir = get_package_share_directory('ira_laser_tools')
    laser_tools_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([laser_tools_launch_file_dir, '/launch/laserscan_multi_merger_launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    tf2_node = Node(package='tf2_ros',
                    executable='static_transform_publisher',
                    name='static_tf_pub_lidar1',
                    arguments=['0.2', '0.0', '0.0','0', '0', '0', '1', robot_name + '_body_link', robot_name + '_lidar_link'],
                    on_exit=Shutdown()
                    )
    tf2_node2 = Node(package='tf2_ros',
                    executable='static_transform_publisher',
                    name='static_tf_pub_lidar2',
                    arguments=['-0.2', '0.0', '0.0','0', '0', '1', '0', robot_name + '_body_link', robot_name + '_lidar2_link'],
                    on_exit=Shutdown()
                    )

    return launch.LaunchDescription([
        lidar_launch,
        laser_tools_launch,
        tf2_node,
        tf2_node2
    ])
