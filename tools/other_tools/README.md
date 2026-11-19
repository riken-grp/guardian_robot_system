# ハードウェア設定ツール

ロボットのハードウェアを設定するためのツール。組み立てや部品交換のときに、ロボット搭載マシン上で使う。
通常の運用（起動・終了・操作）では使わない。

|ツール|対象|内容|
|---|---|---|
|`robstride02_tool`|アーム・首のモータ(Robstride02)|ゼロ点の設定、CAN IDの変更、モータの検索・状態表示|
|`set_urg_ip.py`|LiDAR(北陽電機 URG、Ethernet接続)|IPアドレスの変更|

以下、`$GUARDIAN_ROBOT_PATH/tools/other_tools`を`other_tools`と書く。

## robstride02_tool

アームと首のモータ(Robstride02)を、CAN経由で設定する。

### 準備

1. アーム・首を制御するノード(`arm_motor_control`、`motor_control`)を停止する。  
   動いている場合、ツールはエラーを表示して終了する。
2. CANインターフェースが有効になっていることを確認する(「indy_ロボット搭載マシン構築.md」の「5. CANインターフェースの起動時自動設定」参照)。
   ```
   ip link show rightarm
   ```

|CAN I/F|部位|CAN ID(関節)|
|---|---|---|
|`rightarm`|右腕|1(a)、2(b)、3(c)、4(d)|
|`leftarm`|左腕|1(a)、2(b)、3(c)、4(d)|
|`neck`|首・胴体|1(body_pitch)、2(neck_yaw)、3(neck_pitch)|

※CAN IDを省略した場合は、上の表の全関節が対象になる。  
※scan、show、set-zeroは、対象のモータに停止(disable)命令を送る。アームはトルクが抜けて下がるので、手で支えてから実行すること。

### モータの状態を確認する(show)

```
other_tools/robstride02_tool show rightarm
```
各モータの位置[rad]、電圧[V]、温度[℃]を表示する。応答しないモータは「応答なし」と表示される。

### ゼロ点を設定する(set-zero)

モータの現在の位置を、ゼロ点(0 rad)に設定する。モータを交換したときや、関節の位置がずれたときに行う。

|部位|ゼロ点の姿勢|
|---|---|
|右腕・左腕|手のひらを下に向けて、腕を真横に伸ばした姿勢|
|首・胴体|首と胴体を正面に向けて、直立させた姿勢|

1. 部位を上の姿勢にし、手で押さえて保持する。
2. 以下のコマンドを実行する(右腕の例。左腕は`leftarm`、首・胴体は`neck`)。
   ```
   other_tools/robstride02_tool set-zero rightarm
   ```
   一部の関節だけ設定する場合は、CAN IDを指定する(e.g. `set-zero rightarm 3`)。
3. 現在の位置が表示されるので、姿勢を保持したまま`y`を入力する。
4. 「設定後の位置」が0付近になっていれば成功。
5. モータの電源を入れ直し、`show`で位置が保たれていることを確認する。

### CAN IDを変更する(set-id)

```
other_tools/robstride02_tool set-id rightarm <今のID> <新しいID>
```
モータを交換したときなど、新しいモータのCAN IDを上の表に合わせるときに使う。  
※同じCANバスに同じIDのモータが複数あると区別できない。変更するモータだけをCANバスに接続して行うとよい。  
※新しいIDが既に使われている場合は、エラーを表示して終了する。  
※変更後、モータの電源を入れ直し、`scan`で新しいIDが保たれていることを確認する。

### CAN IDを調べる(scan)

```
other_tools/robstride02_tool scan rightarm
```
CAN ID 1〜127で応答するモータを表示する。IDが分からないモータを調べるときに使う。

### ビルド

`robstride02_tool`はビルド済み(Ubuntu 22.04、x86_64)。ソースを変更した場合は、以下でビルドし直す。
```
$GUARDIAN_ROBOT_PATH/ros2_ws/indy/motor_driver/Robstride02/tools/build.sh
```
ソース: `ros2_ws/indy/motor_driver/Robstride02/tools/robstride02_tool.cpp`(ドライバは同じディレクトリの`../src/Robstride02.hpp`)

## set_urg_ip.py

LiDAR(北陽電機 URG、Ethernet接続)のIPアドレスを変更する。

|LiDAR|IPアドレス|設定ファイル|
|---|---|---|
|1台目(前、laser_f)|192.168.4.10|`ros2_ws/indy/rover_system/rover_tools/config/params_ether_1st.yaml`|
|2台目(後、laser_b)|192.168.4.11|`ros2_ws/indy/rover_system/rover_tools/config/params_ether_2nd.yaml`|

1. ロボット搭載マシンから、LiDARの今のIPアドレスに接続できることを確認する(`ping <今のIPアドレス>`)。
2. 以下のコマンドを実行する。
   ```
   other_tools/set_urg_ip.py <新しいIPアドレス> <ゲートウェイ> --ip <今のIPアドレス>
   ```
   e.g. IPアドレスが192.168.0.10のLiDAR(北陽電機の初期値として一般的な値。機種や設定により異なる場合がある)を2台目のアドレスにする場合:
   ```
   other_tools/set_urg_ip.py 192.168.4.11 192.168.4.1 --ip 192.168.0.10
   ```
   ※`--ip`を省略した場合は、192.168.4.10に接続する。ネットマスクは`--nm`で指定する(省略時は255.255.255.0)。
3. 「Done updating, cycle power on laser」と表示されたら、LiDARの電源を入れ直す。
4. 新しいIPアドレスが、上の表の設定ファイルの`ip_address`と一致していることを確認する。

※本スクリプトは urg_node(Unbounded Robotics Inc.、BSDライセンス)に由来する。ファイル冒頭のライセンス表記は削除しないこと。
