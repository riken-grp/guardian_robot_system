"""ローバのドライバ(amr_ros_driver)を起動する。

amr_ros_driver の deb に同梱の amr_ros_driver.launch.py は include せず、ノードを直接起動する。
同梱の launch は版によってリマップ元のトピック名が異なり(e.g. `/cmd_vel`)、
ドライバが実際に購読する `rover/cmd_vel` と一致しないとリマップが無音で無視される。
その場合、障害物回避の速度フィルタ(vel_filter)を通らない速度指令でローバが動いてしまうため、
リマップ元を本ファイルで固定する。

launch引数:
  cmd_vel: ドライバが速度指令を受け取るトピック名(既定値: rover/cmd_vel)
           通常の起動(rover_base.launch.py 等)では rover/cmd_vel_filtered を指定する。
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print("error: failed to get robot name")
        return

    # 設定ファイルは deb のインストール先にあるもの(場所は変更できない)を使う
    config_file = os.path.join(
        get_package_share_directory("amr_ros_driver"), "config", "amr_ros_driver.yaml"
    )

    return LaunchDescription([
        DeclareLaunchArgument("cmd_vel", default_value="rover/cmd_vel"),
        Node(
            package="amr_ros_driver",
            executable="amr_ros_driver",
            namespace=robot_name,
            parameters=[config_file],
            # ドライバは相対名 rover/cmd_vel を購読する(/<ロボット名>/rover/cmd_vel)
            remappings=[("rover/cmd_vel", LaunchConfiguration("cmd_vel"))],
            on_exit=Shutdown(),
        ),
    ])
