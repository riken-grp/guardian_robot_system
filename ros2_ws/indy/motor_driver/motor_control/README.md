# motor_control
姿勢(首)モータ制御用のROS2ドライバ

## 起動方法

- 実機の場合
```
ros2 launch motor_control motor_control.launch.py
```
- ノード（`motor_control_node`）は`/$ROBOT_NAME`名前空間で起動する。以下のトピック名は名前空間からの相対名。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|motor_control/joints|sensor_msgs/JointState|モータの現在情報（位置・速度・電流値）|
|motor_control/temperature|std_msgs/Float32MultiArray|モータの現在情報（温度）|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|motor_control/control_position|sensor_msgs/JointState|モータの位置制御コマンド|
|motor_control/control_speed|sensor_msgs/JointState|モータの速度制御コマンド|
|motor_control/enable|std_msgs/Empty|全モータのenable命令|
|motor_control/disable|std_msgs/Empty|全モータのdisable命令|

### 操作方法
- 目標角度指令
  - 目標角度を入力して、モータを回転させる。
  ``` (各ジョイントを制御)
  ros2 topic pub /$ROBOT_NAME/motor_control/control_position sensor_msgs/msg/JointState   "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  name: [${ROBOT_NAME}_neck_yaw_joint, ${ROBOT_NAME}_neck_pitch_joint, ${ROBOT_NAME}_body_pitch_joint]
  position: [0.1, 0.2, 0.3]
  velocity: []
  effort: []" -1
  ```

- 目標角速度指令
  - 各モータに目標角速度を設定する。
  ``` (各ジョイントを制御)
  ros2 topic pub /$ROBOT_NAME/motor_control/control_speed sensor_msgs/msg/JointState   "header:
    stamp:
      sec: 0
      nanosec: 0
  name: [${ROBOT_NAME}_neck_yaw_joint, ${ROBOT_NAME}_neck_pitch_joint, ${ROBOT_NAME}_body_pitch_joint]
  velocity: [0.5, 0.5, 0.5]" -1
  ```
  - ジョイント名は`<ROBOT_NAME>_<joint_name>`の形式。上の例はシェルで`$ROBOT_NAME`を展開させるため、ジョイント名を引用符で囲まずに`${ROBOT_NAME}_...`と書いている。

- 全モータのenable命令
  - 全モータを有効化する。
  ```
  ros2 topic pub /$ROBOT_NAME/motor_control/enable std_msgs/msg/Empty "{}" -1
  ```

- 全モータのdisable命令
  - 全モータを無効化する。
  ```
  ros2 topic pub /$ROBOT_NAME/motor_control/disable std_msgs/msg/Empty "{}" -1
  ```

## 設定方法
### rosパラメータ
config/motor_control.yamlにて設定されている。
|parameter名|デフォルト値|概要|
|:--|:--|:--|
|can_interface|"neck"|CANインターフェース名|
|joint_name|["neck_yaw_joint", "neck_pitch_joint", "body_pitch_joint"]|制御対象のジョイント名リスト、実際のジョイント名は先頭に"ROBOT_NAME_"が付く|
|can_id|[0x02, 0x03, 0x01]|各モータのCAN ID（16進数）|
|default_offset|[0.0, 0.0, 0.0]|各モータのデフォルトオフセット[rad]|
|gain|[-1.0, -1.0, -1.0]|各モータのゲイン（符号含む）|
|max_position|[1.396, 0.785, 0.0]|各モータの最大位置[rad]|
|min_position|[-1.396, -0.15, -0.314]|各モータの最小位置[rad]|
|max_velocity|[1.047, 0.349, 0.314]|各モータの最大速度[rad/sec]|
|default_velocity|[1.0, 0.5, 0.5]|各モータのデフォルト速度[rad/sec]|

※ yamlには`default_acceleration`・`default_torque`も記載されているが、現在のコード（`src/motor_control.cpp`）では使用されていない。
