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
|30_indyxe_viewer|ロボットの状態表示・操作画面(Webページ)<br>カメラ、バッテリー、シナリオの状態、地図、聞き取った言葉、行動の表示と、移動・発話の操作|indyxe_viewer|main.py|任意|

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
|MongoDB|サーバマシン上のMongoDB(Docker)に接続する。MongoDBは2種類ある。<br>・設定DB(全ロボット共通、既定のポート9100): シナリオマネージャと、ロボット側の一部のモジュール(pyindyの`load_robot_settings`を使うもの)が、`RISM_CONFIG_HOST`、`RISM_CONFIG_PORT`(未設定の場合は`MONGO_URI`、9100)で接続する。<br>・ロボットDB(ロボットごと、既定のポートはロボットN台目が9100+10×N): 各マシンが`MONGO_URI`、`MONGO_PORT`で接続する。シナリオマネージャは、設定DBに書かれた接続先で接続する。<br>MongoDBはレプリカセットとして動作する。Web UI(構築時に選択した場合)は、MongoDBのポート番号+1で開く。|
|時刻同期|サーバマシンがNTPサーバ(chrony)となり、他のマシンはサーバマシンに時刻同期する。|

別のマシン(rviz用のマシンなど)からROSトピックにアクセスする場合の設定は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「4.1. マシン間のROS通信(zenoh)」を参照すること。

## 3. MongoDBのデータ構成

MongoDBは、全ロボット共通の設定DBと、ロボットごとのロボットDBの2種類がある。  
構築手順は、[サーバマシン構築.md](../手順書/サーバマシン構築.md)の「5. MongoDBの構築」を参照すること。

|MongoDB|既定のポート|主なDatabase|内容|
|---|---|---|---|
|設定DB|9100|`rism_configs`|シナリオマネージャの設定、ロボットごとの設定、デモごとの設定、全ロボット共通の設定(「3.2. シナリオ関連のコレクション」)|
|ロボットDB|9100+10×N(ロボットN台目。1台目は9110)|`robot_config`|各モジュールのパラメータ(「3.1. パラメータ」)|
|||`demo_configs`|シナリオ(「3.2. シナリオ関連のコレクション」)|
|||`tBlackBoard`|観測、ロボットへの動作指示、実行中の状態など|
|||`memory_settings`|LLMのプロンプトなど|
|||`persona`|姿勢(ジェスチャー)の定義、音声の設定|

