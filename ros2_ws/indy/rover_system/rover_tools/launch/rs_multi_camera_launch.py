# Copyright 2023 Intel Corporation. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# DESCRIPTION #
# ----------- #
# Use this launch file to launch 2 devices.
# The Parameters available for definition in the command line for each camera are described in rs_launch.configurable_parameters
# For each device, the parameter name was changed to include an index.
# For example: to set camera_name for device1 set parameter camera_name1.
# command line example:
# ros2 launch realsense2_camera rs_multi_camera_launch.py camera_name1:=D400 device_type2:=l5. device_type1:=d4..

"""Launch realsense2_camera node."""
import copy
from launch import LaunchDescription, LaunchContext
import launch_ros.actions
from launch.actions import IncludeLaunchDescription, OpaqueFunction, Shutdown
from launch.substitutions import LaunchConfiguration, ThisLaunchFileDir
from launch.launch_description_sources import PythonLaunchDescriptionSource
import sys
import os
import pathlib
sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
import rs_launch

robot_name = os.getenv("ROBOT_NAME")

local_parameters = [{'name': 'camera_name1', 'default': robot_name+'_camera_bu', 'description': 'camera1 unique name'},
                    {'name': 'camera_name2', 'default': robot_name+'_camera_td', 'description': 'camera2 unique name'},
                    {'name': 'camera_name3', 'default': robot_name+'_camera', 'description': 'camera3 unique name'},
                    {'name': 'camera_namespace1', 'default': robot_name+'_camera_bu', 'description': 'camera1 namespace'},
                    {'name': 'camera_namespace2', 'default': robot_name+'_camera_td', 'description': 'camera2 namespace'},
                    {'name': 'camera_namespace3', 'default': robot_name+'_camera', 'description': 'camera3 namespace'},
                    {'name': 'camera_link1', 'default': robot_name+'_camera_bu', 'description': 'camera1 base link'},
                    {'name': 'camera_link2', 'default': robot_name+'_camera_td', 'description': 'camera2 base link'},
                    {'name': 'camera_link3', 'default': robot_name+'_camera', 'description': 'camera3 base link'},
                    {'name': 'pointcloud.enable1', 'default': 'true', 'description': 'camera1 pointcloud enable'},
                    {'name': 'pointcloud.enable2', 'default': 'true', 'description': 'camera2 pointcloud enable'},
                    {'name': 'pointcloud.enable3', 'default': 'true', 'description': 'camera3 pointcloud enable'},
                    {'name': 'usb_port_id1', 'default': "'4-1.1'", 'description': 'camera1 usb serial port'},
                    {'name': 'usb_port_id2', 'default': "'4-1.2'", 'description': 'camera2 usb serial port'},
                    {'name': 'usb_port_id3', 'default': "'4-2.3.4'", 'description': 'camera3 usb serial port'},
                    {'name': '_usb_port_id1', 'default': "'4-1.1'", 'description': 'camera1 usb serial port'},
                    {'name': '_usb_port_id2', 'default': "'4-1.2'", 'description': 'camera2 usb serial port'},
                    {'name': '_usb_port_id3', 'default': "'4-2.3.4'", 'description': 'camera3 usb serial port'},
                    ]

def set_configurable_parameters(local_params):
    return dict([(param['original_name'], LaunchConfiguration(param['name'])) for param in local_params])

def duplicate_params(general_params, posix):
    local_params = copy.deepcopy(general_params)
    for param in local_params:
        param['original_name'] = param['name']
        param['name'] += posix
    return local_params

def launch_static_transform_publisher_node(context : LaunchContext):
    # dummy static transformation from camera1 to camera2
    node = launch_ros.actions.Node(
            package = "tf2_ros",
            executable = "static_transform_publisher",
            arguments = ["0", "0", "0", "0.9", "0", "3.14",
                          context.launch_configurations['camera_link1'] + "_link",
                          context.launch_configurations['camera_link2'] + "_link"],
            on_exit=Shutdown()
    )
    return [node]

def generate_launch_description():
    params1 = duplicate_params(rs_launch.configurable_parameters, '1')
    params2 = duplicate_params(rs_launch.configurable_parameters, '2')
    params3 = duplicate_params(rs_launch.configurable_parameters, '3')
    return LaunchDescription(
        rs_launch.declare_configurable_parameters(local_parameters) +
        rs_launch.declare_configurable_parameters(params1) +
        rs_launch.declare_configurable_parameters(params2) +
        rs_launch.declare_configurable_parameters(params3) +
        [
        OpaqueFunction(function=rs_launch.launch_setup,
                       kwargs = {'params'           : set_configurable_parameters(params1),
                                 'param_name_suffix': '1'}),
        OpaqueFunction(function=rs_launch.launch_setup,
                       kwargs = {'params'           : set_configurable_parameters(params2),
                                 'param_name_suffix': '2'}),
        OpaqueFunction(function=rs_launch.launch_setup,
                       kwargs = {'params'           : set_configurable_parameters(params3),
                                 'param_name_suffix': '3'}),
        OpaqueFunction(function=launch_static_transform_publisher_node)
    ])
