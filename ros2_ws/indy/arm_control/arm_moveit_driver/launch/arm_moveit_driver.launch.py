import os
import xacro
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import (
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import (
    Node,
    PushRosNamespace,
    SetRemap,
)
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launch_utils import (
    DeclareBooleanLaunchArg,
)

def launch_node(context: LaunchContext):
    prefix_name = LaunchConfiguration("prefix_name")
    prefix_name_str = context.perform_substitution(prefix_name)

    group_name = LaunchConfiguration("group_name")
    group_name_str = context.perform_substitution(group_name)
    
    package_name = LaunchConfiguration("package_name")
    package_name_str = context.perform_substitution(package_name)

    moveit_config = MoveItConfigsBuilder("guardian", package_name=package_name_str).to_moveit_configs()
    """
     Launches a self contained demo
  
     launch_package_path is optional to use different launch and config packages
  
     Includes
      * static_virtual_joint_tfs
      * robot_state_publisher
      * move_group
      * moveit_rviz
      * warehouse_db (optional)
      * ros2_control_node + controller spawners
    """
    launch_package_path = None
    if launch_package_path == None:
        launch_package_path = moveit_config.package_path

    return [
        SetRemap(src="joint_states", dst="joints"),
        SetRemap(src="/tf", dst="/" + prefix_name_str + "/tf"),
        SetRemap(src="/tf_static", dst="/" + prefix_name_str + "/tf_static"),
        PushRosNamespace(prefix_name_str),
        DeclareBooleanLaunchArg(
            "debug",
            default_value=False,
            description="By default, we are not in debug mode",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                str(launch_package_path / "launch/static_virtual_joint_tfs.launch.py")
            ),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                str(launch_package_path / "launch/rsp.launch.py")
            ),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                str(launch_package_path / "launch/move_group.launch.py")
            ),
        ),
        # Node(
        #     package="controller_manager",
        #     executable="ros2_control_node",
        #     parameters=[
        #         moveit_config.robot_description,
        #         str(moveit_config.package_path / "config/ros2_controllers.yaml"),
        #     ],
        # ),
        # IncludeLaunchDescription(
        #     PythonLaunchDescriptionSource(
        #         str(launch_package_path / "launch/spawn_controllers.launch.py")
        #     ),
        # ),
    ]
    

def generate_launch_description():
    # robot_name = os.getenv("ROBOT_NAME")
    # if robot_name is None:
    #     print ("error: failed to get robot name")
    #     return

    return LaunchDescription(
        [
            GroupAction(
                [
                    # PushRosNamespace(robot_name),
                    OpaqueFunction(function=launch_node)
                ]
            )
        ]
    )