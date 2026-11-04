import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

ROBOT_NAME = os.getenv("ROBOT_NAME", "")


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('speaker_x', default_value='1.0',
                              description='Speaker X position (forward, metres)'),
        DeclareLaunchArgument('speaker_y', default_value='-0.5',
                              description='Speaker Y position (left-positive, metres)'),
        DeclareLaunchArgument('text', default_value='こんにちは',
                              description='Utterance text for TTS'),
        DeclareLaunchArgument('speech_duration', default_value='1.5',
                              description='Duration of synthetic speech if TTS unavailable'),

        Node(
            package='ssl_bringup',
            executable='sim_speaker_node.py',
            name='sim_speaker_node',
            namespace=ROBOT_NAME,
            parameters=[{
                'speaker_x': LaunchConfiguration('speaker_x'),
                'speaker_y': LaunchConfiguration('speaker_y'),
                'text': LaunchConfiguration('text'),
                'speech_duration': LaunchConfiguration('speech_duration'),
            }],
            remappings=[
                ('in_scan', 'scan'),
                ('out_scan', 'scan_sim'),
                ('in_audio', 'audio/multichannel'),
                ('out_audio', 'audio/multichannel_sim'),
            ],
            output='screen',
        ),
    ])
