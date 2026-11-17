import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

ROBOT_NAME = os.getenv("ROBOT_NAME", "")

_AUDIO_TOPIC_REAL = 'audio/multichannel'
_AUDIO_TOPIC_SIM = 'audio/multichannel_sim'


def generate_launch_description():
    config_dir = os.path.join(
        get_package_share_directory('ssl_bringup'), 'config'
    )

    tracker_params_file = os.path.join(config_dir, 'tracker_params.yaml')
    localizer_params_file = os.path.join(config_dir, 'localizer_params.yaml')
    separator_params_file = os.path.join(config_dir, 'separator_params.yaml')
    speaker_id_params_file = os.path.join(config_dir, 'speaker_id_params.yaml')
    camera_person_params_file = os.path.join(config_dir, 'camera_person_adapter_params.yaml')
    speaker_face_params_file = os.path.join(config_dir, 'speaker_face_params.yaml')

    sim_arg = DeclareLaunchArgument(
        'sim', default_value='false',
        description='If true, use simulated scan/audio topics (*_sim)',
    )

    # ---- tracker_node ----
    tracker_node_real = Node(
        package='lidar_person_tracker',
        executable='tracker_node',
        name='tracker_node',
        namespace=ROBOT_NAME,
        parameters=[tracker_params_file],
        remappings=[
            ('in_scan', 'scan'),
            ('out_tracked_persons', 'recog/ssl/tracked_persons'),
            ('out_viz_markers', 'recog/ssl/viz/tracker_markers'),
            ('out_viz_clusters', 'recog/ssl/viz/tracker_clusters'),
        ],
        output='screen',
        condition=UnlessCondition(LaunchConfiguration('sim')),
    )

    tracker_node_sim = Node(
        package='lidar_person_tracker',
        executable='tracker_node',
        name='tracker_node',
        namespace=ROBOT_NAME,
        parameters=[tracker_params_file],
        remappings=[
            ('in_scan', 'scan_sim'),
            ('out_tracked_persons', 'recog/ssl/tracked_persons'),
            ('out_viz_markers', 'recog/ssl/viz/tracker_markers'),
            ('out_viz_clusters', 'recog/ssl/viz/tracker_clusters'),
        ],
        output='screen',
        condition=IfCondition(LaunchConfiguration('sim')),
    )

    # ---- localizer_node ----
    localizer_node_real = Node(
        package='sound_source_localizer',
        executable='localizer_node',
        name='localizer_node',
        namespace=ROBOT_NAME,
        parameters=[localizer_params_file],
        remappings=[
            ('out_doa_estimates', 'recog/ssl/doa_estimates'),
            ('out_viz_doa_markers', 'recog/ssl/viz/doa_markers'),
        ],
        output='screen',
        condition=UnlessCondition(LaunchConfiguration('sim')),
    )

    localizer_node_sim = Node(
        package='sound_source_localizer',
        executable='localizer_node',
        name='localizer_node',
        namespace=ROBOT_NAME,
        parameters=[localizer_params_file],
        remappings=[
            ('audio/multichannel', _AUDIO_TOPIC_SIM),
            ('out_doa_estimates', 'recog/ssl/doa_estimates'),
            ('out_viz_doa_markers', 'recog/ssl/viz/doa_markers'),
        ],
        output='screen',
        condition=IfCondition(LaunchConfiguration('sim')),
    )

    # ---- camera_person_adapter_node (real only) ----
    # Camera persons (recog/person/pose/associated) converted to
    # TrackedPersonArray, merged with LiDAR tracks outside the camera FOV.
    # The LiDAR tracker loses persons closer than about 1.8 m and keeps
    # static objects; the camera keeps the same ID from 0.55 to 2.1 m.
    camera_person_adapter_node = Node(
        package='audio_source_separator',
        executable='camera_person_adapter_node',
        name='camera_person_adapter_node',
        namespace=ROBOT_NAME,
        parameters=[camera_person_params_file],
        remappings=[
            ('in_persons', 'recog/person/pose/associated'),
            ('in_lidar_persons', 'recog/ssl/tracked_persons'),
            ('out_tracked_persons', 'recog/ssl/tracked_persons_fused'),
        ],
        output='screen',
        condition=UnlessCondition(LaunchConfiguration('sim')),
    )

    # ---- separator_node ----
    separator_node_real = Node(
        package='audio_source_separator',
        executable='separator_node',
        name='separator_node',
        namespace=ROBOT_NAME,
        parameters=[separator_params_file],
        remappings=[
            # camera + LiDAR (camera_person_adapter_node); LiDAR only: recog/ssl/tracked_persons
            ('in_tracked_persons', 'recog/ssl/tracked_persons_fused'),
            ('in_doa_estimates', 'recog/ssl/doa_estimates'),
            ('out_speech_segments', 'recog/ssl/speech_segments'),
        ],
        output='screen',
        condition=UnlessCondition(LaunchConfiguration('sim')),
    )

    separator_node_sim = Node(
        package='audio_source_separator',
        executable='separator_node',
        name='separator_node',
        namespace=ROBOT_NAME,
        parameters=[separator_params_file],
        remappings=[
            ('audio/multichannel', _AUDIO_TOPIC_SIM),
            ('in_tracked_persons', 'recog/ssl/tracked_persons'),
            ('in_doa_estimates', 'recog/ssl/doa_estimates'),
            ('out_speech_segments', 'recog/ssl/speech_segments'),
        ],
        output='screen',
        condition=IfCondition(LaunchConfiguration('sim')),
    )

    # ---- speaker_id_node (same for real/sim) ----
    speaker_id_node = Node(
        package='audio_source_separator',
        executable='speaker_id_node',
        name='speaker_id_node',
        namespace=ROBOT_NAME,
        parameters=[speaker_id_params_file],
        remappings=[
            ('in_persons', 'recog/persons'),
            ('in_speech_segments', 'recog/ssl/speech_segments'),
            ('out_speech_segments', 'recog/ssl/identified_speech_segments'),
        ],
        output='screen',
    )

    # ---- speaker_face_node (real only) ----
    # Speech segments with the speaker's face image (camera instance_id ==
    # person_id), cropped from the robot camera image.
    speaker_face_node = Node(
        package='audio_source_separator',
        executable='speaker_face_node',
        name='speaker_face_node',
        namespace=ROBOT_NAME,
        parameters=[speaker_face_params_file],
        remappings=[
            ('in_speech_segments', 'recog/ssl/identified_speech_segments'),
            ('in_faces', 'recog/person/face/associated'),
            ('in_image', f'{ROBOT_NAME}_camera/color/image_raw/compressed'),
            ('out_speaker_faces', 'recog/ssl/speaker_face_segments'),
        ],
        output='screen',
        condition=UnlessCondition(LaunchConfiguration('sim')),
    )

    return LaunchDescription([
        sim_arg,
        tracker_node_real,
        tracker_node_sim,
        localizer_node_real,
        localizer_node_sim,
        camera_person_adapter_node,
        separator_node_real,
        separator_node_sim,
        speaker_id_node,
        speaker_face_node,
    ])
