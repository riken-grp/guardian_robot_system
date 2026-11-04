import copy
import os
import sys

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import PushRosNamespace

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, GroupAction,
                            IncludeLaunchDescription)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

# This is a workaround to import rs_launch
try:
    realsense2_camera_path = get_package_share_directory("realsense2_camera")
    sys.path.append(os.path.join(realsense2_camera_path, "launch"))
    import rs_launch
except ImportError:
    print("Could not import rs_launch. Please make sure realsense2_camera is installed.")
    exit()


ROBOT_NAME = os.getenv("ROBOT_NAME")
if ROBOT_NAME is None:
    print("env ROBOT_NAME is not defined")
    exit()

local_parameters = [
    {
        "name": "camera_name_" + ROBOT_NAME,
        "default": ROBOT_NAME + "_camera",
        "description": "camera of " + ROBOT_NAME,
    }
]


def set_configurable_parameters(local_params):
    return dict(
        [
            (param["original_name"], LaunchConfiguration(param["name"]))
            for param in local_params
        ]
    )


def duplicate_params(general_params, posix):
    local_params = copy.deepcopy(general_params)
    for param in local_params:
        param["original_name"] = param["name"]
        param["name"] += "_" + posix
    return local_params


def generate_launch_description():
    params = duplicate_params(rs_launch.configurable_parameters, ROBOT_NAME)
    launch_launch_share_dir = get_package_share_directory("realsense2_camera")


    realsense = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_launch_share_dir, "launch", "rs_launch.py")
        ),
        launch_arguments=list(set_configurable_parameters(params).items())
        + list(
            {
                "rgb_camera.profile": "848x424x30",
                "depth_module.profile": "1280x720x30",
                "align_depth.enable": "true",
                "camera_namespace": ROBOT_NAME,
                "initial_reset": "true",
                "qos": "SENSOR_DATA",
            }.items()
        ),
    )

    actions = rs_launch.declare_configurable_parameters(local_parameters)
    actions += rs_launch.declare_configurable_parameters(params)
    actions += [
        realsense,
        PushRosNamespace(ROBOT_NAME),
    ]

    commands = [GroupAction(actions=actions)]

    return LaunchDescription(commands)
