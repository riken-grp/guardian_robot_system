from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    package_path = get_package_share_directory('human_tracker')
    ros_audio_tracker_config = os.path.join(
        package_path,
        'ros_audio_tracker.yaml'
    )

    tf_publisher_launch_file_dir = get_package_share_directory('sensor_tf_publisher')
    tf_publisher_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([tf_publisher_launch_file_dir, '/sensor_tf_publisher_launch.py']),
        launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
    )

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        GroupAction([
            tf_publisher_launch,
            PushRosNamespace(robot_name),
            Node(
                package='human_tracker',
                executable='ros_audio_tracker_node',
                name='ros_audio_tracker_outer_camera_node',
                parameters=[ros_audio_tracker_config,
                            {'robot_link': robot_name + '_base_link'}],
                on_exit=Shutdown()
            ),
        ])
    ])
