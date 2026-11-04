import os

from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory

from pyindy.param_manager import ParamManager

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
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
                package='sensor_tf_publisher',
                executable='sensor_tf_publisher_node',
                parameters=[{'mongo_uri': mongo_uri, 'mongo_port': mongo_port}],
                on_exit=Shutdown()
            ),
        ])
    ])