Web UI(構築時に選択した場合)は、MongoDBのポート番号+1で開く([Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.1. MongoDBでのパラメータ設定」参照)。

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

シナリオマネージャ(`modules/scenario_manager/rism2`)が読み書きするコレクションを以下に示す。  
シナリオマネージャは、起動時に設定DBの`rism_configs`を読み、そこに書かれた接続先からシナリオ(`demo_configs`)を読み、ロボットDBの`tBlackBoard`を通じてロボットに動作を指示する。  
シナリオの追加手順は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.2. 新規シナリオの追加」を参照すること。  
詳細は、rism2の以下の文書を参照すること。

|文書|内容|
|---|---|
|[SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)|シナリオの書き方(フィールド、条件、イベント、動作、Event Generator)|
|[CONFIG.md](../../modules/scenario_manager/rism2/docs/CONFIG.md)|設定(`rism_config`)の全項目・型・既定値、`robot_list`、`demo_list`、`common`|
|[OBSERVATIONS.md](../../modules/scenario_manager/rism2/docs/OBSERVATIONS.md)|観測イベントの形(ロボット側が`physical_topic`に書くもの)|
|[ARCHITECTURE.md](../../modules/scenario_manager/rism2/docs/ARCHITECTURE.md)|しくみ(処理の流れ、読み書きするDB、割り込みの決まり、`current_state`)|
|[ACTION_DB_VERSION_ROUTING.md](../../modules/scenario_manager/rism2/docs/ACTION_DB_VERSION_ROUTING.md)|`Actions`のv1.0/v2.0の形|

※旧シナリオマネージャ(rism)が使っていたロボットDBの`rism_configs`/`scenarios`、`interruption_subscenarios`、`interaction_subscenarios`は使用しない。  
※シナリオ切り替え用のWeb UI(`modules/indy_modules/scenario_switchboard`)を使うと、ロボットDBの`demo_configs`/`scenarios`、`interruption_subscenarios`の`status`(`active`/`inactive`)を一覧から切り替えられる。起動方法は[README](../../modules/indy_modules/scenario_switchboard/README.md)を参照。

#### rism_configs/rism_config(設定DB)

シナリオマネージャ全体の設定。1つのDocumentに書く。  
主な項目を以下に示す。全項目・既定値は[CONFIG.md](../../modules/scenario_manager/rism2/docs/CONFIG.md)を参照すること。  
書いていない項目には既定値が使われる。知らない項目や型の違う値は、起動時に`[Settings]`の警告としてログに出る。

|フィールド名|概要|
|---|---|
|interruption_probability|割り込みを発動させる確率(0〜1)。サブシナリオの`interruption_probability`が優先|
|use_change_streams|観測をChange Streamsで受け取るフラグ<br>(`true`: Change Streams、`false`: ポーリング)|
|default_navigation_interrupt_mode|移動中に割り込んだときの移動の扱い(`parallel`、`suspend_and_resume`、`wait_completion`)|
|executor|動作の完了待ちの時間[秒](`default_timeout`、`default_utterance_timeout`、`default_navigation_timeout`など)|
|prefetch|次のLLM発話を先に生成する設定(`enabled`、`wait_timeout`)|
|error_recovery|動作が失敗したときのリトライ回数・間隔|
|timezone|時刻の扱い(`mode`: `system`または`explicit`、`explicit`: `mode`が`explicit`の場合のタイムゾーン(e.g. `Asia/Tokyo`))|

#### rism_configs/robot_list(設定DB)

ロボットごとの設定。ロボットごとに1つのDocumentを書く(`robot_id`がキー)。  
シナリオマネージャが読む項目と、ロボット側のモジュールが読む項目がある。

|フィールド名|概要|
|---|---|
|_id|DocumentのID|
|robot_id|ロボットのID(`ROBOT_NAME`、`SCENARIO_ROBOTS`に指定する名前)|
|name_alias|ロボットの表示名|
|action_db|動作指示を書くDB(`host`、`port`、`dbname`(`tBlackBoard`)、`version`(`1.0`、`2.0`。省略時は`2.0`。標準の構築では`1.0`))。動作指示は`dbname`の`Actions`コレクションに書く|
|physical_topic、cyber_topic|観測を読むDB(`host`、`port`)。省略時は`demo_list`の`host`、`port`|
|internalstate_db|内部状態と`current_state`を書くDB(`host`、`port`、`dbname`)|
|llm|発話の生成に使うLLM(`url`、`model`、`system_prompt`、`defaults`(`temperature`など)、`log_db`)|
|google_asr|Google音声認識の中継サーバ(`NumASR`、`ServerConf`、`AliveMesgInterval`)。ロボット側が読む|
|asr_target_angle|音声認識に使う音源の角度の範囲[度]。ロボット側(db_management)が読む|
|ignore_non_looking|ロボットを見ていない人の音声認識を登録しないフラグ。ロボット側(db_management)が読む|
|recognition_available_regions|認識してよい範囲(省略時はすべて)。ロボット側(db_management)が読む|

※ロボット側のモジュールは、pyindyの`load_robot_settings`で、`robot_list`の`ROBOT_NAME`のDocumentと`common`を読む。

#### rism_configs/demo_list(設定DB)

デモごとの設定。デモごとに1つのDocumentを書く(`demo_id`がキー)。シナリオを読むDBを指定する。

|フィールド名|概要|
|---|---|
|_id|DocumentのID|
|demo_id|デモID(`SCENARIO_DEMO`に指定する名前。既定は`<ロボット名>_demo`)|
|host、port|シナリオを読むDB(ロボットDB)のホスト名、ポート番号|
|db_name|シナリオを読むDatabase名(`demo_configs`)|
|version|形式のバージョン(`2.0`)|

※`host`、`port`、`db_name`は、`scenario_db`(`host`、`port`、`db_name`)に書いて上書きすることもできる。  
※`SCENARIO_DEMO`のデモIDが`demo_list`に無い場合は、設定DBの、デモIDと同じ名前のDatabaseからシナリオを読もうとする。デモIDと`demo_list`を一致させること。

#### rism_configs/common(設定DB)

全ロボット共通の設定。1つのDocumentに書く。ロボット側(db_managementの天気の登録)が読む。

|フィールド名|概要|
|---|---|
|city|天気を取得する場所(e.g. `Kyoto,JP`)|
|language|天気の言語|
|openweathermap_token|OpenWeatherMapのAPIキー|

#### demo_configs/scenarios(ロボットDB)

メインシナリオ群。  
シナリオ起動中、`status`が`active`で`condition`に合うシナリオから、`priority`を重みにして次に実行するシナリオを選び、`events`を先頭から順に実行する。  
シナリオを選ぶたびにDBから読み込むため、追加・変更はシナリオマネージャを再起動しなくても反映される。

|フィールド名|概要|
|---|---|
|_id|シナリオID|
|name|シナリオ名(必須)|
|status|`active`: 自動で選ばれる、`inactive`: 自動では選ばれない(`next_scenarios`、`include`からは実行できる)(必須)|
|version|形式のバージョン(`"2.0"`)|
|priority|シナリオの優先度(0〜1000の整数。既定は1)。大きいほど選ばれやすい(100と1なら100:1の割合)|
|condition|シナリオが選ばれる条件(観測イベント名をキーにした辞書)<br>空の場合は常に候補となる。|
|events|実行するイベントの配列(必須。「3.3. eventsフィールド」参照)|
|next_scenarios|次に実行するシナリオIDの配列。要素を配列にすると、その中から選ぶ<br>空の場合は、`condition`と`priority`で選ぶ。|
|ignore_interruptions|本シナリオの実行中は発動させないサブシナリオIDの配列|
|exit_condition|本シナリオを打ち切る条件(条件、または条件の配列。配列の場合はどれか1つに合えば打ち切る)|
|exit_events|`exit_condition`で打ち切ったときに実行するイベントの配列(または、観測イベント名ごとのイベントの配列)|

※シナリオID、サブシナリオIDは、参照先のDocumentの`_id`(24桁の16進数の文字列)を記載する。  
※`condition`の書き方(e.g. `{"asr": {"text": {"$regex": "さようなら|またね"}}}`)、使える演算子、観測イベント名は、[SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)を参照すること。

#### demo_configs/interruption_subscenarios(ロボットDB)

割り込みサブシナリオ群。`condition`に合う観測が来たら、実行中のシナリオに割り込んで実行する。  
変更を検知して読み直すため、追加・変更はシナリオマネージャを再起動しなくても反映される。  
`demo_configs/scenarios`のフィールド(`_id`、`name`、`status`、`version`、`priority`、`events`、`next_scenarios`、`ignore_interruptions`、`exit_condition`、`exit_events`)に加え、以下のフィールドを持つ。

|フィールド名|概要|
|---|---|
|condition|サブシナリオの発動条件(必須)|
|priority|同時に条件が合ったときの選ばれやすさと、割り込みの実行順(大きいほど優先)|
|resume_after|終了後の戻り方<br>(`resume`: 元のシナリオの続きから(既定)、`terminate`: 元のシナリオを終えて`next_scenarios`へ、`next_event`: 割り込まれたイベントの残りを飛ばして次のイベントから、`restart`: 割り込まれたイベントをやり直す)|
|important|重要フラグ<br>(`true`: 移動中でもナビゲーションを止めて実行し、`interruption_probability`にかかわらず必ず発動する)|
|force_interrupt|旧形式。`important`と同じ意味として読む|
|navigation_interrupt_mode|移動中の扱い(`parallel`: 移動を続ける、`suspend_and_resume`: 移動を止め、終了後に送り直す、`wait_completion`: 移動の終了を待つ)|
|navigation_wait_timeout|`wait_completion`で移動の終了を待つ時間[秒]|
|ignore_after_activated|発動後のクールタイム[秒]|
|interruption_probability|発動させる確率(0〜1)。省略時は`rism_config`の`interruption_probability`|
|ignore_same_observations|発動したとき、まとめて届いた同じ観測の残りも使用済みにするフラグ<br>(`true`: 同じまとまりで何度も発動しない、`false`: 既定)|
|tags|内部状態による優先度の調整に使うタグの配列|

#### demo_configs/knowledge(ロボットDB)

KnowledgeEventGenerator(登録した知識だけを使ってLLMが答える発話生成)が使う知識。

|フィールド名|概要|
|---|---|
|_id|知識ID|
|title|知識の名前|
|keywords|キーワードの配列。聞いた発話にキーワードが含まれる知識を使う|
|text|知識の内容|
|status|`active`: 使う、`inactive`: 使わない|

#### tBlackBoard/Actions(ロボットDB)

シナリオマネージャからロボットへの動作指示と、その履歴。  
シナリオ起動中、`status`が`waiting`の動作指示が書き込まれ、ロボット側が順に実行して`status`を更新する。  
以下は`action_db.version`が`1.0`の場合(標準の構築)の形である(`2.0`の場合は`command`の代わりに`name`を使い、`inserted`、`last_update`は無い)。

|フィールド名|概要|
|---|---|
|_id|アクションID|
|actor|アクションを実行するロボット(`robot_list`の`robot_id`)|
|condition|アクション実行条件|
|status|アクション実行状態(`waiting`、`is_playing`、`done`、`failed`、`canceled`など)|
|command|アクションコマンド(`speak`、`gesture`、`navigation`、`eye`、`ros_command`、`observation`など)<br>`observation`は、シナリオが観測(返事など)を待っている間の印である。|
|option|アクション内容(動作内容、発話内容など)|
|inserted|ドキュメント追加日時|
|last_update|ドキュメント最終更新日時|

#### tBlackBoard/current_state(ロボットDB)

シナリオマネージャの実行中の状態。1つのDocument(`_id`: `current_state_singleton`)を随時更新する。  
各フィールドの詳細は、[ARCHITECTURE.md](../../modules/scenario_manager/rism2/docs/ARCHITECTURE.md)の「current_state」を参照すること。

|フィールド名|概要|
|---|---|
|interpreter|シナリオマネージャの状態(`status`: `running`、`interrupted`、`idle`など)|
|scenario|実行中のシナリオ(`id`、`name`、`status`)|
|event|実行中のイベント(`index`、`type`)|
|actors|ロボットごとの状態(`name`、`status`: `running`、`waiting`)|
|interrupt|割り込みの状態(`is_interrupted`、`depth`、`subscenario_id`、`subscenario_name`)|
|processing|処理中のフラグ(`is_tts_processing`、`is_llm_generating`、`is_asr_waiting`、`is_navigating`、`is_prefetching`)|
|internal_state|内部状態(`stress_level`など)|
|waiting|現在の待ち(観測待ち、動作の完了待ちなど)のリスト。待っていなければ空|
|last_wait|直近に終わった待ちとその結果|
|last_updated|最終更新日時(UTC)|

※実行したシナリオの履歴は、`tBlackBoard/scenario_history`に書き込まれる。

#### persona/ActionPrimitives(ロボットDB)

Indyの姿勢群の定義。

|フィールド名|概要|
|---|---|
|_id|アクションプリミティブID|
|name|アクションプリミティブ名|
|option|姿勢制御パラメータ(頭、体、腕など)|

### 3.3. eventsフィールド

eventsフィールドは複数のイベントオブジェクトの配列であり、先頭から順に実行される。  
イベントオブジェクト内の主なフィールドについて以下に示す。  
全フィールドと、`wait_for`などの制御用のイベント、発話生成(Event Generator)の詳細は、[SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)の「イベント」「Event Generator」を参照すること。

- actor  
  動作を実行するロボットを設定する(e.g. robot1)。  
  `robot1`、`robot2`、…は、シナリオ起動時に指定したロボット(`SCENARIO_ROBOTS`または`ROBOT_NAME`)に、指定した順に対応する。

- type  
  イベントの種類を設定する。主な種類を以下に示す。
  - `action`: ロボットに動作させる(`speak`、`gesture`、`eye`、`navigation`、`ros_command`をまとめて実行し、すべて終わるまで待つ)
  - `wait_for`: 観測(音声認識など)を待つ。来たら`success`、来なければ`failure`のイベントを実行する
  - `if`: 観測を待って分岐する(`true`、`false`、`failure`)
  - `until`: 条件に合う観測が来るまで`loop`を繰り返す
  - `repeat`、`random`、`shuffle`: 繰り返し、ランダムに1つ選択、順番をシャッフルしてすべて実行
  - `include`: 指定したシナリオ・サブシナリオ(`scenario`にIDを記載)のイベントを、その場で実行する
  - `scenario_exit`: シナリオを終える
  - `suspend_navigation`: 実行中の移動を止める
  - `face_person`: 体を人の方へ回す

- speak  
  発話情報を設定する。`{"type": ..., "option": {...}}`の形で書く。  
  - type: 発話の種類(`normal`: `option.text`を発話、`blank`: `option.text`の`{変数}`を埋めて発話、`generate`: `option.generator`で発話を生成(LLMなど)、`file`: 音声ファイルを再生)
  - option.text: 発話内容
  - option.generator、option.prompt: `generate`の場合の生成方法(e.g. `LlmJPEventGenerator`、`TemplateEventGenerator`)とLLMへの指示

- gesture  
  動作情報を設定する。`{"type": "normal", "option": {...}}`の形で書く。  
  - option.command: 動作内容
    - persona/ActionPrimitivesコレクションの中から適した動作を選択し、nameフィールドの値を記載する。  
  - option.duration: 動作時間[秒]

- eye  
  目の表示を設定する(e.g. `{"type": "normal", "image": "smile.jpg", "duration": 2}`)。

- navigation  
  目標位置・目標角度情報を設定する。`{"type": "normal", "option": {...}}`の形で書く。  
  optionには、以下のいずれか1つを設定する。  
  - navigation: 指定位置への移動。先頭から順に、「x座標」「y座標」「向き」
    - x座標・y座標  
      メートル単位で、原点からの絶対位置を設定する(e.g. 1.0、-5.0)。
    - 向き  
      ラジアン単位で、原点からの絶対角度を設定する(e.g. 1.0、-2.0)。
  - destination: 地点名を指定した移動
  - rotate: その場での回転。ラジアン単位で設定する(e.g. 3.14)。
  - move: 直進(後退)。メートル単位で設定する(e.g. 0.2)。
  - dock: `true`で充電ステーションに入る。充電が始まれば完了となる。

- ros_command  
  送信するROSコマンド情報を設定する。`{"type": "normal", "topic": ..., "topic_type": ..., "data": ...}`の形で書く。  
  - topic: 送信先のトピック名(`<ロボット名>`は実際のロボット名に置き換える)  
  - topic_type: メッセージ型(e.g. `std_msgs/msg/String`)  
  - data: 送信データ(`std_msgs/msg/Int32`の場合は整数)

- interruptable  
  イベント実行中に検知した割り込みの扱いを設定する。  
  (`true`: イベントの実行中に割り込みを実行する(既定)、`false`: 割り込みを後で実行する。`important`のサブシナリオは本イベントの完了直後、それ以外は次の`interruptable`が`true`のイベントで実行する)

- ignore_interruptions  
  本イベントの実行中は発動させないサブシナリオIDの配列を設定する。
