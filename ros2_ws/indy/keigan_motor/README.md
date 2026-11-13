# keigan_motor
Keigan Motorを制御するドライバノード

## 起動手順
### pykeiganの配置
本ノードはKeigan Motor公式のPythonライブラリ「pykeigan」を使用します。  
使用する際は以下の手順で`keigan_motor/keigan_motor/pykeigan`に配置してください。

配置後のディレクトリ構成は以下の通りです。
```
keigan_motor/
├── keigan_motor/
│   ├── __init__.py
│   ├── keigan_motor.py
│   └── pykeigan/
│       ├── __init__.py
│       ├── blecontroller.py
│       ├── controller.py
│       ├── usbcontroller.py
│       └── utils.py
├── setup.py
└── ...
```

- pykeiganを配置する。
  - 公式リポジトリ([keigan-motor/pykeigan_motor](https://github.com/keigan-motor/pykeigan_motor))から取得して配置し、import文を相対importに修正する。
    ```
    git clone https://github.com/keigan-motor/pykeigan_motor.git
    cp -r pykeigan_motor/pykeigan $GUARDIAN_ROBOT_PATH/ros2_ws/indy/keigan_motor/keigan_motor/
    cd $GUARDIAN_ROBOT_PATH/ros2_ws/indy/keigan_motor/keigan_motor/pykeigan
    sed -i 's/^from pykeigan/from ..pykeigan/' *.py
    ```
    - 修正後、各ファイルのimport文が`from ..pykeigan import controller as base`、`from ..pykeigan.utils import *`の形式になっていることを確認する。
- 配置後、パッケージをビルドする。
  ```
  cd $GUARDIAN_ROBOT_PATH/ros2_ws
  colcon build --packages-select keigan_motor
  ```
  - pykeiganが配置されていない場合、ビルド時に警告が出て、ノード・launch・設定ファイルはインストールされない。

### モータの実行権限の設定
設定手順は以下の通りです。
- 接続したいモータの実行権限を変更する。
  - "ls /dev/serial/by-id"で接続されているモータを確認する。
  - 以下のコマンドにより実行権限を変更する。（制御するモータを一つずつ選択することも可）
    ```
    sudo chmod 777 /dev/serial/by-id/usb-*
    ```

### 設定ファイルの更新
本ノードの設定ファイルは、パッケージ内の`config/<ROBOT_NAME>_param.yaml`（`<ROBOT_NAME>`は環境変数`ROBOT_NAME`の値）です。launch時にこのファイルが読み込まれるため、使用するロボット名のファイルが必要です。現状は`indy1_param.yaml`と`indy2_param.yaml`のみ用意されています。  

設定ファイルを更新したら、以下のコマンドを実行してビルドをし直す必要があります。
```
colcon build --packages-select keigan_motor
```
設定ファイルの内容は以下の通りです。
```
/**/keigan_motor_node:
  ros__parameters:
    joint_name:
      - "neck_yaw_joint"
      - "neck_pitch_joint"
      - "body_pitch_joint"

    joint_port:
      - "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DM00KLZB-if00-port0"
      - "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DM00KU8D-if00-port0"
      - "/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DM00KKFY-if00-port0"

    max_velocity: 
      - 3.0 # [rad/sec]
      - 3.0 # [rad/sec]
      - 3.0 # [rad/sec]

    default_velocity: 
      - 1.0 # [rad/sec]
      - 1.0 # [rad/sec]
      - 1.0 # [rad/sec]

    default_acceleration: 
      - 3.0 # [rad/sec^2]
      - 3.0 # [rad/sec^2]
      - 3.0 # [rad/sec^2]

    default_torque: 
      - 1.0 # [Nm]
      - 1.0 # [Nm]
      - 1.0 # [Nm]

    report_hz: 10.0 # Frequency of joints info publisher [Hz]

    nearly_zero_vel: 0.05 # Speed regarded as zero when executing target_vel_pose [rad/sec]

    nearly_target_pose: 0.02 # Position difference regarded as target when executing target_vel_pose [rad]

    max_duration: 15.0 # Max duration to stop rotation when executing target_vel_pose [sec]

```
- joint_name：ROSで管理する際に使用するモータ固有の名称
- joint_port：各モータの接続ポート
- max_velocity:：モータの最大速度[rad/sec]
- default_velocity:：モータの動作速度[rad/sec]
- default_acceleration:：モータの動作加速度[rad/sec^2]
- default_torque:：モータの最大トルク[Nm]
- report_hz：モータの現在地を配信する周期[Hz]
- nearly_zero_vel：target_vel_pose実行時、0とみなす速度[rad/sec]
- nearly_target_pose：target_vel_pose実行時、到達とみなす目標との差分[rad]
- max_duration：target_vel_pose実行時、回転継続をタイムアウトするまでの期間[sec]

※各パラメータの順番は対応させる必要があります


## 起動方法
- ROS2ワークスペース（`$GUARDIAN_ROBOT_PATH/ros2_ws`）にて以下のコマンドを実行することで起動する。
  ```
  source install/setup.bash
  ros2 launch keigan_motor keigan_motor_launch.py
  ```
- ノードは`/$ROBOT_NAME`名前空間で起動する（環境変数`ROBOT_NAME`が必要）。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/keigan_motor/joints|sensor_msgs/JointState|モータの名称、角度、角速度、トルク値を一定周期で配信|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/keigan_motor/goal_pose|sensor_msgs/JointState|モータごとの角度制御コマンド(目標角度指定)|
|/$ROBOT_NAME/keigan_motor/relative_goal_pose|sensor_msgs/JointState|モータごとの角度制御コマンド(相対角度指定)|
|/$ROBOT_NAME/keigan_motor/target_velocity|sensor_msgs/JointState|モータごとの角速度制御コマンド|
|/$ROBOT_NAME/keigan_motor/target_vel_pose|sensor_msgs/JointState|モータごとの角速度・角度制御コマンド|
|/$ROBOT_NAME/keigan_motor/set_velocity|keigan_grp_msgs/JointData|モータのデフォルトの動作速度設定コマンド|
|/$ROBOT_NAME/keigan_motor/set_acceleration|keigan_grp_msgs/JointData|モータのデフォルトの動作加速度設定コマンド|
|/$ROBOT_NAME/keigan_motor/set_torque|keigan_grp_msgs/JointData|モータの最大トルク設定コマンド|
|/$ROBOT_NAME/keigan_motor/reset_offset|std_msgs/String|モータの角度リセットコマンド|
|/$ROBOT_NAME/keigan_motor/stop_move|std_msgs/String|モータの動作停止コマンド|


### 操作方法
- 角度指令(目標角度指定)
  - モータごとに指定した目標角度まで移動する。
  - モータごとに速度を指定しなかった場合、デフォルトのモータ動作速度で動作する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/goal_pose sensor_msgs/msg/JointState "header:
    stamp:
        sec: 0
        nanosec: 0
    frame_id: ''
    name: [joint_name1, joint_name2]
    position: [-1.57, 1.57]
    velocity: [1.0, 0.5]        # optional
    effort: []"
    ```

- 角度指令(相対角度指定)
  - モータごとに指定した相対角度まで移動する。
  - モータごとに速度を指定しなかった場合、デフォルトのモータ動作速度で動作する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/relative_goal_pose sensor_msgs/msg/JointState "header:
    stamp:
        sec: 0
        nanosec: 0
    frame_id: ''
    name: [joint_name1, joint_name2]
    position: [-1.57, 1.57]
    velocity: [1.0, 0.5]        # optional
    effort: []"
    ```

- 角速度指令
  - モータごとに指定した角速度で動作する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/target_velocity sensor_msgs/msg/JointState "header:
    stamp:
        sec: 0
        nanosec: 0
    frame_id: ''
    name: [joint_name1, joint_name2]
    position: []
    velocity: [1.0, 1.5]
    effort: []"
    ```

- 角度指令(速度自動調節)
  - モータごとに指定した目標角度まで、速度を制御して移動する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/target_vel_pose sensor_msgs/msg/JointState "header:
    stamp:
        sec: 0
        nanosec: 0
    frame_id: ''
    name: [joint_name1, joint_name2]
    position: [10.0, 5.0]
    velocity: []
    effort: []"
    ```

- デフォルト動作速度設定
  - モータのデフォルトの動作速度を設定値に変更する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/set_velocity keigan_grp_msgs/msg/JointData "joint_name: 'joint_name'
    data: 0.5"
    ``` 

- デフォルト動作加速度設定
  - モータのデフォルトの動作加速度を設定値に変更する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/set_acceleration keigan_grp_msgs/msg/JointData "joint_name: 'joint_name'
    data: 0.5"
    ```

- 最大トルク値設定
  - モータの最大トルクを設定値に変更する。
    ```
    ros2 topic pub -1 /$ROBOT_NAME/keigan_motor/set_torque keigan_grp_msgs/msg/JointData "joint_name: 'joint_name'
    data: 0.5"
    ```

- モータ角度リセット
  - 指定したモータの現在の角度を0[rad]とする。
    ```
    ros2 topic pub /$ROBOT_NAME/keigan_motor/reset_offset std_msgs/msg/String "data: 'joint_name'"
    ```

- モータ動作停止
  - 指定したモータの動作をストップする。
    ```
    ros2 topic pub /$ROBOT_NAME/keigan_motor/stop_move std_msgs/msg/String "data: 'joint_name'"
    ```
