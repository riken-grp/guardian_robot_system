import os
import xacro
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import GroupAction, OpaqueFunction, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap


def load_file(package_name, file_path):
    package_path = get_package_share_directory(package_name)
    absolute_file_path = os.path.join(package_path, file_path)

    try:
        with open(absolute_file_path, "r") as file:
            return file.read()
    except EnvironmentError:  # parent of IOError, OSError *and* WindowsError where available
        return None

def load_yaml_file(package_name, file_path):
    package_path = get_package_share_directory(package_name)
    absolute_file_path = os.path.join(package_path, file_path)
    try:
        with open(absolute_file_path, "r") as file:
            return yaml.safe_load(file)
    except EnvironmentError:  # parent of IOError, OSError *and* WindowsError where available
        return None    

def launch_node(context: LaunchContext):
    prefix_name = LaunchConfiguration("prefix_name")
    prefix_name_str = context.perform_substitution(prefix_name)

    group_name = LaunchConfiguration("group_name")
    group_name_str = context.perform_substitution(group_name)
    
    package_name = LaunchConfiguration("package_name")
    package_name_str = context.perform_substitution(package_name)

    xacro_file_path = LaunchConfiguration("xacro_file_path")
    xacro_file = context.perform_substitution(xacro_file_path)
    
    srdf_file_path = LaunchConfiguration("srdf_file_path")
    srdf_file = context.perform_substitution(srdf_file_path)    
    
    node_params = {
        "prefix_name": prefix_name_str,
        "group_name": group_name_str,
    }

    # planning_context
    robot_description_config = xacro.process_file(
        os.path.join(
            get_package_share_directory(package_name_str),
            xacro_file,
        )
    )
    robot_description = {"robot_description": robot_description_config.toxml()}

    robot_description_semantic_config = load_file(
        package_name_str, srdf_file
    )
    robot_description_semantic = {
        "robot_description_semantic": robot_description_semantic_config
    }

    kinematics_yaml = load_yaml_file(
        package_name_str, "config/kinematics.yaml"
    )
    
    
    trajectory_execution = {
        "moveit_manage_controllers": True,
        "trajectory_execution.allowed_execution_duration_scaling": 1.2,
        "trajectory_execution.allowed_goal_duration_margin": 0.5,
        "trajectory_execution.allowed_start_tolerance": 0.01,
    }

    planning_scene_monitor_parameters = {
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
    }
    
    
    # joint_limits.yaml
    joint_limits_yaml = load_yaml_file(
        package_name_str, "config/joint_limits.yaml"
    )
    robot_description_planning = {"robot_description_planning": joint_limits_yaml}
    
    
    moveit_simple_controllers_yaml = load_yaml_file(
        package_name_str, "config/moveit_controllers.yaml"
    )
    moveit_controllers = {
        "moveit_simple_controller_manager": moveit_simple_controllers_yaml,
        "moveit_controller_manager": "moveit_simple_controller_manager/MoveItSimpleControllerManager",
    }

    return [
        SetRemap(src="joint_states", dst="joints"),
        SetRemap(src="/tf", dst="/" + prefix_name_str + "/tf"),
        SetRemap(src="/tf_static", dst="/" + prefix_name_str + "/tf_static"),
        Node(
            package=package_name_str,
            executable="arm_moveit_driver_node",
            namespace=prefix_name_str,
            parameters=[
                {"move_group_namespace": "/" + prefix_name_str, "group_name": group_name},
                moveit_controllers,
                planning_scene_monitor_parameters,
                robot_description,
                robot_description_semantic,
                kinematics_yaml,
                robot_description_planning,
                trajectory_execution,
                node_params,
                ],
            # output="screen",
            on_exit = Shutdown()
        )
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

