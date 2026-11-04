from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    # 1. get robot name from environmental variable
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return
    # 2. set mongo_uri and mongo_port to node
    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        GroupAction([
            # 3. set namespace to node
            PushRosNamespace(robot_name),   
            Node(
                package='robot',
                executable='rosCommand',
                respawn=True,
                # 4. set yaml config parameter to the node
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            )#,
        ])
    ])

# https://engineeeer.com/ros2-launch-python/
