#!/usr/bin/env python
# coding: utf-8 -*-

"""ROS Launch Module for Indy's Memory System. Version 2"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace


def generate_launch_description():
    """Returns the ROS2 Node Launch Description for Indy's Memory System.
    Called via `ros2 launch memory memory_launch.py`"""

    # 1. get robot name from environmental variable
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return

    # 2. set mongo_uri and mongo_port by launch arguments
    mongo_uri = LaunchConfiguration("mongo_uri")
    declare_mongo_uri = DeclareLaunchArgument("mongo_uri", default_value="")
    mongo_port = LaunchConfiguration("mongo_port")
    declare_mongo_port = DeclareLaunchArgument("mongo_port", default_value="1")

    return LaunchDescription(
        [
            declare_mongo_uri,
            declare_mongo_port,
            GroupAction(
                [
                    # 3. set namespace to node in GroupAction
                    PushRosNamespace(robot_name),
                    Node(
                        package="llm_responder",
                        executable="llm_responder_node",
                        # 4. set mongo_uri and mongo_port to node
                        parameters=[
                            {"mongo_uri": mongo_uri, "mongo_port": mongo_port}
                        ],
                        # 5. shutdown node on exit
                        on_exit=Shutdown(),
                    ),
                ]
            ),
        ]
    )
