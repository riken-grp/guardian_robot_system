# arm_control
腕制御用のROS2パッケージ群。目標関節角や目標姿勢を受け取り、MoveItで経路生成してモータを駆動する。

## パッケージ構成
|パッケージ|概要|
|---|---|
|arm_motor_control|Robstride02モータをCAN経由で制御し、関節状態・温度を配信する|
|arm_moveit_driver|目標関節角/目標姿勢を受信し、MoveItで経路生成して`joint_trajectory`を配信する|
|guardian_urdf|アームのURDFモデルと表示用STLメッシュを提供する|

データの流れは以下の通り。
```
goal_joints / goal_pose / euler_goal_pose / euler_way_and_end_pose
      ↓
 arm_moveit_driver      MoveItで経路生成
      ↓ joint_trajectory（内部トピック）
 arm_motor_control      CAN送信
      ↓ joints / temperature
```

## ビルド方法
本パッケージ群は環境変数 `ON_ROBOT` が `1` の場合のみビルドされる。それ以外の場合、3パッケージともスキップされる。
```
export ON_ROBOT=1
colcon build --packages-select arm_motor_control arm_moveit_driver guardian_urdf
```

## 起動方法
事前に環境変数 `ROBOT_NAME` を設定しておく必要がある。未設定の場合、launchは何も起動せずに終了する。
```
export ROBOT_NAME=<ロボット名>
ros2 launch arm_motor_control arm_bringup.launch.py
```
`arm_bringup.launch.py` は `arm_motor_control` と `arm_moveit_driver` の両方を起動する。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/joints|sensor_msgs/JointState|モータの現在情報（位置・速度・電流値）|
|/$ROBOT_NAME/right(left)_arm/temperature|std_msgs/Float32MultiArray|モータの現在情報（温度）|
|/$ROBOT_NAME/right(left)_arm/joint_trajectory|trajectory_msgs/JointTrajectory|関節位置制御コマンド（内部トピック）|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/goal_joints|sensor_msgs/JointState|モータごとの角度制御コマンド|
|/$ROBOT_NAME/right(left)_arm/goal_pose|geometry_msgs/Pose|手先位置制御コマンド（Quaternion）|
|/$ROBOT_NAME/right(left)_arm/euler_goal_pose|flamingo_grp_msgs/EulerPoseStamped|手先位置制御コマンド（Euler角）|
|/$ROBOT_NAME/right(left)_arm/euler_way_and_end_pose|flamingo_grp_msgs/EulerWayEndPoseStamped|経由点付き手先位置制御コマンド（Euler角）|
|/$ROBOT_NAME/right(left)_arm/joint_trajectory|trajectory_msgs/JointTrajectory|関節位置制御コマンド（内部トピック）|
|/$ROBOT_NAME/right(left)_arm/enable|std_msgs/Empty|全モータのenable命令|
|/$ROBOT_NAME/right(left)_arm/disable|std_msgs/Empty|全モータのdisable命令|

### 操作方法
- 目標角度指令
  - 目標角度を入力して、モータを回転させる。(関節数分の角度をまとめて指定する)
  ``` (各ジョイントを制御)
  ros2 topic pub -1 /$ROBOT_NAME/right(left)_arm/goal_joints sensor_msgs/msg/JointState "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  name: []
  position: [0.1, 0.2, 0.3, 0.4]
  velocity: []
  effort: []"
  ```
  - **`name` フィールドは使用されない。** 受信側は `position` のみを参照するため、値は
    `joint_names` パラメータの並び順（bracket_arm_a → b → c → d）で指定すること。
    順序を誤ると意図しない関節が動作する。

上記以外の操作方法は arm_moveit_driver/README.md を参照。

## 設定方法
### rosパラメータ
arm_motor_control/config/arm_motor_control.yamlにて設定されている。

|parameter名|デフォルト値(右腕)|概要|
|:--|:--|:--|
|arm_status_file|"right_arm.txt"|モーター状態記録用ファイル名|
|can_interface|"rightarm"|CANインターフェース名|
|joints_pub_cycle|100|ジョイント状態の配信周期 [ms]|
|temp_check|true|モータの温度チェック機能の有効化/無効化|
|restart_temp|45.0|モータの再稼働可能温度 [deg]|
|max_temp|50.0|モータの最大温度 [deg]|
|joint_names|["bracket_arm_a_joint", "bracket_arm_b_joint", "bracket_arm_c_joint", "bracket_arm_d_joint"]|ジョイント名の配列|
|can_id|[0x01, 0x02, 0x03, 0x04]|各ジョイントのCAN ID|
|default_offset|[0.0, 0.0, 1.3, 0.0]|各ジョイントのデフォルトオフセット [rad]|
|gain|[-0.8, 1.0, -1.0, 1.0]|各ジョイントのゲイン|
|default_position|[0.0, -1.4, 1.3, -0.3]|各ジョイントのデフォルト位置 [rad]|
|max_position|[0.785, 1.571, 1.571, 0.0]|各ジョイントの最大位置 [rad]|
|min_position|[-3.142, -1.571, -1.571, -2.094]|各ジョイントの最小位置 [rad]|
|max_velocity|[0.314, 0.314, 0.314, 0.314]|各ジョイントの最大速度 [rad/sec]|
|default_velocity|[0.5, 0.5, 0.5, 0.5]|各ジョイントのデフォルト速度 [rad/sec]|

左腕の値は同ファイルの `left_arm/arm_motor_control_node` セクションに定義されている。
`default_offset` / `default_position` / `max_position` / `min_position` は左右で符号が異なる。

### 速度制限の設定箇所について
速度制限は以下の2箇所で独立に設定されている。片方のみを変更すると不整合になるため注意すること。

|設定箇所|パラメータ|値|
|---|---|---|
|arm_motor_control/config/arm_motor_control.yaml|max_velocity|0.314 [rad/sec]|
|arm_moveit_driver/config/joint_limits.yaml|max_velocity × default_velocity_scaling_factor|3.15 × 0.1 = 0.315 [rad/sec]|
