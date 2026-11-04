# rover_tools
ローバを起動するための補助機能

## 機能概要
- ローバ・センサ類のlaunchファイルを用意している。
- ナビゲーション設定を行っている。

## 起動方法
### ローバ全般
- ローバ全体（ナビゲーションを含む）
  ```
  ros2 launch rover_tools rover_bringup.launch.py
  ```
- SLAM機能(map作成)
  ```
  ros2 launch rover_tools slam_bringup.launch.py
  ```
  - teleop_twist_keyboardノード等で操作してmapを作成する。
  - 以下のコマンドによって作成したmapの保存が可能。
    ```
    ros2 run nav2_map_server map_saver_cli
    ```
### 各機能
- 自己位置推定
  ```
  ros2 launch rover_tools localization_launch.py
  ```
- ナビゲーション機能
  ```
  ros2 launch rover_tools navigation_launch.py
  ```
  - config/nav2_param.yamlで各種設定
- 足元LiDAR x2 (ナビゲーション用)
  ```
  ros2 launch rover_tools lidar_launch.py
  ```
- 胸元LiDAR (HumanTracker用)
  ```
  ros2 launch rover_tools lidar_ht_launch.py
  ```
- 足元RealSense x2 (ナビゲーション用)
  ```
  ros2 launch rover_tools rs_camera_nav_launch.py
  ```
- 頭部RealSense x2 (画像認識用)
  ```
  ros2 launch rover_tools rs_camera_recog_launch.py
  ```
- Realsense x3
  ```
  ros2 launch rover_tools rs_multi_camera_launch.py
  ```
- RealSense (YAMLファイルから読み込んだ設定で起動)
  ```
  ros2 launch rover_tools rs_launch.py
  ```
- ジョイスティック
  ```
  ros2 launch rover_tools joy_launch.py
  ```