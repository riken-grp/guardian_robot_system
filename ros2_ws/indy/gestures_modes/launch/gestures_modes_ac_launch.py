from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return
    
    mongo_uri = LaunchConfiguration('mongo_uri')
    declare_mongo_uri = DeclareLaunchArgument('mongo_uri', default_value='')
    mongo_port = LaunchConfiguration('mongo_port')
    declare_mongo_port = DeclareLaunchArgument('mongo_port', default_value='1')
    
    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        GroupAction([
            PushRosNamespace(robot_name),
            Node(
                package='robot',
                executable='rosGesture_modes',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='default_mode_action_server',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='tracking_mode_action_server',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='listen_mode_action_server',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='modes_description_w_action_server',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='default_mode_action_client',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='tracking_mode_action_client',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            ),
            Node(
                package='gestures_modes',
                executable='listen_mode_action_client',
                respawn=True,
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit = Shutdown()
            )
        ])
    ])
