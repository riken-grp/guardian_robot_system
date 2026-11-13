# amr_ros_driver仕様書

## 1. 概要

amr_ros_driverは、ローバ(AMRメイン基板)を制御するROS 2ドライバである。  
`rover/cmd_vel`を受け取ってローバを動かし、オドメトリ、バンパ、バッテリーなどのローバの状態を配信する。

- 本リポジトリにはamr_ros_driverのソースコードは含まれず、deb形式で提供されるビルド済みのパッケージ(版数1.0.0)を使用する。
  - `ros-humble-amr-msgs`(amr_msgs)、`ros-humble-amr-ros-driver`(amr_ros_driver)の2つで、どちらも`/opt/ros/humble`にインストールされる。
  - ソース版のamr_ros_driver・amr_msgsをビルドしたワークスペースを`source`していると、ワークスペース側が優先され、deb版は使われない。`ros2 pkg prefix amr_ros_driver`で`/opt/ros/humble`と表示されることを確認すること。
- 本書は、ROSのインターフェース(ノード名、トピック、パラメータ、メッセージ型)を記載する。

## 2. 起動方法

ロボット搭載マシンの起動スクリプト`02_indyXe_rover_base`(rover_toolsの`rover_base.launch.py`)から、以下のlaunchファイルで起動される。

```
ros2 launch amr_ros_driver amr_ros_driver.launch.py
```

|項目|内容|
|---|---|
|ノード名|`/<ロボット名>/amr_ros_driver`(名前空間は環境変数`ROBOT_NAME`)|
|launch引数|`cmd_vel`: 速度指令を受け取るトピック名(既定値: `rover/cmd_vel`)<br>※`rover_base.launch.py`からは`rover/cmd_vel_filtered`(障害物回避の速度フィルタ通過後の速度指令)が指定される。|
|設定ファイル|`/opt/ros/humble/share/amr_ros_driver/config/amr_ros_driver.yaml`(場所は変更できない。「4. パラメータ」参照)|

※起動ファイルは`amr_ros_driver.launch.py`のみ(`amr_ros_driver.launch.xml`は含まれない)。  
※`ROBOT_NAME`が未設定の場合は、`error: failed to get robot name`を出力し、起動しない。

起動すると、ログに`amr_ros_driver version: 1.0.0`が出力される。主なエラーは以下のとおり。  
※ノードが異常終了しても`ros2 launch`の終了コードは0になるため、成否はログで確認すること。

|ログ|原因・対処|
|---|---|
|`Error: not open usb device: <device_path>`|シリアルポートを開けない。`device_path`とメイン基板の接続を確認する。|
|`Error: required parameters are not set: <パラメータ名>`|設定ファイルに必須のパラメータが無い(「4. パラメータ」参照)。|

## 3. トピック

トピック名は、いずれも`/<ロボット名>/`からの相対名である。

### 3.1. Publish

|トピック名|型|QoS|概要|
|---|---|---|---|
|rover/odom|nav_msgs/msg/Odometry|Reliable|オドメトリ|
|rover/bumper|std_msgs/msg/UInt8|Reliable|バンパのラッチ状態(ビットごと。bit0: 前方接触、bit1: 後方接触)<br>0: 接触なし、1: 前方、2: 後方、3: 前後とも<br>`rover/bumper_clear`でクリアするまで保持される。|
|rover/bumper_current|std_msgs/msg/UInt8|Reliable|バンパの現在の状態(値の意味は`rover/bumper`と同じ)|
|rover/emr_status|std_msgs/msg/UInt8|Reliable|緊急停止の原因(ビットごと。bit0: HARDWARE、bit1: SOFTWARE)<br>0の場合は緊急停止していない。|
|rover/firm_state|std_msgs/msg/UInt8|Best Effort|ファームウェアの状態(0: INIT、1: RUN、2: STOP、3: CHARGE(未使用)、4: EMERGENCY、5: SHUTDOWN、9: ERROR)|
|rover/firm_err|std_msgs/msg/UInt8|Best Effort|ファームウェアのエラー(ビットごと。bit0: TIMEOUT_CONTROL、bit1: TIMEOUT_SUB_BOARD、bit2: TIMEOUT_MOTOR、bit3: TIMEOUT_BATTERY)<br>0の場合はエラーなし。|
|rover/shutdown|std_msgs/msg/UInt8|Reliable|シャットダウン指令|
|rover/battery|sensor_msgs/msg/BatteryState|Best Effort|バッテリー全体の情報<br>全バッテリーの値を平均し、`percentage`、`current`、`voltage`に設定する。|
|rover/battery_individual|amr_msgs/msg/BatteryArray|Best Effort|バッテリーごとの情報(「6. メッセージ型(amr_msgs)」参照)|
|rover/driver_ver|std_msgs/msg/String|Reliable、Transient Local|amr_ros_driverの版数(e.g. `1.0.0`)<br>起動時に1回配信する。Transient Localのため、起動後に購読を始めても受け取れる。<br>確認例: `ros2 topic echo --once --qos-durability transient_local /<ロボット名>/rover/driver_ver`|

※QoSの履歴の深さは、いずれも1。

### 3.2. Subscribe

|トピック名|型|概要|
|---|---|---|
|rover/cmd_vel|geometry_msgs/msg/Twist|速度指令(`linear.x`、`angular.z`を使用)<br>※launch引数`cmd_vel`で受け取るトピック名を変更できる。<br>※最後の受信から1.0秒を超えて指令が無い場合、モータの回転数指令を0にする(停止する)。|
|rover/bumper_clear|std_msgs/msg/UInt8|バンパのクリア指令(1: クリアする、0: クリアを解除する)<br>0、1以外の値は無視される。|
|rover/motor_release|std_msgs/msg/UInt8|モータのリリース(タイヤの解放)指令(1: リリースする、0: リリースを解除する)<br>0、1以外の値は無視される。|

