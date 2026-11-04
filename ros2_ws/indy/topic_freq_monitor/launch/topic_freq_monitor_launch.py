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

    package_path = get_package_share_directory('topic_freq_monitor')
    topic_freq_monitor_config = os.path.join(
        package_path,
        'topic_freq_monitor.yaml'
    )

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        PushRosNamespace(robot_name),
        Node(
            package='topic_freq_monitor',
            executable='topic_freq_monitor',
            parameters=[topic_freq_monitor_config,
                        {'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
            on_exit=Shutdown()
        ),
    ])