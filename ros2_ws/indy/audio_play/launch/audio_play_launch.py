import os

from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node, PushRosNamespace


def generate_launch_description():
    # 1. get robot name from environmental variable
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return

    return LaunchDescription([
        GroupAction([
            # 2. set namespace to node (topic: /<robot>/robot/play_audio)
            PushRosNamespace(robot_name),
            Node(
                package="audio_play",
                executable="rosAudioPlay",
                name="audio_play",
                respawn=True,
                parameters=[{"max_duration": 30.0, "max_queue": 3}],
                on_exit=Shutdown(),
            ),
        ])
    ])
