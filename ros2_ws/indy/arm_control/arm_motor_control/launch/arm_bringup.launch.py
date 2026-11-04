from launch import LaunchDescription
from launch_ros.actions import PushRosNamespace
from launch.actions import IncludeLaunchDescription, GroupAction
from launch.launch_description_sources import PythonLaunchDescriptionSource

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    arm_motor_control_share_dir = get_package_share_directory("arm_motor_control")
    arm_moveit_driver_share_dir = get_package_share_directory("arm_moveit_driver")

    return LaunchDescription([
        GroupAction([
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [arm_motor_control_share_dir + "/launch/arm_motor_control.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [arm_moveit_driver_share_dir + "/launch/bringup_arm_moveit_driver.launch.py"]
                )
            ),
        ])
    ])
