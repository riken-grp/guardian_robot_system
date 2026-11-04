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
    tf2_parameter_file = LaunchConfiguration('tf2_params_file')

    params_declare = DeclareLaunchArgument('params_file',
                                           default_value=os.path.join(
                                           share_dir, 'config', 'multi_ydlidar.yaml'),
                                           description='FPath to the ROS2 parameters file to use.')

    tf2_params_declare = DeclareLaunchArgument('tf2_params_file',
                                           default_value=os.path.join(
                                           share_dir, 'config', 'transform_tf_broadcaster.yaml'),
                                           description='FPath to the ROS2 parameters file to use.')

    driver_node = Node(package='ydlidar_ros2_driver',
                                executable='ydlidar_ros2_driver_node',
                                name='ydlidar_ros2_driver_node',
                                # output='screen',
                                emulate_tty=True,
                                parameters=[parameter_file],
                                namespace='lidar1',
                                on_exit=Shutdown()
                                )
    driver_node2 = Node(package='ydlidar_ros2_driver',
                                executable='ydlidar_ros2_driver_node',
                                name='ydlidar_ros2_driver_node',
                                # output='screen',
                                emulate_tty=True,
                                parameters=[parameter_file],
                                namespace='lidar2',
                                on_exit=Shutdown()
                                )
    # transform_tf2_node = Node(package='ydlidar_ros2_driver',
    #                           executable='transform_tf_broadcaster',
    #                           name='transform_tf_broadcaster',
    #                           parameters=[tf2_parameter_file],
    #                           output='screen',
    #                           on_exit=Shutdown()
    #                           )
    tf2_node = Node(package='tf2_ros',
                    executable='static_transform_publisher',
                    name='static_tf_pub_lidar1',
                    arguments=['0', '-0.067', '0.45','0', '0', '0', '1', robot_name + '_body_link', robot_name + '_lidar_link'],
                    on_exit=Shutdown()
                    )
    tf2_node2 = Node(package='tf2_ros',
                    executable='static_transform_publisher',
                    name='static_tf_pub_lidar2',
                    arguments=['0', '0.067', '0.45','0', '0', '0', '1', robot_name + '_body_link', robot_name + '_lidar2_link'],
                    on_exit=Shutdown()
                    )
    # rqt_reconfigure_node = Node(package='rqt_reconfigure',
    #                             executable='rqt_reconfigure',
    #                             output='screen',
    #                             on_exit=Shutdown()
    #                             )

    return LaunchDescription([
        params_declare,
        tf2_params_declare,
        tf2_node,
        tf2_node2,
        GroupAction([
            PushRosNamespace(robot_name),
            driver_node,
            driver_node2,
        ]),
        # rqt_reconfigure_node,
    ])
