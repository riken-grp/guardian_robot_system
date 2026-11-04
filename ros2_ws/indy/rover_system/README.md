# rover_system
ローバを起動・制御するためのパッケージ群

## 概要
本パッケージ群は、以下の6つのパッケージで構成されている。

|パッケージ名|概要|
|---|---|
|amr_ros_driver|ローバの基本的な制御とステータス配信|
|amr_description|ローバのURDF生成と配信|
|auto_charge|自動充電機能|
|rover_tools|ローバ起動の補助機能|
|rover_wrapper|ローバ制御の補助機能|
|vel_filter|障害物回避機能|

## 起動方法
- ナビゲーションを含むローバ全体は以下のコマンドで起動する。
  ```
  ros2 launch rover_tools rover_bringup.launch.py
  ```
- SLAM（map作成）を実施したい場合は以下のコマンドで起動する。
  ```
  ros2 launch rover_tools slam_bringup.launch.py
  ```
  - teleop_twist_keyboardノード等で操作してmapを作成する。
  - 以下のコマンドによって作成したmapの保存が可能。
    ```
    ros2 run nav2_map_server map_saver_cli
    ```

## 基本的な操作方法
各パッケージ内のREADMEにそれぞれの機能の使い方を記載する。  
ここではよく使う機能（ROSトピック）について紹介する。
### ローバ情報
- rover/pose
  - map上のローバの現在位置情報が配信されている。
- rover/battery
  - ロボットの充電状況が配信されている。
  - 充電中のとき、current値が0以下になる。
- rover/bumper
  - バンパの反応がないとき：0
  - 前方のバンパが反応しているとき：1
  - 後方のバンパが反応しているとき：2
- rover/butukusa
  - ローバの状態がJSON形式で配信されている。
### ローバ制御
- rover/cmd_vel
  - ローバに直接速度を送って移動させる。
- rover/move_straight
  - 移動距離を指定して直進指令を送る。
- rover/rotate
  - 回転角度を指定して回転指令を送る。
- rover/navigate
  - 座標を指定してナビゲーション指令を送る。
- auto_charge/dock_start
  - 充電ステーションへの自動ドッキングを開始する。
