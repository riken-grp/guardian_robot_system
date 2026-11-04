#!/usr/bin/env python
# coding: utf-8 -*-

"""ROS Launch Module for Indy's ASR System."""
from pathlib import Path

import launch
from ament_index_python.packages import get_package_share_directory
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    """Returns the ROS2 Node Launch Description for Indy's full ASR System.
    Called via `ros2 launch asr full_asr_launch.py`"""

    mem_share_dir = Path(get_package_share_directory("memory"))
    mongo_uri = LaunchConfiguration("mongo_uri")
    mongo_port = LaunchConfiguration("mongo_port")

    return launch.LaunchDescription(
        [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [str(mem_share_dir / "memory_node_launch.py")]
                ),
                launch_arguments={
                    "mongo_uri": mongo_uri,
                    "mongo_port": mongo_port,
                }.items(),
            ),
        ]
    )
