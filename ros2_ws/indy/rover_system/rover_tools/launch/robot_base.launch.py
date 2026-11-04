import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

import launch
from launch.actions import GroupAction, DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    eye_launch_file_dir = get_package_share_directory('lcd_control')
    eye_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([eye_launch_file_dir, '/launch/eye_control.launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    arm_launch_file_dir = get_package_share_directory('arm_motor_control')
    arm_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([arm_launch_file_dir, '/launch/arm_bringup.launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    motor_launch_file_dir = get_package_share_directory('motor_control')
    motor_launch = launch.actions.IncludeLaunchDescription(
        PythonLaunchDescriptionSource([motor_launch_file_dir, '/launch/motor_control.launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        namespace=robot_name,
        parameters=[{'source_list':['motor_control/joints']}],
        on_exit=Shutdown()
    )

    return launch.LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        eye_launch,
        arm_launch,
        motor_launch,
        joint_state_publisher_node
    ])
