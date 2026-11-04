import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

ROBOT_NAME = os.getenv("ROBOT_NAME", "")
CUDA_VISIBLE_DEVICES = os.getenv("CUDA_VISIBLE_DEVICES", "3")


def generate_launch_description():
    config_dir = os.path.join(
        get_package_share_directory('ssl_bringup'), 'config'
    )

    asr_params_file = os.path.join(config_dir, 'asr_params.yaml')

    asr_node = Node(
        package='ssl_asr',
        executable='asr_node',
        name='asr_node',
        namespace=ROBOT_NAME,
        parameters=[asr_params_file],
        additional_env={'CUDA_VISIBLE_DEVICES': CUDA_VISIBLE_DEVICES},
        remappings=[
            ('in_speech_segments', 'recog/ssl/identified_speech_segments'),
            ('out_raw_text', 'recog/ssl/asr/raw_text'),
        ],
        output='screen',
    )

    return LaunchDescription([
        asr_node,
    ])
