# Copyright (c) 2018 Intel Corporation
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
import yaml
from pymongo import MongoClient

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, GroupAction, EmitEvent, 
                            SetEnvironmentVariable, RegisterEventHandler, Shutdown)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import LoadComposableNodes
from launch_ros.actions import Node, LifecycleNode
from launch_ros.descriptions import ComposableNode, ParameterFile
from launch_ros.events.lifecycle import ChangeState
from launch_ros.event_handlers import OnStateTransition
import lifecycle_msgs.msg
from nav2_common.launch import RewrittenYaml
import lifecycle_msgs


def lifecycle_start_transision(target_node, action_node):
   return RegisterEventHandler(#イベントハンドラの登録
            OnProcessStart(#プロセス起動イベント
               target_action=target_node,
               on_start=[
                  # action_nodeをconfigur遷移させるイベントを登録
                  EmitEvent(
                     event=ChangeState(
                           lifecycle_node_matcher=matches_action(action_node),
                           transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
                     )
                  ),
               ],
            )
          )

def lifecycle_state_transision(target_node, action_node, target_start_state, target_goal_state, transision_goal):
   return RegisterEventHandler(#イベントハンドラの登録
            OnStateTransition(#target_nodeが状態遷移したときのイベント
               target_lifecycle_node=target_node,
               start_state=target_start_state, goal_state=target_goal_state,# target_start_state状態からtarget_goal_state状態へ遷移
               entities=[
                  # action_nodeをtransision_goal状態に遷移させるイベントを登録
                  EmitEvent(
                     event=ChangeState(
                           lifecycle_node_matcher=matches_action(action_node),
                           transition_id=transision_goal,
                     )
                  ),
               ],
            )
         )

