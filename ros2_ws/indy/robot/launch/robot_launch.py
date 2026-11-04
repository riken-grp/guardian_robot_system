import os
from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    return LaunchDescription([
        GroupAction([
            Node(
                package='rover',
                executable='mqtt2ros',
                on_exit = Shutdown()
            ),
            Node(
                package='rover',
                executable='twist2alimove',
                on_exit = Shutdown()
            ),
            Node(
                package='rover',
                executable='aliAction',
                on_exit = Shutdown()
            ),
            Node(
                package='rover',
                executable='recordvisitedlocation',
                on_exit = Shutdown()
            ),
            Node(
                package='rover',
                executable='watchindy',
                on_exit = Shutdown()
            ),
            Node(
                package='rover',
                executable='rover_state',
                on_exit = Shutdown()
            )
        ])
    ])