### 3.3. TF

|親フレーム|子フレーム|概要|
|---|---|---|
|`<ロボット名>_odom`|`<ロボット名>_base_footprint`|オドメトリ(最大30Hzで配信)|

※フレーム名は、パラメータ`odom_frame_id`、`odom_chil_frame_id`の値の前に`<ロボット名>_`を付けたものになる。`rover/odom`の`header.frame_id`、`child_frame_id`も同じ。

## 4. パラメータ

設定値は、設定ファイル`/opt/ros/humble/share/amr_ros_driver/config/amr_ros_driver.yaml`の値である。

### 4.1. パラメータの変更方法

1. 以下のコマンドを実行し、設定ファイルを編集する。
   ```
   sudoedit /opt/ros/humble/share/amr_ros_driver/config/amr_ros_driver.yaml
   ```

2. 02_indyXe_rover_baseを再起動し、設定を反映する。

注意:
- **deb(ros-humble-amr-ros-driver)を更新・再インストールすると、設定ファイルは提供時の内容に戻る。** 機体に合わせて変更した場合は、編集後の内容の控えを別に残しておくこと。
- 設定は`/**:`の下に記載する。ノード名・名前空間によらず適用される。
- 以下の必須パラメータが無い場合、シリアルポートを開く前に`Error: required parameters are not set: <パラメータ名>`を出力して終了する。  
  `device_path`、`robot_model_type`、`wheel_size`、`vehicle_tread`、`gear_ratio`、`encoder_resolution`、`gpio_set`、`gpio_output_ini`(`robot_model_type`が`mecanum`の場合は`robot_width`、`robot_length`も)

### 4.2. パラメータ一覧

|パラメータ名|設定値|概要|
|---|---|---|
|show_ctrl_cmd|false|基板へ送信する制御コマンドのログ表示|
|show_gpio_cmd|false|基板へ送信するGPIOコマンドのログ表示|
|show_led_cmd|false|基板へ送信するLEDコマンドのログ表示|
|show_motor_info|false|基板から受信したモータ情報のログ表示|
|show_board_info|false|基板から受信した基板情報のログ表示|
|show_battery_info|false|基板から受信したバッテリー情報のログ表示|
|show_firmware_info|false|基板から受信したファームウェア情報のログ表示|
|show_charging_station_info|false|基板から受信した充電ステーション情報のログ表示|
|device_path|"/dev/main_board"|基板と通信するシリアルポート|
|robot_model_type|"differential"|駆動方式("differential": 差動二輪、"mecanum": メカナムホイール)|
|robot_width|0.8|ロボットの幅[m]。mecanumの場合のみ使用|
|robot_length|1.0|ロボットの長さ[m]。mecanumの場合のみ使用|
|exist_ir_board|true|IR基板の有無|
|main_loop_rate|1000.0|メインループの周期[Hz]|
|gpio_set|0x0008|GPIOの入出力設定(1: 出力、0: 入力)<br>※`ros2 param`で変更しないこと。|
|gpio_output_ini|0x00FF|GPIO出力の初期値(1: HIGH、0: LOW)|
|wheel_size|0.150|車輪の直径[m]|
|vehicle_tread|0.4|トレッド[m]|
|gear_ratio|20.0|ギア比|
|encoder_resolution|36000|エンコーダの分解能[pulse/rev]|
|odom_frame_id|"odom"|オドメトリの親フレーム名(先頭に`<ロボット名>_`が付く)|
|odom_chil_frame_id|"base_footprint"|オドメトリの子フレーム名(先頭に`<ロボット名>_`が付く)|
|pose_covariance|[0.001, 0.001, 1000000.0, 1000000.0, 1000000.0, 1.0]|`rover/odom`の位置・姿勢の共分散(x、y、z、roll、pitch、yaw)|
|twist_covariance|[0.001, 0.001, 1000000.0, 1000000.0, 1000000.0, 1.0]|`rover/odom`の速度の共分散(x、y、z、roll、pitch、yaw)|
|front_frame_id / rear_frame_id|"front_sonar" / "rear_sonar"|ソナーのフレーム名(現在、ソナーのトピックは配信していない)|
|front_fov / rear_fov|20.0|ソナーの視野角[deg]|
|front_min_range / rear_min_range|0.1|ソナーの最小距離[m]|
|front_max_range / rear_max_range|1.0|ソナーの最大距離[m]|

## 5. 動作

- 基板への制御コマンドは50ms周期で送信する。
- `rover/cmd_vel`を最後に受信してから1.0秒を超えると、モータの回転数指令を0にする。
- `rover/battery`は、全バッテリーの情報がそろった時点で、その平均値を配信する。

## 6. メッセージ型(amr_msgs)

### amr_msgs/msg/BatteryArray

|フィールド|型|概要|
|---|---|---|
|battery|amr_msgs/msg/Battery[]|バッテリーごとの情報|

### amr_msgs/msg/Battery

|フィールド|型|単位|概要|
|---|---|---|---|
|soc|uint8|%|充電率|
|soh|uint8|%|劣化状態|
|cur|int16|10mA|電流(負の値は充電中)|
|cycle|uint16|回|充放電サイクル数|
|vol|uint16|mV|電圧|

### amr_msgs/msg/LedCommand

現在、amr_ros_driverでは使用していない(LEDコマンドのトピックは受信していない)。

```
uint8 OFF=0x00
uint8 ON=0x02
uint8 BLINK=0x03
uint8 FLASH=0x04
uint8 AUTO=0xF0

uint8 cmd
uint32 color
uint8 on_duty
uint16 period
```
