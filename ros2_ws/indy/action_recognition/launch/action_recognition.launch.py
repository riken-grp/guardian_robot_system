import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, SetEnvironmentVariable,
                            Shutdown)
from launch.substitutions import LaunchConfiguration

ROBOT_NAME = os.getenv("ROBOT_NAME")


def generate_launch_description():
    package_path = get_package_share_directory("action_recognition")
    config_path = os.path.join(package_path, "config", "action_recognition.yaml")

    mongo_uri = LaunchConfiguration("mongo_uri")
    declare_mongo_uri = DeclareLaunchArgument("mongo_uri", default_value="")
    mongo_port = LaunchConfiguration("mongo_port")
    declare_mongo_port = DeclareLaunchArgument("mongo_port", default_value="1")

    nodes = []
    # arm_state_node
    nodes.append(
        Node(
            package="action_recognition",
            executable="arm_state_node",
            name="arm_state_node",
            namespace=ROBOT_NAME,
            parameters=[
                config_path,
                {"mongo_uri": mongo_uri, "mongo_port": mongo_port},
            ],
            remappings=[
                ("in_person_topic", "recog/person/pose/associated"),
                ("out_topic", "recog/person/hand_state"),
            ],
            on_exit=Shutdown(),
        )
    )
    # hand_waving_node
    nodes.append(
        Node(
            package="action_recognition",
            executable="hand_waving_node",
            name="hand_waving_node",
            namespace=ROBOT_NAME,
            parameters=[
                config_path,
                {"mongo_uri": mongo_uri, "mongo_port": mongo_port},
            ],
            remappings=[
                ("in_topic", "local_recog/color/image_raw/compressed"),
                ("in_person_topic", "recog/person/pose/associated"),
                ("out_topic", "recog/person/hand_waving"),
                ("vis_topic", "local_recog/person/hand_waving/visualized/compressed"),
            ],
            on_exit=Shutdown(),
        )
    )
    # looking_at_simple_node
    nodes.append(
        Node(
            package="action_recognition",
            executable="looking_at_simple_node",
            name="looking_at_simple_node",
            namespace=ROBOT_NAME,
            parameters=[
                config_path,
                {"mongo_uri": mongo_uri, "mongo_port": mongo_port},
            ],
            remappings=[
                ("in_topic", "local_recog/color/image_raw/compressed"),
                ("in_person_topic", "recog/person/face/associated"),
                ("out_topic", "recog/person/looking_at"),
                ("vis_topic", "local_recog/person/looking_at/visualized/compressed"),
            ],
            on_exit=Shutdown(),
        )
    )
    # wheelchair_node
    nodes.append(
        Node(
            package="action_recognition",
            executable="wheelchair_node",
            name="wheelchair_node",
            namespace=ROBOT_NAME,
            parameters=[
                config_path,
                {"mongo_uri": mongo_uri, "mongo_port": mongo_port},
            ],
            remappings=[
                ("in_topic", "local_recog/color/image_raw/compressed"),
                ("in_person_topic", "recog/person/pose/associated"),
                ("out_topic", "recog/person/wheelchair"),
                ("vis_topic", "local_recog/person/wheelchair/visualized/compressed"),
            ],
            on_exit=Shutdown(),
        )
    )
    # noticed_node (whether each person has noticed the robot)
    nodes.append(
        Node(
            package="action_recognition",
            executable="noticed_node",
            name="noticed_node",
            namespace=ROBOT_NAME,
            parameters=[
                config_path,
                {"mongo_uri": mongo_uri, "mongo_port": mongo_port},
            ],
            remappings=[
                ("in_person_topic", "recog/person/pose/associated"),
                ("in_lookingat_topic", "recog/person/looking_at"),
                ("in_hand_waving_topic", "recog/person/hand_waving"),
                ("in_hand_topic", "recog/person/hand_state"),
                ("out_topic", "recog/person/noticed"),
            ],
            on_exit=Shutdown(),
        )
    )

    return LaunchDescription(
        [
            declare_mongo_uri,
            declare_mongo_port,
            SetEnvironmentVariable(name="CUDA_VISIBLE_DEVICES", value="1"),
            *nodes,
        ]
    )
