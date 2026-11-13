# rover_wrapper
ローバ制御を補助するための機能

## 機能概要
- ローバに対して制御指令(直進・回転・ナビゲーション・停止)を送る。
- バンパセンサ反応時にローバのモータをリリースする。
  - バンパセンサの反応がなくなってから10秒後に指令受付状態に戻す。

## 起動方法
```
ros2 launch rover_wrapper rover_wrapper.launch.py
```
- 環境変数`ON_ROBOT=1`のときのみビルドされる。
- ノード（`rover_wrapper_node`）は`/$ROBOT_NAME`名前空間で起動する。以下のトピック名は名前空間からの相対名。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|rover/pose|geometry_msgs/PoseStamped|ローバの現在位置を配信|
|rover/butukusa|common_msgs/StringStamped|ローバの状態情報を配信(JSON形式)|
|rover/cmd_vel|geometry_msgs/Twist|ローバの速度制御トピック|
|rover/initialpose|geometry_msgs/PoseWithCovarianceStamped|ロボットの初期位置を設定|
|rover/bumper_clear|std_msgs/UInt8|バンパークリア指令 1:バンパクリア|
|rover/motor_release|std_msgs/UInt8|モータリリース指令 1:モータリリース|
|right_arm/disable|std_msgs/Empty|右アーム無効化指令（バンパ接触時）|
|left_arm/disable|std_msgs/Empty|左アーム無効化指令（バンパ接触時）|
|right_arm/enable|std_msgs/Empty|右アーム有効化指令（バンパ接触で無効化したアームを、モータリリース解除時に再度有効化）|
|left_arm/enable|std_msgs/Empty|左アーム有効化指令（同上）|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|rover/rotate|std_msgs/Float32|ローバの回転コマンド(角度)|
|rover/move_straight|std_msgs/Float32|ローバの直進コマンド(距離)|
|rover/navigate|common_msgs/PoseAngle|ローバのナビゲーションコマンド|
|rover/stop|std_msgs/Empty|ローバの停止コマンド|
|rover/set_initialpose|common_msgs/PoseAngle|初期位置設定コマンド|
|rover/bumper|std_msgs/UInt8|バンパーのラッチ状態 0:接触無し 1:前方接触 2:後方接触|
|rover/firm_state|std_msgs/UInt8|ファームウェア状態 0:INIT 1:RUN 2:STOP 3:CHARGE(未使用) 4:EMERGENCY 5:SHUTDOWN 9:ERROR|

### 操作方法
- 直進（後退）指令
  - 移動距離を入力して、ローバを直進させる。
  ``` (1[m]だけ直進させる指令)
  ros2 topic pub /$ROBOT_NAME/rover/move_straight std_msgs/msg/Float32 "data: 1.0" -1
  ```
- 回転指令
  - 回転角度を入力して、ローバを回転させる。
  ``` (1[rad]だけ回転させる指令)
  ros2 topic pub /$ROBOT_NAME/rover/rotate std_msgs/msg/Float32 "data: 1.0" -1
  ```
- ナビゲーション指令
  - 座標・角度を入力して、指令した位置まで移動させる。
  ``` (座標：(1.0, 2.0)、向き：1.0[rad]まで移動させる指令)
  ros2 topic pub /$ROBOT_NAME/rover/navigate common_msgs/msg/PoseAngle "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  position:
    x: 1.0
    y: 2.0
    z: 0.0
  angle: 1.0" -1
  ```
- 現在位置設定
  - 現在の位置がずれていた場合に、位置を設定する。
  ``` (座標：(1.0, 2.0)、向き：1.0[rad]に現在位置を設定)
  ros2 topic pub /$ROBOT_NAME/rover/set_initialpose common_msgs/msg/PoseAngle "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  position:
    x: 1.0
    y: 2.0
    z: 0.0
  angle: 1.0" -1
  ```
- 停止指令
  - ローバの移動を取りやめて停止させる。
  ```
  ros2 topic pub /$ROBOT_NAME/rover/stop std_msgs/msg/Empty "{}" -1
  ```

## 設定方法
### rosパラメータ
rover_wrapper/config/default_param.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|report_rate|0.05|配信周期 [s]|
|move_speed|0.7|移動速度 [m/s]|
|rotate_speed|0.5|回転速度 [rad/s]|
|motor_release_time|10.0|モータリリース時間 [s]|