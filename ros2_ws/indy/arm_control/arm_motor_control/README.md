# arm_motor_control
Robstride02モータをCAN経由で制御し、関節角度・速度・電流値・温度をROSトピックとして配信する。

## ビルド方法
本パッケージは環境変数 `ON_ROBOT` が `1` の場合のみビルドされる。それ以外の場合はスキップされる。
```
export ON_ROBOT=1
colcon build --packages-select arm_motor_control
```

## 起動方法
```
export ROBOT_NAME=<ロボット名>
ros2 launch arm_motor_control arm_motor_control.launch.py
```
`ROBOT_NAME` が未設定の場合、名前空間のロボット名部分が空文字になり、
トピックは `/right_arm/...` の形で配信される。

MoveItを含む腕制御一式を起動する場合は `arm_bringup.launch.py` を使用する
（こちらは `ROBOT_NAME` 未設定時には何も起動しない）。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/joints|sensor_msgs/JointState|モータの現在情報（位置・速度・電流値）|
|/$ROBOT_NAME/right(left)_arm/temperature|std_msgs/Float32MultiArray|モータの現在情報（温度）|

`joints` の `effort` にはトルク値ではなくq軸電流値（Iqf）が格納される。

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/joint_trajectory|trajectory_msgs/JointTrajectory|関節位置制御コマンド|
|/$ROBOT_NAME/right(left)_arm/enable|std_msgs/Empty|全モータのenable命令|
|/$ROBOT_NAME/right(left)_arm/disable|std_msgs/Empty|全モータのdisable命令|

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
