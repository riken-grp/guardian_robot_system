from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace
from launch.actions import Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    package_path = get_package_share_directory('network_check')
    network_check_config = os.path.join(
        package_path,
        'default_param.yaml'
    )

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')
    network_interface = LaunchConfiguration('network_interface')
    declare_network_interface = DeclareLaunchArgument('network_interface', default_value='')

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        declare_network_interface,
        PushRosNamespace(robot_name),
        Node(
            package='network_check',
            executable='network_check',
            parameters=[network_check_config, 
                        {'mongo_uri': mongo_uri, 'mongo_port': mongo_port, 'network_interface': network_interface}],
            on_exit = Shutdown()
        ),
    ])