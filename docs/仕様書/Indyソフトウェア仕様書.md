# Indyソフトウェア仕様書

## 1. ソフトウェア構成

各システム(Indy、robodj)で使用するマシンについては、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「1. 概要」を参照すること。  
各マシンのソフトウェアの構成(起動スクリプトの一覧)を以下に示す。  
「enable登録」列は、各マシンの構築手順書の「起動スクリプトの準備」で一括起動の対象(`enable`フォルダ)に登録するかを示す。  
○: 標準で登録する、任意: 必要な場合のみ登録する、不要(自動起動): 登録しなくても自動で起動される

### ① ロボット搭載マシン

|セッション名|概要|パッケージ|launch|enable登録|
|---|---|---|---|---|
|000_zenoh_bridge|zenoh-bridge-ros2dds|-|-|○|
|00_hv_watch|常駐監視<br>※起動スクリプトは無く、module_launch.sh実行時に自動で起動される(ON_ROBOT=1の場合のみ)。|-|-|不要(自動起動)|
|00_charge_quiet|充電状態に応じた音量制御|-|-|○|
|00_indyXe_network_log|ネットワーク接続状態監視|network_check|network_check_launch.py|○|
|01_indyXe_rover_sense|以下の機器と機能を起動<br>・ローバ用LiDAR<br>・ローバ用RealSense<br>・障害物回避機能|rover_tools|rover_sense.launch.py|○|
|02_indyXe_map|map生成|world|map_grp_space.launch.py|○|
|02_indyXe_rover_base|ローバ基本動作制御|rover_tools|rover_base.launch.py|○|
|03_indyXe_slam_toolbox|ナビゲーション機能起動|rover_tools|rover_slam.launch.py|○|
|04_indyXe_robot_base|以下の機器を起動<br>・眼球モニタ<br>・腕用モータ<br>・首用モータ|rover_tools|robot_base.launch.py|○|
|05_indyXe_microphone_array|マイク音声取得<br>※10_indyXe_mic2sock_16chとは同時に起動できない。どちらか一方のみ使用すること。|microphone_array|microphone_array.launch.py|任意|
|10_indyXe_mic2sock_16ch|マイク・スピーカーによるリアルタイム音声通信(mic2sock)<br>※05_indyXe_microphone_arrayとは同時に起動できない。どちらか一方のみ使用すること。|-|-|任意|
|10_indyXe_robot_sense|以下の機器を起動<br>・胸用LiDAR<br>・頭部用RealSense|rover_tools|robot_sense.launch.py|○|
|10_indyXe_send_audio_server|スピーカー出力音声の配信(pa_send_audio_server)<br>終了した場合は自動で再起動する。|-|pa_send_audio_server.sh|任意|
|20_grs_action_eye|眼球映像操作|robot|eye_launch.py|○|
|20_grs_action_gesture|ジェスチャー制御|gestures_modes|gestures_modes_ac_launch.py|○|
|20_grs_action_nav|ナビゲーション操作|robot|nav_smr_launch.py|○|
|20_grs_action_ros_command|ROSコマンド操作|robot|ros_command_launch.py|○|
|20_grs_action_tts|tts操作|robot|tts_launch.py|○|
|20_grs_action_watchdog|Watchdog|robot|ros_watchdog_launch.py|○|
|30_chat_monitor|会話ログ配信(HTTP API)|chat-bubble|getData.js|○|

※ローバのドライバ(amr_ros_driver。02_indyXe_rover_baseで起動)は、本リポジトリにソースコードが含まれない。ノード名とROSのインターフェースは、別紙[amr_ros_driver仕様書.md](amr_ros_driver仕様書.md)を参照すること。

### ② サーバマシン

|セッション名|概要|パッケージ|launch|enable登録|
|---|---|---|---|---|
|000_zenoh_bridge|zenoh-bridge-ros2dds|-|-|○|
|50_grsrv_asr|音声認識(関連機能を複数起動)|asr|all_asr_launch.py|○|
|50_grsrv_db_management|データベース管理|db_management|db_management.launch.py|○|
|50_grsrv_human_tracker|人物検出・追跡|human_tracker|human_tracker.launch.py|○|
|50_grsrv_llm_responder|対話生成|llm_responder|llm_responder_launch.py|○|
|50_grsrv_memory|履歴管理|memory|all_memory_launch.py|○|
|50_grsrv_recognition|画像認識|scene_understanding|recognition.launch.py|○|
|50_grsrv_ros_asr|音声認識(単体起動)|ssl_bringup|ssl_server.launch.py|任意|
|50_grsrv_vad_for_camera|話者情報(位置、音量、発話状態など)の配信|human_tracker|at_for_outside_camera.launch.py|任意|