def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    # Get the launch directory
    bringup_dir = get_package_share_directory('rover_tools')

    namespace = LaunchConfiguration('namespace')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    params_file = LaunchConfiguration('params_file')
    use_composition = LaunchConfiguration('use_composition')
    container_name = LaunchConfiguration('container_name')
    container_name_full = (namespace, '/', container_name)
    use_respawn = LaunchConfiguration('use_respawn')
    log_level = LaunchConfiguration('log_level')

    lifecycle_nodes = ['amcl']


    # Map fully qualified names to relative ones so the node's namespace can be prepended.
    # In case of the transforms (tf), currently, there doesn't seem to be a better alternative
    # https://github.com/ros/geometry2/issues/32
    # https://github.com/ros/robot_state_publisher/pull/30
    # TODO(orduno) Substitute with `PushNodeRemapping`
    #              https://github.com/ros2/launch_ros/issues/56
    remappings = [('/'+robot_name+'/map', '/map'),
                  ('/'+robot_name+'/map_server/transition_event', '/map_server/transition_event')]

    # initioalpose設定
    # ファイルから取得
    file_path = os.path.expanduser("~/config/rover_pose.txt")
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            content = file.read().strip()
        num = [num for num in content.split(',')]
        if len(num) == 3:
            pose = [float(num) for num in content.split(',')]
        else:
            pose = [0.0, 0.0, 0.0]
    else:
        pose = [0.0, 0.0, 0.0]
    initial_x = LaunchConfiguration('pose_x')
    initial_x_cmd = DeclareLaunchArgument('pose_x', default_value=str(pose[0]))
    initial_y = LaunchConfiguration('pose_y')
    initial_y_cmd = DeclareLaunchArgument('pose_y', default_value=str(pose[1]))
    initial_yaw = LaunchConfiguration('yaw')
    initial_yaw_cmd = DeclareLaunchArgument('yaw', default_value=str(pose[2]))

    # Create our own temporary YAML files that include substitutions
    param_substitutions = {
        'use_sim_time': use_sim_time,
        '/**/amcl.ros__parameters.base_frame_id': robot_name+'_base_footprint',
        '/**/amcl.ros__parameters.odom_frame_id': robot_name+'_odom'}

    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=namespace,
            param_rewrites=param_substitutions,
            convert_types=True),
        allow_substs=True)

    stdout_linebuf_envvar = SetEnvironmentVariable(
        'RCUTILS_LOGGING_BUFFERED_STREAM', '1')

    declare_namespace_cmd = DeclareLaunchArgument(
        'namespace',
        default_value='',
        description='Top-level namespace')

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (Gazebo) clock if true')

    declare_params_file_cmd = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(bringup_dir, 'nav2_params.yaml'),
        description='Full path to the ROS2 parameters file to use for all launched nodes')

    declare_autostart_cmd = DeclareLaunchArgument(
        'autostart', default_value='true',
        description='Automatically startup the nav2 stack')

    declare_use_composition_cmd = DeclareLaunchArgument(
        'use_composition', default_value='False',
        description='Use composed bringup if True')

    declare_container_name_cmd = DeclareLaunchArgument(
        'container_name', default_value='nav2_container',
        description='the name of conatiner that nodes will load in if use composition')

    declare_use_respawn_cmd = DeclareLaunchArgument(
        'use_respawn', default_value='True',
        description='Whether to respawn if a node crashes. Applied when composition is disabled.')

    declare_log_level_cmd = DeclareLaunchArgument(
        'log_level', default_value='info',
        description='log level')

    amcl_node = LifecycleNode(
                package='nav2_amcl',
                executable='amcl',
                name='amcl',
                namespace=robot_name,
                # output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                parameters=[configured_params]+
                           [{'initial_pose.x': initial_x},
                            {'initial_pose.y': initial_y},
                            {'initial_pose.yaw': initial_yaw}],
                arguments=['--ros-args', '--log-level', log_level],
                remappings=remappings + [('initialpose', 'rover/initialpose')],
                on_exit=Shutdown())

    load_nodes = GroupAction(
        condition=IfCondition(PythonExpression(['not ', use_composition])),
        actions=[
            amcl_node,
            Node(
                package='nav2_lifecycle_manager',
                executable='lifecycle_manager',
                name='lifecycle_manager_localization',
                namespace=robot_name,
                # output='screen',
                arguments=['--ros-args', '--log-level', log_level],
                parameters=[{'use_sim_time': use_sim_time},
                            {'autostart': autostart},
                            {'node_names': ['amcl']}]),
            lifecycle_state_transision(amcl_node, amcl_node, "configuring", "inactive",
                                       lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE)
        ],
        
    )

    load_composable_nodes = LoadComposableNodes(
        condition=IfCondition(use_composition),
        target_container=container_name_full,
        composable_node_descriptions=[
            ComposableNode(
                package='nav2_amcl',
                plugin='nav2_amcl::AmclNode',
                name='amcl',
                namespace=robot_name,
                # parameters=[configured_params],
                parameters=[configured_params]+
                           [{'initial_pose.x': initial_x},
                            {'initial_pose.y': initial_y},
                            {'initial_pose.yaw': initial_yaw}],
                remappings=remappings + [('initialpose', 'rover/initialpose')]),
            ComposableNode(
                package='nav2_lifecycle_manager',
                plugin='nav2_lifecycle_manager::LifecycleManager',
                name='lifecycle_manager_localization',
                namespace=robot_name,
                parameters=[{'use_sim_time': use_sim_time,
                             'autostart': autostart,
                             'node_names': lifecycle_nodes},
                            {'bond_timeout': 60.0}]),
        ],
    )
    # map_tf_node removed: AMCL already publishes map->odom TF (tf_broadcast: true in nav2_params.yaml)
    # This was causing duplicate TF broadcasts which overflowed the loopback buffer during WiFi disconnection

    # Create the launch description and populate
    ld = LaunchDescription()

    # Set environment variables
    ld.add_action(stdout_linebuf_envvar)

    # Declare the launch options
    ld.add_action(declare_namespace_cmd)
    ld.add_action(declare_use_sim_time_cmd)
    ld.add_action(declare_params_file_cmd)
    ld.add_action(declare_autostart_cmd)
    ld.add_action(declare_use_composition_cmd)
    ld.add_action(declare_container_name_cmd)
    ld.add_action(declare_use_respawn_cmd)
    ld.add_action(declare_log_level_cmd)
    ld.add_action(initial_x_cmd)
    ld.add_action(initial_y_cmd)
    ld.add_action(initial_yaw_cmd)

    # Add the actions to launch all of the localiztion nodes
    ld.add_action(load_nodes)
    ld.add_action(load_composable_nodes)

    return ld
