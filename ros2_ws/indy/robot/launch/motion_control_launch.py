from launch import LaunchDescription
from launch_ros.actions import PushRosNamespace, Node
from launch.actions import IncludeLaunchDescription, GroupAction,Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource

from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    robot_share_dir = get_package_share_directory("robot")
    gestures_share_dir = get_package_share_directory("gestures_modes")

    return LaunchDescription([
        GroupAction([
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [robot_share_dir + "/eye_launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [gestures_share_dir + "/gestures_modes_ac_launch.py"]
                )
            ),
        ])
    ])
