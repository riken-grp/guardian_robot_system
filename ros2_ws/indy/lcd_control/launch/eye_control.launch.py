import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node

def generate_launch_description():
    package_name = "lcd_control"
    package_path = get_package_share_directory(package_name)
    image_base_directory = package_path + "/image/"
    
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        robot_name = ""
    
    node_params = {
        "image_base_directory": image_base_directory
    }
    
    config = os.path.join(
        package_path,
        'config',
        'lcd_control.yaml'
    )

    return LaunchDescription(
        [
            GroupAction(
                [
                    Node(
                        package=package_name,
                        executable="lcd_control",
                        namespace=robot_name,
                        parameters=[
                            node_params,
                            config,
                            ],
                        # output="screen",
                        on_exit = Shutdown()
                    )
                ]
            )
        ]
    )
