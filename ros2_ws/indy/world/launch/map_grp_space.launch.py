import os

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import OpaqueFunction
from launch.actions import Shutdown
from launch.substitutions import LaunchConfiguration

from pyindy.param_manager import ParamManager

def launch_setup(context):
    # MongoDBに接続
    mongo_uri = LaunchConfiguration("mongo_uri").perform(context)
    mongo_port = int(LaunchConfiguration("mongo_port").perform(context))
    pm = ParamManager(mongo_uri, mongo_port)
    
    params = pm.get_param("map_server")

    # map_serverが取得できない場合は終了
    if not params:
        print(
            "Parameters for Map Server not in Params DB. "
        )
        return []

    # mapファイル名取得
    map_yaml_file = params.get("map_yaml_file", None)
    keepout_yaml_file = params.get("keepout_yaml_file", None)
    map_param_path = get_package_share_directory("world")

    # map_yaml_fileが存在しない場合は終了
    if not map_yaml_file:
        print("error: map_yaml_file is not set.")
        return []

    use_sim_time = True
    autostart = True
    nodes = []
    lifecycle_nodes = ["map_server"]

    # MapServer生成
    map_config = {
        "yaml_filename": os.path.join(map_param_path, map_yaml_file)
    }

    map_server_cmd = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        # output='screen',
        parameters=[map_config],
        on_exit=Shutdown(),
    )

    nodes.append(map_server_cmd)

    # keepout_yaml_fileが存在する場合は、keepout_filter_mask_server生成
    if keepout_yaml_file:
        keepout_map_config = {
            "yaml_filename": os.path.join(map_param_path, keepout_yaml_file)
        }

        keepout_map_server_cmd = Node(
            package="nav2_map_server",
            executable="map_server",
            name="keepout_filter_mask_server",
            # output='screen',
            parameters=[keepout_map_config],
            remappings=[("/map", "/keepout_filter_mask")],
        )

        nodes.append(keepout_map_server_cmd)
        lifecycle_nodes.append("keepout_filter_mask_server")

    # lifecycle_manager生成
    start_lifecycle_manager_cmd = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager",
        # output='screen',
        emulate_tty=True,
        parameters=[
            {"use_sim_time": use_sim_time},
            {"autostart": autostart},
            {"node_names": lifecycle_nodes},
        ],
    )
    
    nodes.append(start_lifecycle_manager_cmd)

    return nodes

def generate_launch_description():

    return LaunchDescription([
        DeclareLaunchArgument("mongo_uri", default_value=""),
        DeclareLaunchArgument("mongo_port", default_value='1'),
        OpaqueFunction(function=launch_setup),
    ])
