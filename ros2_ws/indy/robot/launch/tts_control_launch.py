from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace
from launch.actions import Shutdown

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():

    # 1. get robot name from environmental variable
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    # 2. set yanl config file
    package_path = get_package_share_directory('common_data_package')
    common_config = os.path.join(
        package_path,
        'common_data.yaml'
    )

    return LaunchDescription([
        PushRosNamespace(robot_name),   # 3. set namespace to node
        Node(
            package='sample_package',
            executable='sample_node',
            parameters=[common_config],  # 4. set yaml config parameter to the node
            on_exit = Shutdown()
        ),
    ])