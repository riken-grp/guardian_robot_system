from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

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

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        Node(
            package='rover_tools',
            executable='battery_log',
            namespace=robot_name,
            parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
            on_exit = Shutdown()
        ),
    ])