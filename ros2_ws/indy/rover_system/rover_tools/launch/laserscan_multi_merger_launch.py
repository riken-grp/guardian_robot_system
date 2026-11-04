import os

from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node
from launch_ros.actions import PushRosNamespace

from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    return LaunchDescription([
        GroupAction([
            Node(
                package='ira_laser_tools',
                executable='laserscan_multi_merger',
                namespace=robot_name,
                parameters=[{"destination_frame":robot_name+"_base_link",
                             "cloud_destination_topic":"merged_cloud",
                             "scan_destination_topic":"rover/scan",
                             "laserscan_topics":"/"+robot_name+"/laser_f/scan " + \
                                                "/"+robot_name+"/laser_b/scan" ,
                             "angle_min":-3.14,
                             "angle_max":3.14,
                             "angle_increment":0.00437,
                             "scan_time":0.1,
                             "range_min":0.05,
                             "range_max":20.0
                             }],
                on_exit = Shutdown()
            ),
        ])
    ])