import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    IncludeLaunchDescription,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    package_name = "arm_moveit_driver"
    ld = LaunchDescription()
    
    arm_moveit_driver_dir = os.path.join(
        get_package_share_directory(package_name),
        "launch",
    )

    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    # right arm
    ld.add_action(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([arm_moveit_driver_dir, '/arm_moveit_driver.launch.py']),
            launch_arguments={
                "package_name": package_name,
                "group_name": "arm",
                "prefix_name": robot_name + "/right_arm",
            }.items(),
        )
    )
    
    ld.add_action(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([arm_moveit_driver_dir, '/arm_moveit_driver_node.launch.py']),
            launch_arguments={
                "package_name": package_name,
                "group_name": "arm",
                "prefix_name": robot_name + "/right_arm",
                "xacro_file_path": "config/guardian.urdf.xacro",
                "srdf_file_path": "config/guardian.srdf"
            }.items(),
        )
    )

    # left arm
    ld.add_action(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([arm_moveit_driver_dir, '/arm_moveit_driver.launch.py']),
            launch_arguments={
                "package_name": package_name,
                "group_name": "arm",
                "prefix_name": robot_name + "/left_arm",
            }.items(),
        )
    )
    
    ld.add_action(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([arm_moveit_driver_dir, '/arm_moveit_driver_node.launch.py']),
            launch_arguments={
                "package_name": package_name,
                "group_name": "arm",
                "prefix_name": robot_name + "/left_arm",
                "xacro_file_path": "config/guardian.urdf.xacro",
                "srdf_file_path": "config/guardian.srdf"
            }.items(),
        )
    )        

    return ld