### ③ robodj

robodjは、Indyとは別のロボットシステム(2台のロボットによる会話システム)である。Indyを動かすだけであれば不要。

|セッション名|概要|パッケージ|launch|enable登録|
|---|---|---|---|---|
|000_zenoh_bridge|zenoh-bridge-ros2dds(待ち受け側。`ZENOH_MODE=listen`)<br>※別のマシンからrobodjのROSトピックにアクセスする場合のみ。|-|-|任意|
|60_robodj_chat_monitor|会話ログ配信(HTTP API)|chat-bubble|getData.js|○|
|60_robodj_sensors|RealSenseカメラ設定|scene_understanding|sensors.launch.py|○|
|60_robodj_tts_djken|音声合成ノード起動(djken)|robot|tts_launch.py|○|
|60_robodj_tts_djri|音声合成ノード起動(djri)|robot|tts_launch.py|○|
|60_robodj_watchdog_djken|ロボット状態(会話、動作、バッテリー)監視・記録(djken)|robot|ros_watchdog_launch.py|○|
|60_robodj_watchdog_djri|ロボット状態(会話、動作、バッテリー)監視・記録(djri)|robot|ros_watchdog_launch.py|○|
|60_robodj_watchdog_robodj|ロボット状態(会話、動作、バッテリー)監視・記録(robodj)|robot|ros_watchdog_launch.py|○|

※音声合成用ソフトウェアサーバ(AITalk)の起動スクリプトは本リポジトリに含まれない。  
※robodjの構築・起動手順は[docs/手順書/robodj構築.md](../手順書/robodj構築.md)を参照。

## 2. マシン間の通信

|通信|方式|
|---|---|
|ROS|各マシンのROSの通信はマシン内に限定し(`CYCLONEDDS_URI`で読み込むcyclonedds.xml)、マシン間はzenoh-bridge-ros2ddsで中継する。<br>ロボット搭載マシン、robodjは待ち受け側、サーバマシンは接続側。|
|MongoDB|サーバマシン上のMongoDB(Docker)に、各マシンが`MONGO_URI`、`MONGO_PORT`で接続する。|
|時刻同期|サーバマシンがNTPサーバ(chrony)となり、他のマシンはサーバマシンに時刻同期する。|

別のマシン(rviz用のマシンなど)からROSトピックにアクセスする場合の設定は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「4.1. マシン間のROS通信(zenoh)」を参照すること。

## 3. MongoDBのデータ構成

### 3.1. パラメータ
`robot_config.system_parameters`の各Documentと、それを読み込むモジュール(パッケージ)の対応を以下に示す。  
設定可能なパラメータについては、各モジュールのREADME参照。  
変更手順は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.1. MongoDBでのパラメータ設定」を参照すること。

|Document(`name`の値)|読み込むモジュール|
|---|---|
|asr|asr|
|gestures_modes|gestures_modes、robot(ジェスチャー制御)|
|human_tracker|human_tracker|
|llm_responder|llm_responder|
|map_server|world(地図の配信)|
|memory|memory|
|ros_audio_tracker|audio_publisher、human_tracker|
|sensor_tf|sensor_tf_publisher|

### 3.2. シナリオ関連のコレクション

シナリオの追加手順は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.2. 新規シナリオの追加」を参照すること。

#### rism_configs/scenarios

Indyの基本的なデモシナリオ群。   
シナリオ起動中、status: activeのシナリオをランダムで読み込み、tBlackBoard/Actionsコレクションに順に書き込む。

|フィールド名|概要|
|---|---|
|_id|シナリオID|
|name|シナリオ名|
|status|`active`: ランダム実行対象、`inactive`: ランダム実行対象外|
|priority|シナリオの優先度|
|trigger|シナリオの発火条件(手を挙げる、話しかけられるなど)<br>空の場合は常に実行対象となる。|
|interaction_subscenario_ids|次にランダムに実行するサブシナリオ(rism_configs/interaction_subscenarios)のIDの配列|
|ignore_after_activated|シナリオ実行後のクールタイム|
|ignore_same_observations|同じ観測データの再利用フラグ<br>(`true`: 再利用禁止、`false`: 再利用可能)|
|'return'|本シナリオ終了後に、元々実行していたシナリオに戻るフラグ<br>(`true`: 戻る、`false`: 戻らない)|
|events|実行するアクション|
|next_scenarios|次に実行するシナリオIDの配列<br>※`'return'`が`false`の場合のみ有効|

#### rism_configs/interruption_subscenarios

triggerを受けて開始するシナリオ群。

