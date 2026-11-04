# Copyright 2022 eSOL Co.,Ltd.
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

import os
import launch
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch.actions import (DeclareLaunchArgument, EmitEvent, RegisterEventHandler, Shutdown)
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml

lidar_names = [
    {"num": "3rd", "name": "lidar"},
]

# 2台LiDAR接続時のurg_node2複数起動
def launch_urg_node(robot_name, num):
    lidar_name = [x["name"]  for x in lidar_names if (x["num"] == num)][0]
    param_substitutions = {
        'frame_id': robot_name+'_'+lidar_name+'_link'}
    
    # パラメータファイルのパス設定
    config_file_path = os.path.join(
        get_package_share_directory('rover_tools'),
        'params_ether_'+num+'.yaml'
    )

    # パラメータファイルのロード
    with open(config_file_path, 'r') as file:
        config_params = yaml.safe_load(file)['urg_node2']['ros__parameters']
    config_params['frame_id'] = robot_name+'_'+lidar_name+'_link'

    # urg_node2をライフサイクルノードとして起動
    lifecycle_node = LifecycleNode(
        package='urg_node2',
        executable='urg_node2_node',
        name=LaunchConfiguration('node_name_'+num),
        remappings=[('scan', LaunchConfiguration('scan_topic_name_'+num))],
        parameters=[config_params],
        namespace="",
        # output='screen',
        on_exit=Shutdown()
    )

    return lifecycle_node

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    lifecycle_node_3rd = launch_urg_node(robot_name, "3rd")

    # Unconfigure状態からInactive状態への遷移（auto_startがtrueのとき実施）（1台目）
    urg_node2_node_3rd_configure_event_handler = RegisterEventHandler(
        event_handler=OnProcessStart(
            target_action=lifecycle_node_3rd,
            on_start=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(lifecycle_node_3rd),
                        transition_id=Transition.TRANSITION_CONFIGURE,
                    ),
                ),
            ],
        ),
        condition=IfCondition(LaunchConfiguration('auto_start')),
    )

    # Inactive状態からActive状態への遷移（auto_startがtrueのとき実施）（1台目）
    urg_node2_node_3rd_activate_event_handler = RegisterEventHandler(
        event_handler=OnStateTransition(
            target_lifecycle_node=lifecycle_node_3rd,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(lifecycle_node_3rd),
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    ),
                ),
            ],
        ),
        condition=IfCondition(LaunchConfiguration('auto_start')),
    )

    # パラメータについて
    # auto_start          : 起動時自動でActive状態まで遷移 (default)true
    # node_name_3rd       : 1台目のノード名 (default)"urg_node2_3rd"
    # scan_topic_name_3rd : トピック名 (default)"scan_3rd" *マルチエコー非対応*
    # *マルチエコーを使用する場合は上部のnode起動部のremappingsを直接編集してください*
    # *ロードするパラメータファイルは上部のファイル名を直接編集してください*
    return LaunchDescription([
        DeclareLaunchArgument('auto_start', default_value='true'),
        DeclareLaunchArgument('node_name_3rd', default_value='urg_node'),
        DeclareLaunchArgument('scan_topic_name_3rd', default_value='scan'),
        lifecycle_node_3rd,
        urg_node2_node_3rd_configure_event_handler,
        urg_node2_node_3rd_activate_event_handler,
    ])
