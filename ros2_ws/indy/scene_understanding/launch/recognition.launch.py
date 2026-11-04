import os

import torch
from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            SetEnvironmentVariable, Shutdown)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

ROBOT_NAME = os.getenv("ROBOT_NAME")


def generate_launch_description():
    scene_understanding_path = get_package_share_directory("scene_understanding")
    config = os.path.join(
        scene_understanding_path, "config", "scene_understanding.yaml"
    )

    mongo_uri = LaunchConfiguration("mongo_uri")
    declare_mongo_uri = DeclareLaunchArgument("mongo_uri", default_value="")
    mongo_port = LaunchConfiguration("mongo_port")
    declare_mongo_port = DeclareLaunchArgument("mongo_port", default_value="1")

    commands = []
    commands.extend(
        [
            # カラー画像: compressed → compressed (topic_tools relay)
            Node(
                package="topic_tools",
                executable="relay",
                name="color_republish",
                namespace=ROBOT_NAME,
                arguments=[
                    ROBOT_NAME + "_camera/color/image_raw/compressed",
                    "local_recog/color/image_raw/compressed",
                ],
                on_exit=Shutdown(),
            ),
            # 深度画像: compressedDepth → compressedDepth (topic_tools relay)
            Node(
                package="topic_tools",
                executable="relay",
                name="depth_republish",
                namespace=ROBOT_NAME,
                arguments=[
                    ROBOT_NAME
                    + "_camera/aligned_depth_to_color/image_raw/compressedDepth",
                    "local_recog/depth/image_raw/compressedDepth",
                ],
                on_exit=Shutdown(),
            ),
            SetEnvironmentVariable(name="CUDA_VISIBLE_DEVICES", value="1"),
            Node(
                package="scene_understanding",
                executable="detection_and_tracking_node",
                name="detection_and_tracking_node",
                namespace=ROBOT_NAME,
                parameters=[
                    config,
                    {
                        "mongo_uri": mongo_uri,
                        "mongo_port": mongo_port,
                    },
                ],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("in_depth_topic", "local_recog/depth/image_raw/compressedDepth"),
                    ("cinfo_topic", ROBOT_NAME + "_camera/color/camera_info"),
                    ("out_topic", "recog/object/tracked"),
                    ("vis_topic", "local_recog/object/tracked/visualized/compressed"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="scene_understanding",
                executable="body_pose_estimation_node",
                name="body_pose_estimation_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("in_depth_topic", "local_recog/depth/image_raw/compressedDepth"),
                    ("cinfo_topic", f"{ROBOT_NAME}_camera/color/camera_info"),
                    ("out_topic", "recog/person/pose"),
                    ("marker_topic", "recog/person/pose/markers"),
                    ("vis_topic", "local_recog/person/pose/visualized/compressed"),
                ],
                on_exit=Shutdown(),
            ),
        ]
    )
    if torch.cuda.device_count() > 1:
        commands.append(SetEnvironmentVariable(name="CUDA_VISIBLE_DEVICES", value="2"))
    commands.extend(
        [
            Node(
                package="scene_understanding",
                executable="head_pose_estimation_node",
                name="head_pose_estimation_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("in_depth_topic", "local_recog/depth/image_raw/compressedDepth"),
                    ("cinfo_topic", f"{ROBOT_NAME}_camera/color/camera_info"),
                    ("out_topic", "recog/person/face"),
                    ("vis_topic", "local_recog/person/face/visualized/compressed"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="scene_understanding",
                executable="attribute_recognition_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("in_person_topic", "recog/person/pose/associated"),
                    ("out_topic", "recog/person/attributes"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="scene_understanding",
                executable="association_node",
                name="association_node",
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                namespace=ROBOT_NAME,
                remappings=[
                    ("in_track_topic", "recog/object/tracked"),
                    ("in_person_topic", "recog/person/pose"),
                    ("in_face_topic", "recog/person/face"),
                    ("out_person_topic", "recog/person/pose/associated"),
                    ("out_face_topic", "recog/person/face/associated"),
                ],
                on_exit=Shutdown(),
            ),
            # Node(
            #     package='scene_understanding',
            #     executable='scene_text_reader',
            #     namespace=ROBOT_NAME,
            #     parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
            #     remappings=[("in_color_topic", "local_recog/color/image_raw"),
            #                 ("in_depth_topic", "local_recog/depth/image_raw"),
            #                 ("cinfo_topic", ROBOT_NAME + "_camera/color/camera_info"),
            #                 ("out_topic", "recog/person/text"),
            #                 ("vis_topic", "local_recog/text/visualized")],
            #     on_exit=Shutdown()
            # ),
            Node(
                package="scene_understanding",
                executable="aruco_reader_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("cinfo_topic", ROBOT_NAME + "_camera/color/camera_info"),
                    ("vis_topic", "local_recog/aruco/visualized/compressed"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="scene_understanding",
                executable="qr_code_reader_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_color_topic", "local_recog/color/image_raw/compressed"),
                    ("out_topic", "recog/qr_code"),
                    ("vis_topic", "local_recog/qr_code/visualized/compressed"),
                ],
                on_exit=Shutdown(),
            ),
            Node(
                package="robot_looking",
                executable="looking_target_recognition_node",
                name="looking_target_recognition_node",
                namespace=ROBOT_NAME,
                parameters=[config, {"mongo_uri": mongo_uri, "mongo_port": mongo_port}],
                remappings=[
                    ("in_humantracker_topic", "human_tracker/audio_info"),
                    ("out_topic", "recog/robot_looking_target"),
                ],
                on_exit=Shutdown(),
            ),
        ]
    )

    return LaunchDescription(commands)
