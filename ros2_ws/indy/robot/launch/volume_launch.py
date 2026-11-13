import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace


def generate_launch_description():
    # 1. get robot name from environmental variable
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return

    sink = LaunchConfiguration("sink")
    initial_volume = LaunchConfiguration("initial_volume")
    check_sound = LaunchConfiguration("check_sound")

    return LaunchDescription([
        DeclareLaunchArgument(
            "sink",
            default_value="alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo",
        ),
        # -1: keep the current volume on startup
        DeclareLaunchArgument("initial_volume", default_value="-1"),
        # wav played after a change ("" : no sound)
        DeclareLaunchArgument("check_sound", default_value=""),
        GroupAction([
            # 2. set namespace to node: /<ROBOT_NAME>/robot/set_volume
            PushRosNamespace(robot_name),
            Node(
                package="robot",
                executable="rosVolume",
                respawn=True,
                parameters=[{
                    "sink": sink,
                    "initial_volume": initial_volume,
                    "check_sound": check_sound,
                }],
            ),
        ]),
    ])
