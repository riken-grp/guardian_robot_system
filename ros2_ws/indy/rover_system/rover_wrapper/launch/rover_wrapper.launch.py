from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import Shutdown

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    package_path = get_package_share_directory('rover_wrapper')
    rover_wrapper_config = os.path.join(
        package_path,
        'default_param.yaml'
    )

    return LaunchDescription([
        Node(
            package='rover_wrapper',
            executable='rover_wrapper',
            namespace=robot_name,
            parameters=[rover_wrapper_config],
            on_exit=Shutdown()
        ),
    ])