import os

import launch_ros
import xacro
from ament_index_python.packages import get_package_share_directory

import launch
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    pkg_share = os.path.join(get_package_share_directory('robots'))
    default_xacro_path = os.path.join(pkg_share, 'urdf', 'indy.xacro')
    default_model_path = os.path.join(pkg_share, 'urdf', 'indy.urdf')

    doc = xacro.process_file(default_xacro_path, mappings={"robot_name" : robot_name})
    robot_desc = doc.toprettyxml(indent="    ")

    with open(default_model_path, "w") as f:
        f.write(robot_desc)

    robot_state_publisher_node = launch_ros.actions.Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        arguments=[default_model_path],
        on_exit=Shutdown()
    )
    joint_state_publisher_node = launch_ros.actions.Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        on_exit=Shutdown()
    )

    return launch.LaunchDescription([
        GroupAction([
            PushRosNamespace(robot_name),
            launch.actions.DeclareLaunchArgument(name='model', default_value=default_model_path,
                                                description='Absolute path to robot urdf file'),
            joint_state_publisher_node,
            robot_state_publisher_node,
        ])
    ])
