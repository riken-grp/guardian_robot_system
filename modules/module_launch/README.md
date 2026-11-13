# Module Launch

## 概要
機能ごとにtmuxセッションを開いて、機能を起動するためのスクリプトのセットです。
- 以下のコマンドによってenableフォルダ内に格納された機能（スクリプト）が一括起動されます。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/module_launch.sh
  ```
  - enableフォルダ内のスクリプトがファイル名順でソートされて起動します。
- 各tmuxセッションごとに1つのlaunchファイルが実行されるようになっています。
  - セッション内で起動しているノードが1つでも停止したら、tmuxセッションが終了するようになっています。
  - デバッグの際は、セッションが落ちてエラーメッセージを確認できないため、個別のターミナルでlaunchを実行することを推奨します。
- 起動している機能(tmuxセッション)の一覧は以下のスクリプトによって確認できます。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/check_sessions.sh
  ```
- 起動した機能は以下のスクリプトで停止できます（詳細は「[機能の一括停止方法](#機能の一括停止方法)」を参照）。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/kill_sessions.sh
  ```
- ロボット搭載マシン（`ON_ROBOT=1`）では、module_launch.sh の最後にレスキューモード監視（tmuxセッション`00_hv_watch`）も起動します（[rescue_mode/README.md](rescue_mode/README.md)を参照）。

## マシンごとのセッティング方法
1. module_launchディレクトリはリポジトリ内（`$GUARDIAN_ROBOT_PATH/modules/module_launch`）のものを、ホームディレクトリへのシンボリックリンク経由で使用します（tools/binも同様に`~/bin`へリンクします）。  
   どのマシンでも、ホームディレクトリで`module_launch/module_launch.sh`のように起動できます。  
   ※コピーはしないでください。各スクリプトはリポジトリ内の`enable`を参照するため、コピー先の`enable`は使われません。
   ```
   ln -s $GUARDIAN_ROBOT_PATH/modules/module_launch ~/
   ln -s $GUARDIAN_ROBOT_PATH/tools/bin ~/bin
   ```
2. デフォルトではavailableフォルダ内に基本的な起動スクリプトが配置されています。  
   その中からマシンごとに一括起動したいスクリプトのシンボリックリンクを、以下のようにenableフォルダに作成してください（コピーはしないでください）。  
   ※ availableフォルダ内のスクリプトはリポジトリ管理対象のため、移動はしないでください。enableフォルダ内のスクリプトはgit管理対象外です。
   ```
   cd ~/module_launch/enable
   ln -s ../available/02_indyXe_map.sh .
   ```
   ※ マシンごとの標準の組み合わせ（登録するコマンド）は、`docs/手順書`の各マシンの構築手順書の「起動スクリプトの準備」に記載しています。  
   ※ `00_hv_watch`はavailableに無く、登録は不要です（`ON_ROBOT=1`の場合、module_launch.sh実行時に自動で起動されます）。
3. module_launch.sh / scenario_launch.sh 等は guardian_robot_system のパス、ロボット名、MongoDBの接続先などを環境変数から取得します。  
   リポジトリ直下の`indy.env.sample`を`~/indy.env`にコピーして編集し、`~/.bashrc`で読み込んでください（必須の変数が未設定の場合、スクリプトはエラー終了します）。
   ```
   cp <guardian_robot_systemのパス>/indy.env.sample ~/indy.env
   # ~/indy.env を編集したうえで、~/.bashrc に以下を追記
   source ~/indy.env
   ```
   主な環境変数は以下のとおりです（詳細は`indy.env.sample`のコメントを参照）。
   ```
   export ON_ROBOT=<1 or 空>          # ロボット搭載マシンは1。1の場合のみ module_launch.sh が 00_hv_watch を起動する
   export GUARDIAN_ROBOT_PATH=<guardian_robot_systemディレクトリのPATH>
   export ROBOT_NAME=<ロボット名>     # scenario_launch.sh、各launchファイル等で使用
   export SCENARIO_ROBOTS="<ロボット名> ..."  # 任意。scenario_launch.sh の対象ロボット(空白区切り)。未設定時は ROBOT_NAME
   export MONGO_URI=<MongoDBのホスト名 or IPアドレス>
   export MONGO_PORT=<MongoDBのポート番号>
   export ROS_DOMAIN_ID=<ROS_DOMAIN_ID>       # 000_zenoh_bridge.sh で必須
   export ZENOH_MODE=<listen or connect>     # 任意。000_zenoh_bridge.sh の役割。未設定時は ON_ROBOT=1 なら listen(待ち受け側)、それ以外は connect(接続側)。robodj は listen
   export ZENOH_ROBOT_ADDR=<ロボットのIPアドレス>  # 000_zenoh_bridge.sh を接続側(connect)で使う場合に必須
   export ZENOH_LISTEN=<待ち受けIPアドレス>   # 任意。待ち受け側(listen)。空なら全インタフェース
   export ZENOH_PORT=<ポート番号>             # 任意。空なら 7447
   ```

## 使用方法
### 機能の一括起動方法
- 各マシンにて、以下のシェルスクリプトを実行してください。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/module_launch.sh
  ```
### シナリオの起動方法
- シナリオ起動マシンにて、以下のシェルスクリプトを実行してください。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/scenario_launch.sh
  ```
### 機能の一括停止方法
- 以下のシェルスクリプトを実行してください。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/kill_sessions.sh
  ```
  - `00_hv_watch`セッションがあれば、先にCtrl+Cを送って停止します。
  - `enable/*.sh`に対応する各セッションと、`scenario_manager`セッションにCtrl+Cを送ります。
  - 最後に`tools/bin/50_cancel_all.py`を実行し、MongoDB上の待機中・実行中（status が waiting / is_playing）のアクションを canceled にします（接続先は環境変数 MONGO_URI、MONGO_PORT）。
### 機能の個別の起動方法
- 以下のコマンドにて対象機能起動用のシェルスクリプトを実行してください。  
  MongoDBの接続先は以下のいずれかの方法で指定できます。
  ```
  # 環境変数を使用する場合、引数不要
  $GUARDIAN_ROBOT_PATH/modules/module_launch/enable(or available)/--.sh

  # 引数で設定する場合
  $GUARDIAN_ROBOT_PATH/modules/module_launch/enable(or available)/--.sh <MONGO_URI> <MONGO_PORT>
  ```

## 機能ごとの起動スクリプトの設定
以下の形式で起動用シェルスクリプトが用意されています。  
例）available/02_indyXe_rover_base.sh
```
#!/bin/bash

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

# MongoDBの接続先は引数、無ければ環境変数から取得する
MONGO_URI=${1:-$MONGO_URI}
MONGO_PORT=${2:-$MONGO_PORT}

: "${MONGO_URI:?MONGO_URI is not set. e.g. export MONGO_URI=<hostname>}"
: "${MONGO_PORT:?MONGO_PORT is not set. e.g. export MONGO_PORT=9110}"

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                    ros2 launch rover_tools rover_base.launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi
```
- ROSパッケージは `$GUARDIAN_ROBOT_PATH/ros2_ws` のビルド結果（install/setup.bash）を読み込んで起動します。
- tmuxのセッション名はファイル名（.shを除いた部分まで）になっています。
- MongoDBの接続先は引数（`$1`、`$2`）、無ければ環境変数（MONGO_URI、MONGO_PORT）から取得します。
- tmux new -d -sから始まる行の""内で起動するlaunchファイルを指定しています。
- 機能によっては起動後安定するまでsleepを入れています。


## 起動スクリプト一覧

※マシンごとの構成(どのマシンでどのスクリプトを使うか、標準で`enable`に登録するか)は、[docs/仕様書/Indyソフトウェア仕様書.md](../../docs/仕様書/Indyソフトウェア仕様書.md)の「1. ソフトウェア構成」を参照してください。

|スクリプト名|launch|概要|
|---|---|---|
|000_zenoh_bridge.sh|-|zenoh-bridge-ros2ddsを常駐起動する。|
|00_charge_quiet.sh|tools/bin/50_quiet_when_charging.sh|1分ごとに充電状況を取得し、充電状態に応じて音量の設定を行う。<br>充電中の場合は、音量を「5％」に設定する。<br>充電中ではない場合は、音量を「20％」に設定する。|
|00_indyXe_network_log.sh|network_check_launch.py|ネットワーク接続状況を監視し、以下の情報をデータベースに記録する。<br>・ロボット名<br>・ホスト名<br>・ネットワーク接続状況<br>・WiFi信号強度<br>・WiFi信号アクセスポイント名<br>・ロボットの位置<br>・ロボットの姿勢|
|01_indyXe_rover_sense.sh|rover_sense.launch.py|ローバ付近の機器を起動する。<br>・lidar_nav_launch.py（足元のLiDAR）<br>・rs_camera_nav_launch.py（足元のRealSense）<br>・vel_filter.launch.py（障害物回避機能）|
|02_indyXe_map.sh|map_grp_space.launch.py|通常マップとkeepoutマップを読み込み、ROSトピックとして配信する。|
|02_indyXe_rover_base.sh|rover_base.launch.py|ローバの基本的な機能を起動する。<br>・amr_ros_driver.launch.py（ローバ制御の基本的な動作機能）<br>・rover_wrapper.launch.py（ローバ制御の補助的な動作機能）<br>・amr_description.launch.py（ロボットの形状情報(URDF)の生成機能）<br>・auto_charge.launch.py（自動充電機能）<br>・battery_log_launch.py（バッテリー状態の記録機能）<br>・laserscan_multi_merger_launch.py（二つのLiDARのLaserScanの統合機能）|
|03_indyXe_slam_toolbox.sh|rover_slam.launch.py|ナビゲーション機能を起動する。<br>・localization_launch.py（自己位置推定機能）<br>・navigation_launch.py（ナビゲーション機能）|
|04_indyXe_robot_base.sh|robot_base.launch.py|眼と腕、首の関節の制御機能を起動する。<br>・eye_control.launch.py（眼球モニタの制御機能）<br>・arm_bringup.launch.py（腕用モータの制御機能）<br>・motor_control.launch.py（首用モータの制御機能）|
|05_indyXe_microphone_array.sh|microphone_array.launch.py|マイクの音声取得ノードを起動する。<br>※10_indyXe_mic2sock_16ch.shとは同時に起動できない（どちらか一方のみenableに入れる）。|
|10_indyXe_mic2sock_16ch.sh|-|マイクとスピーカーを用いて音声を送受信するRust製のリアルタイム音声通信プロジェクトを実行する。<br>※05_indyXe_microphone_array.shとは同時に起動できない（どちらか一方のみenableに入れる）。|
|10_indyXe_robot_sense.sh|robot_sense.launch.py|頭部、胸付近の機器を起動する。<br>・lidar_ht_launch.py（胸元のLiDAR）<br>・rs_camera_recog_launch.py（頭部のRealSense）|
|10_indyXe_send_audio_server.sh|pa_send_audio_server.sh|pa_send_audio_serverを起動し監視する。<br>終了した場合は、再起動する。|
|20_grs_action_eye.sh|eye_launch.py|MongoDBに登録された目の表情指示（画像ファイル、表示時間）を読み取り、ROS2トピック経由で左右の目の画像を切り替える機能を起動する。|
|20_grs_action_gesture.sh|gestures_modes_ac_launch.py|Indyのジェスチャーを管理・実行するためのROS2 Actionベースのシステムを起動する。|
|20_grs_action_nav.sh|nav_smr_launch.py|MongoDBに登録された移動命令を読み取り、ローバへ実行指示を出す。<br>その進行状況・エラー・バッテリー・位置情報を定期的にMongoDBとROSトピックに送信する機能を起動する。|
|20_grs_action_ros_command.sh|ros_command_launch.py|MongoDBに登録されたROSコマンドを監視し、指定されたトピックへメッセージを送信する機能を起動する。|
|20_grs_action_tts.sh|tts_launch.py|MongoDBに登録された発話指示を取得し、音声合成して再生する機能を起動する。|
|20_grs_action_watchdog.sh|ros_watchdog_launch.py|ROS上の発話・音声認識・バッテリー情報を監視し、その内容のMongoDBへの記録や、バッテリー状態に応じたイベント発行を行う機能を実行する。|
|30_chat_monitor.sh|getData.js|MongoDBに保存された発話データをWebブラウザへ配信するためのWebサーバを起動する。<br>MongoDBの接続先は引数、無ければ環境変数（MONGO_URI、MONGO_PORT）から取得する。|
|50_grsrv_asr.sh|all_asr_launch.py|音声認識機能を起動する。<br>・asr_launch.py（音声認識(文字起こし)機能）<br>・asr_metadata_launch.py（音声認識補助(話し手情報、位置情報)機能）|
|50_grsrv_db_management.sh|db_management.launch.py|認識結果やセンサ情報のMongoDBへの保存、監視・集計を行う機能を起動する。|
|50_grsrv_human_tracker.sh|human_tracker.launch.py|LiDARとカメラのセンサー情報を統合し、人間を検出・追跡・識別し、その位置と方向をROS 2上で可視化・配信する機能を起動する。|
|50_grsrv_llm_responder.sh|llm_responder_launch.py|人の発話に対してLLMで返答を考える機能を起動する。|
|50_grsrv_memory.sh|all_memory_launch.py|履歴(記憶)機能を起動する。<br>・memory_node_launch.py（履歴(記憶)の書き込み機能）|
|50_grsrv_recognition.sh|recognition.launch.py|カメラ画像を使った認識AI機能をまとめて起動する。|
|50_grsrv_ros_asr.sh|ssl_bringup ssl_server.launch.py|asr_nodeを起動する。<br>recog/ssl/identified_speech_segmentsで受け取った音声区間を音声認識し、認識結果を recog/ssl/asr/raw_text に出力する。|
|50_grsrv_vad_for_camera.sh|at_for_outside_camera.launch.py|話し手の情報、位置、音量、発話状態などをトピックとして配信する機能を起動する。|
|60_robodj_chat_monitor.sh|getData.js|robodj用。MongoDBに保存された発話データをWebブラウザへ配信するためのWebサーバを起動する。|
|60_robodj_sensors.sh|sensors.launch.py|robodj用。RealSenseカメラを起動する(ROBOT_NAME=robodj)。|
|60_robodj_tts_djken.sh|tts_launch.py|robodj用。djkenの音声合成ノードを起動する(左チャンネル)。|
|60_robodj_tts_djri.sh|tts_launch.py|robodj用。djriの音声合成ノードを起動する(右チャンネル)。|
|60_robodj_watchdog_djken.sh|ros_watchdog_launch.py|robodj用。djkenのロボット状態(会話、動作、バッテリー)を監視・記録する。|
|60_robodj_watchdog_djri.sh|ros_watchdog_launch.py|robodj用。djriのロボット状態(会話、動作、バッテリー)を監視・記録する。|
|60_robodj_watchdog_robodj.sh|ros_watchdog_launch.py|robodj用。robodjのロボット状態(会話、動作、バッテリー)を監視・記録する。|
