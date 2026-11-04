import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction, Shutdown
from launch_ros.actions import Node

def generate_launch_description():
    package_name = "arm_motor_control"
    package_path = get_package_share_directory(package_name)
    print(package_path)
    
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        robot_name = ""
        
    config = os.path.join(
        package_path,
        'config',
        'arm_motor_control.yaml'
    )

    return LaunchDescription(
        [
            GroupAction(
                [
                    Node(
                        package=package_name,
                        executable="arm_motor_control",
                        namespace=robot_name + "/right_arm",
                        parameters=[
                            # node_params_right,
                            config,
                            ],
                        # output="screen",
                        on_exit = Shutdown()
                    ),
                    Node(
                        package=package_name,
                        executable="arm_motor_control",
                        namespace=robot_name + "/left_arm",
                        parameters=[
                            # node_params_left,
                            config,
                            ],
                        # output="screen",
                        on_exit = Shutdown()
                    )
                ]
            )
        ]
    )
