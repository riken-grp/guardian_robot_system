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
from launch_ros.actions import PushRosNamespace
from launch.actions import IncludeLaunchDescription, OpaqueFunction, Shutdown, GroupAction
from launch.substitutions import LaunchConfiguration, ThisLaunchFileDir
from launch.launch_description_sources import PythonLaunchDescriptionSource
import sys
import os
import pathlib
sys.path.append(str(pathlib.Path(__file__).parent.absolute()))
import rs_launch

robot_name = os.getenv("ROBOT_NAME")

local_parameters = [{'name': 'camera_name3', 'default': robot_name+'_camera', 'description': 'camera3 unique name'},
                    {'name': 'camera_namespace3', 'default': robot_name+'_camera', 'description': 'camera3 namespace'},
                    {'name': 'camera_link3', 'default': robot_name+'_camera', 'description': 'camera3 base link'},
                    {'name': 'pointcloud.enable3', 'default': 'true', 'description': 'camera3 pointcloud enable'},
                    {'name': 'usb_port_id3', 'default': "'4-2.3.4'", 'description': 'camera3 usb serial port'},
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

def generate_launch_description():
    params3 = duplicate_params(rs_launch.configurable_parameters, '3')
    node_params = set_configurable_parameters(params3)
    # JPEG quality of compressed color image (compressed_image_transport in Humble).
    # The parameter name is the topic /<robot>/<robot>_camera/color/image_raw
    # with the node namespace /<robot> removed and "/" replaced by "."
    node_params['.' + robot_name + '_camera.color.image_raw.jpeg_quality'] = 80
    return LaunchDescription(
        rs_launch.declare_configurable_parameters(local_parameters) +
        rs_launch.declare_configurable_parameters(params3) +
        [
        GroupAction([
            PushRosNamespace(robot_name),
            OpaqueFunction(function=rs_launch.launch_setup,
                            kwargs = {'params': node_params,
                                      'param_name_suffix': '3'})
        ])
    ])