|フィールド名|概要|
|---|---|
|_id|サブシナリオID|
|name|サブシナリオ名|
|priority|シナリオの優先度|
|status|`active`: 有効、`inactive`: 無効|
|trigger|シナリオの発火条件(手を挙げる、話しかけられるなど)|
|ignore_after_activated|シナリオ実行後のクールタイム|
|save_trigger_contents_values|トリガーになった観測データ|
|interaction_subscenario_ids|次にランダムに実行するサブシナリオIDの配列|
|force_interrupt|現在のアクションを停止して本シナリオを実行するフラグ<br>(`true`: 実行する、`false`: 実行しない)|
|'return'|本シナリオ終了後に、元々実行していたシナリオに戻るフラグ<br>(`true`: 戻る、`false`: 戻らない)|
|ignore_same_observations|同じ観測データの再利用フラグ<br>(`true`: 再利用禁止、`false`: 再利用可能)|
|events|実行するアクション|
|next_scenarios|次に実行するシナリオIDの配列<br>※`'return'`が`false`の場合のみ有効|
|important|重要フラグ<br>(`true`: 重要(割り込み時優先)、`false`: 重要ではない)|

#### rism_configs/interaction_subscenarios

シナリオ実行中に、`interaction_subscenario_ids`で指定されて実行されるサブシナリオ群。

|フィールド名|概要|
|---|---|
|_id|サブシナリオID|
|name|サブシナリオ名|
|status|`active`: 有効、`inactive`: 無効|
|priority|シナリオの優先度|
|trigger|シナリオの発火条件|
|save_trigger_contents_values|トリガーになった観測データ|
|'return'|本シナリオ終了後に、元々実行していたシナリオに戻るフラグ<br>(`true`: 戻る、`false`: 戻らない)|
|events|実行するアクション|
|next_scenarios|次に実行するシナリオIDの配列<br>※`'return'`が`false`の場合のみ有効|

#### tBlackBoard/Actions

Indyが実行したデモシナリオ動作の履歴。  
シナリオ起動中、status: waitingのcommandが書き込まれ、順に実行される。

|フィールド名|概要|
|---|---|
|_id|アクションID|
|actor|アクションを実行するロボット|
|condition|アクション実行条件(none、block scenario manager)|
|status|アクション実行状態(waiting、done、canceledなど)|
|command|アクションコマンド(gesture、speakなど)|
|option|アクション内容(動作内容、発話内容など)|
|inserted|ドキュメント追加日時|
|last_update|ドキュメント最終更新日時|

#### persona/ActionPrimitives

Indyの姿勢群の定義。

|フィールド名|概要|
|---|---|
|_id|アクションプリミティブID|
|name|アクションプリミティブ名|
|option|姿勢制御パラメータ(頭、体、腕など)|

### 3.3. eventsフィールド

eventsフィールドは複数のイベントオブジェクトの配列であり、先頭から順に実行される。  
イベントオブジェクト内の各フィールドについて以下に示す。

- actor  
  動作を実行するロボットを設定する(e.g. robot1)。  
  `robot1`、`robot2`、…は、シナリオ起動時に指定したロボット(`SCENARIO_ROBOTS`または`ROBOT_NAME`)に、指定した順に対応する。

- type  
  イベントの種類を設定する。  
  - `action`: ロボットに動作させる
  - `observation`: 観測(音声認識など)を待つ

- utterance  
  発話情報を設定する。  
  - type: 発話の種類(`normal`: sentenceを発話、`file`: fileを再生)
  - sentence: 発話内容
  - file: 再生する音声ファイル(typeが`file`の場合)

- gesture  
  動作情報を設定する。  
  - command: 動作内容
    - persona/ActionPrimitivesコレクションの中から適した動作を選択し、nameフィールドの値を記載する。  
  - duration: 動作時間[秒]

- navigation  
  目標位置・目標角度情報を設定する。  
  以下のいずれか1つを設定する。  
  - navigation: 指定位置への移動。先頭から順に、「x座標」「y座標」「向き」
    - x座標・y座標  
      メートル単位で、原点からの絶対位置を設定する(e.g. 1.0、-5.0)。
    - 向き  
      ラジアン単位で、原点からの絶対角度を設定する(e.g. 1.0、-2.0)。
  - rotate: その場での回転。ラジアン単位で設定する(e.g. 3.14)。
  - move: 直進(後退)。メートル単位で設定する(e.g. 0.2)。

- ros_command  
  送信するROSコマンド情報を設定する。  
  - topic: 送信先のトピック名(`<ロボット名>`は実際のロボット名に置き換える)  
  - topic_type: メッセージ型(e.g. `std_msgs/msg/String`)  
  - data: 送信データ

- interruptable  
  割り込みイベントが発生した場合のevent中断許可フラグを設定する。  
  (`true`: 割り込みイベントによる中断を許可、`false`: 完了まで中断しない)  
