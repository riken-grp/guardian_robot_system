from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, GroupAction, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import PushRosNamespace

import os


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    share_dir = get_package_share_directory('ydlidar_ros2_driver')
    parameter_file = LaunchConfiguration('params_file')
    node_name = 'ydlidar_ros2_driver_node'

    params_declare = DeclareLaunchArgument('params_file',
                                           default_value=os.path.join(
                                            #    share_dir, 'config', 'ydlidar.yaml'),
                                               share_dir, 'config', 'ydlidar_tmini.yaml'),
                                           description='FPath to the ROS2 parameters file to use.')

    driver_node = Node(package='ydlidar_ros2_driver',
                                executable='ydlidar_ros2_driver_node',
                                name='ydlidar_ros2_driver_node',
                                # output='screen',
                                emulate_tty=True,
                                parameters=[parameter_file],
                                on_exit=Shutdown()
                                )
    tf2_node = Node(package='tf2_ros',
                    executable='static_transform_publisher',
                    name='static_tf_pub_laser',
                    arguments=['0', '0', '0.02','0', '0', '0', '1','map',robot_name + '_laser_frame'],
                    on_exit=Shutdown()
                    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace(robot_name),
            params_declare,
            driver_node,
        ]),
        tf2_node,
    ])
