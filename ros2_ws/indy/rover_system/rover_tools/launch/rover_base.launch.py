from launch import LaunchDescription
from launch_ros.actions import PushRosNamespace, Node
from launch.actions import IncludeLaunchDescription, GroupAction,Shutdown, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource

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

    amr_description_share_dir = get_package_share_directory("amr_description")
    amr_ros_driver_share_dir = get_package_share_directory("amr_ros_driver")
    rover_wrapper_share_dir = get_package_share_directory("rover_wrapper")
    rover_tools_share_dir = get_package_share_directory("rover_tools")
    auto_charge_share_dir = get_package_share_directory("auto_charge")

    return LaunchDescription([
        declare_mongo_uri,
        declare_mongo_port,
        GroupAction([
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [amr_description_share_dir + "/launch/amr_description.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [amr_ros_driver_share_dir + "/launch/amr_ros_driver.launch.py"]
                ),
                launch_arguments={'cmd_vel': 'rover/cmd_vel_filtered'}.items()
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [auto_charge_share_dir + "/auto_charge.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_wrapper_share_dir + "/rover_wrapper.launch.py"]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_tools_share_dir + "/battery_log_launch.py"]
                ),
                launch_arguments={'mongo_uri': mongo_uri, 'mongo_port': mongo_port}.items()
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [rover_tools_share_dir + "/laserscan_multi_merger_launch.py"]
                )
            ),
        ])
    ])
