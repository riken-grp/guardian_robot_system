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

    package_path = get_package_share_directory('keigan_motor')
    keigan_motor_config = os.path.join(
        package_path,
        robot_name + '_param.yaml'
    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace(robot_name),
            Node(
                package='keigan_motor',
                executable='keigan_motor_node',
                parameters=[keigan_motor_config],
                on_exit = Shutdown()
            ),
        ])
    ])