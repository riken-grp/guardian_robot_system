from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return
    return LaunchDescription([
        GroupAction([
            PushRosNamespace(robot_name),
            Node(
                package='joy',
                executable='joy_node',
                on_exit = Shutdown()
            ),
            Node(
                package='rover_tools',
                executable='joy2twist',
                on_exit = Shutdown()
            )
        ])
    ])
