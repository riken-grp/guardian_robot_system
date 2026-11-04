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

    # ---- separator_node ----
    separator_node_real = Node(
        package='audio_source_separator',
        executable='separator_node',
        name='separator_node',
        namespace=ROBOT_NAME,
        parameters=[separator_params_file],
        remappings=[
            ('in_tracked_persons', 'recog/ssl/tracked_persons'),
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

    return LaunchDescription([
        sim_arg,
        tracker_node_real,
        tracker_node_sim,
        localizer_node_real,
        localizer_node_sim,
        separator_node_real,
        separator_node_sim,
        speaker_id_node,
    ])
