# eye_display
ロボットの目（ディスプレイ）に画像を表示する。

## 起動方法
- 片目のみ起動する場合  
  ```
  ros2 launch eye_display eye_display_launch.py \
      serial_port:=<serial_port> \
      node_id:=<node_id> \
      default_target_file:=<default_target_file> \
      report_hz:=<report_hz> \
      baudrate:=<baudrate> \
      log_level:=<log_level>
  ```
  - report_hz：タイマーコールバックの実行周期[Hz]。（デフォルト値：`1`）
  - baudrate：シリアル通信のボーレート。（デフォルト値：`115200`）
  - sirial_port：`/dev/ttyClientA`(右目)または`/dev/ttyClientB`(左目)。（デフォルト値：`/dev/ttyUSB0`） 
  - node_id：`right`(右目)または`left`(左目)。（デフォルト値：`not_set`）
  - default_target_file：起動時に表示する画像ファイル名。（デフォルト値：`neutral2.jpg`）
  - config_file：起動設定yamlファイルのパス。（デフォルト値：`''`）
  - log_level：ログレベル（DEBUG|INFO|WARN|ERROR|FATAL）。（デフォルト値：`info`）

- 両目を起動する場合
  ```
  ros2 launch eye_display two_eyes_display_launch.py
  ```

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|eye_display_node/(node_id)/displayed_file|std_msgs/String|表示中の画像ファイル名|
|eye_display_node/(node_id)/butukusa|common_msgs/StringStamped|受信したトピック情報（表示する画像ファイル名、画面クリア指令）|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|eye_display_node/(node_id)/target_file|std_msgs/String|表示する画像ファイル名|
|eye_display_node/(node_id)/clear_display|std_msgs/Empty|画面クリア指令|

