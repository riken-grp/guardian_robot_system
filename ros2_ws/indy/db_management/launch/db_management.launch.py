import os

from launch_ros.actions import Node

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration

ROBOT_NAME = os.getenv("ROBOT_NAME")


def generate_launch_description():
    mongo_uri = LaunchConfiguration("mongo_uri")
    declare_mongo_uri = DeclareLaunchArgument("mongo_uri", default_value="")
    mongo_port = LaunchConfiguration("mongo_port")
    declare_mongo_port = DeclareLaunchArgument("mongo_port", default_value="27017")

    commands = []
    commands.extend(
        [
            declare_mongo_uri,
            declare_mongo_port,
            Node(
                package="db_management",
                executable="register_db_recog_node",
                name="register_db_recog_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_track_topic", "recog/object/tracked"),
                    ("in_associated_person_topic", "recog/person/pose/associated"),
                    ("in_associated_face_topic", "recog/person/face/associated"),
                    ("in_associated_scenegraph_topic", "recog/scenegraph/associated"),
                    ("in_attributes_topic", "recog/person/attributes"),
                    ("in_hand_topic", "recog/person/hand_state"),
                    ("in_hand_waving_topic", "recog/person/hand_waving"),
                    ("in_lookingat_topic", "recog/person/looking_at"),
                    ("in_wheelchair_topic", "recog/person/wheelchair"),
                    ("in_noticed_topic", "recog/person/noticed"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="register_db_weather_node",
                name="register_db_weather_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="register_db_asr_node",
                name="register_db_asr_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_asr_dbg_topic", "recog/asr"),
                    ("in_asr_topic", "asr/meta_data"),
                    ("in_filtered_vap_topic", "asr/vap"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="register_db_environsensor_node",
                name="register_db_environsensor_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_environ_raw_topic", "recog/environ/raw_data"),
                    ("in_environ_labels_topic", "recog/environ/result"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="register_db_bumper_node",
                name="register_db_bumper_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_bumper_topic", "rover/bumper"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="register_db_qrcode_node",
                name="register_db_qrcode_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_qrcode_topic", "recog/qr_code"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="modify_priority_node",
                name="modify_priority_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="check_num_of_person_node",
                name="check_num_of_person_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="check_looking_at_node",
                name="check_looking_at_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="check_wheelchair_node",
                name="check_wheelchair_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="check_arm_state_node",
                name="check_arm_state_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="check_waving_hand_node",
                name="check_waving_hand_node",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
            Node(
                package="db_management",
                executable="map_to_mongodb",
                name="map_to_mongodb",
                namespace=ROBOT_NAME,
                parameters=[{"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                on_exit=Shutdown(),
            ),
        ]
    )

    return LaunchDescription(commands)
