from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    package_path = get_package_share_directory('human_tracker')
    human_tracker_config = os.path.join(
        package_path,
        'human_tracker_two_lidar.yaml'
    )

    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')

    human_tracker_integration_config = os.path.join(
        package_path,
        'human_tracker_integration.yaml'
    )

    facepose_publisher_config = os.path.join(
        package_path,
        'facepose_publisher.yaml'
    )

    ros_audio_tracker_config = os.path.join(
        package_path,
        'ros_audio_tracker.yaml'
    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace(robot_name),
            Node(
                package='human_tracker',
                executable='human_tracker_node',
                name="right_human_tracker_node",
                parameters=[human_tracker_config, 
                            {"multi_lidar": True, 'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
            Node(
                package='human_tracker',
                executable='human_tracker_node',
                name="left_human_tracker_node",
                parameters=[human_tracker_config, 
                            {"multi_lidar": True, 'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
            Node(
                package='human_tracker',
                executable='human_tracker_integration_node',
                parameters=[human_tracker_integration_config, 
                            {'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
            Node(
                package='human_tracker',
                executable='facepose_publisher_node',
                parameters=[facepose_publisher_config, 
                            {'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
            Node(
                package='human_tracker',
                executable='ros_audio_tracker_node',
                parameters=[ros_audio_tracker_config, 
                            {'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
        ])
    ])