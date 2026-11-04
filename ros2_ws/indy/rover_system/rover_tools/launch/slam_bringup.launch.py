from launch import LaunchDescription
from launch_ros.actions import Node, PushRosNamespace
from launch.actions import IncludeLaunchDescription, GroupAction, Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource

from ament_index_python.packages import get_package_share_directory

import os

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    amr_description_share_dir = get_package_share_directory("amr_description")
    amr_ros_driver_share_dir = get_package_share_directory("amr_ros_driver")
    rover_wrapper_share_dir = get_package_share_directory("rover_wrapper")
    rover_tools_share_dir = get_package_share_directory("rover_tools")

    return LaunchDescription([
        GroupAction([
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [amr_description_share_dir + "/launch/amr_description.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [amr_ros_driver_share_dir + "/launch/amr_ros_driver.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_wrapper_share_dir + "/rover_wrapper.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_tools_share_dir + "/lidar_launch.py"]
                )
            ),
            PushRosNamespace(robot_name),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                parameters=[{"scan_topic": "rover/scan"},
                            {"base_frame": robot_name+"_base_footprint"},
                            {"odom_frame": robot_name+"_odom"},
                            # QoS overrides for WiFi stability
                            {"qos_overrides./scan.subscription.reliability": "best_effort"},
                            {"qos_overrides./scan.subscription.durability": "volatile"},
                            {"qos_overrides./scan.subscription.history": "keep_last"},
                            {"qos_overrides./scan.subscription.depth": 1}],
                on_exit=Shutdown()
            ),
        ])
    ])