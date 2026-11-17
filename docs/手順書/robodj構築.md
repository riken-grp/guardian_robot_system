# robodj構築手順

> **注意**  
> robodjは、サーバマシン上のMongoDBに接続して動作する。  
> 本手順の「6. MongoDBの準備」で、サーバマシン上にrobodj用のMongoDB(ロボットDB)を構築すること(「3. 環境変数設定」の`MONGO_URI`、`MONGO_PORT`には、そのMongoDBの値を使用する)。

robodjは、本リポジトリの機能を使った、Indy(自律対話ロボット)とは別のロボットシステムで、2台のロボット(dj_ri、dj_ken)による会話システムである。  
Indyを動かすだけであれば、本手順は不要である。  
robodjマシンは、2台のロボットの音声合成・状態監視と、RealSenseカメラ、会話ログ配信(chat_monitor)、シナリオ管理を1台で動かす。  
本手順は以下を前提とする。

- OS: Ubuntu 22.04
- ROS 2: humble
- MongoDBは、サーバマシン上でrobodj用に構築する(本手順の「6. MongoDBの準備」参照)。
- robodjのROS通信はrobodj内に限定する。別のマシン(rviz用のマシンなど)からrobodjのROSトピックにアクセスする場合は、zenoh-bridge-ros2ddsを使用する(robodjは待ち受け側)。  
  詳細は[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「4.1. マシン間のROS通信(zenoh)」を参照。

## 1. 基本パッケージ、ROS2のインストール、時刻同期・Avahi設定

[indy_ロボット搭載マシン構築.md](indy_ロボット搭載マシン構築.md)の以下の章を実施する。

- 1. 基本パッケージのインストール
- 2. ROS2のインストール
- 3. zenoh-bridge-ros2ddsのインストール(別のマシンからrobodjのROSトピックにアクセスする場合のみ)
- 4. 時刻同期設定(chrony)(同期先はrobodj用MongoDBを動かすサーバマシン)
- 6. Avahi設定(ネットワークインタフェース名はrobodjで確認したものを設定する)

## 2. ソフトウェアの準備

1. guardian_robot_systemリポジトリ(※guardian_robot_systemリポジトリのパス※)をクローンする。

2. 以下のコマンドを実行し、pyindy(各モジュールが共通で使用するPythonライブラリ)をインストールする。
   ```
   cd <guardian_robot_systemのパス>/modules/pyindy
   pip3 install .
   ```

## 3. 環境変数設定

ビルドや起動スクリプトは環境変数を参照するため、ビルドより先に本設定を行うこと。

1. 以下のコマンドを実行し、guardian_robot_system/indy.env.sampleをコピーして~/indy.envを作成する。
   ```
   cp <guardian_robot_systemのパス>/indy.env.sample ~/indy.env
   ```

2. ~/indy.envを開き、以下の項目をrobodj用に設定する。
   ```
   vi ~/indy.env
   ```

   |変数名|設定値|
   |---|---|
   |ON_ROBOT|空のまま(`1`を設定しないこと)<br>※robodjはロボット搭載マシンではないため、ロボット専用パッケージのビルドとレスキューモード監視(00_hv_watch)の起動は行わない。|
   |GUARDIAN_ROBOT_PATH|guardian_robot_systemリポジトリのパス|
   |ROBOT_NAME|`robodj`|
   |SCENARIO_ROBOTS|`"dj_ri dj_ken"`<br>※シナリオ管理の対象ロボット。シナリオのactorの`robot1`がdj_ri、`robot2`がdj_kenに対応する。|
   |MONGO_URI|robodj用MongoDB(ロボットDB)のホスト名またはIPアドレス<br>※「6. MongoDBの準備」で、サーバマシンのsetup_mongo.shの最後に表示される`MONGO_URI`の値にする。|
   |MONGO_PORT|robodj用MongoDB(ロボットDB)のポート番号<br>※「6. MongoDBの準備」で、サーバマシンのsetup_mongo.shの最後に表示される`MONGO_PORT`の値にする。|
   |RISM_CONFIG_HOST|設定DB(rism_configs)のホスト名(setup_mongo.shの最後に表示された場合のみ。未設定の場合は`MONGO_URI`)|
   |RISM_CONFIG_PORT|設定DBのポート番号(setup_mongo.shの最後に表示された場合のみ。未設定の場合は9100)|
   |SCENARIO_DEMO|シナリオのデモID(設定DBの`demo_list`のキー。未設定の場合は`SCENARIO_ROBOTS`の先頭のロボット名 + `_demo`、すなわち`dj_ri_demo`)<br>※「6. MongoDBの準備」でデモのIDを`dj_ri_demo`以外にした場合のみ設定する。|
   |ROS_DOMAIN_ID|ROS_DOMAIN_ID|
   |ZENOH_MODE|`listen`(zenohを使用する場合のみ)<br>※robodjは待ち受け側として起動する。`ZENOH_ROBOT_ADDR`は設定不要。|
   |DEEPL_API_KEY|DeepLのAPIキー(chat_monitorで自動翻訳を使う場合のみ)|

   ※`RMW_IMPLEMENTATION`、`CYCLONEDDS_URI`はサンプルの値から変更しないこと。  
   　サンプルの`CYCLONEDDS_URI`は、ROSの通信をマシン内に限定する設定である。  
   ※setup_mongo.shの最後には`export ROBOT_NAME=dj_ri`が表示されるが、robodjの`ROBOT_NAME`は`robodj`のままにすること(dj_riはシナリオ管理の対象ロボットとして`SCENARIO_ROBOTS`に指定する)。

3. .bashrcを開き、以下の設定を追加する。
   ```
   vi ~/.bashrc
   ```

   ```
   # ROS2
   
   source /opt/ros/humble/setup.bash
   source ~/indy.env
   if [ -f "$GUARDIAN_ROBOT_PATH/ros2_ws/install/local_setup.bash" ]; then
       source "$GUARDIAN_ROBOT_PATH/ros2_ws/install/local_setup.bash"
   fi
   ```

4. 以下のコマンドを実行して設定を反映し、環境変数が設定されていることを確認する。
   ```
   source ~/.bashrc
   echo $GUARDIAN_ROBOT_PATH $ROBOT_NAME $SCENARIO_ROBOTS $MONGO_URI $MONGO_PORT
   ```

   ※起動スクリプトは、tmuxが起動した時点の環境変数を引き継ぐ。後から~/indy.envを変更した場合は、`~/module_launch/kill_sessions.sh`で全セッションを停止して`tmux kill-server`を実行し、新しいターミナルから起動し直すこと。

## 4. ソフトウェアのビルド

1. 以下のコマンドを実行し、ビルドする。
   ```
   cd $GUARDIAN_ROBOT_PATH/ros2_ws
   colcon build
   ```

2. 以下のコマンドを実行し、ビルド結果を反映する。
   ```
   source ~/.bashrc
   ```

## 5. chat_monitorの準備

会話ログ配信(chat_monitor)はNode.jsで動作する。

1. 以下のコマンドを実行し、Node.js(LTS版)をインストールする。
   ```
   sudo apt install -y nodejs npm
   sudo npm install -g n
   sudo n lts
   sudo apt purge -y nodejs npm
   exec $SHELL -l
   node --version
   ```

2. 以下のコマンドを実行し、chat_monitorが使用するライブラリをインストールする。
   ```
   cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/chat_monitor
   npm install mongodb express deepl-node
   ```

## 6. MongoDBの準備

robodj用のMongoDB(ロボットDB)を、サーバマシン上に構築する。  
以下の作業は**サーバマシン**で実施する。

### 6.1. MongoDBの起動

robodjのためにサーバマシンを新しく構築する場合、[サーバマシン構築.md](サーバマシン構築.md)のうち必要な章は以下のみである(6章以降は不要)。  
既にIndy用にサーバマシンを構築済みの場合は、手順1から実施する。

|章|実施内容|
|---|---|
|1. 時刻同期設定(NTPサーバ)|すべて実施する。|
|2. Avahi設定|`MONGO_URI`などに`<ホスト名>.local`を使用する場合のみ実施する。|
|3. ソフトウェアの準備|すべて実施する。|
|4. 環境変数設定|~/indy.envは`GUARDIAN_ROBOT_PATH`のみ設定すればよい。|
|5. MongoDBの構築|以下の手順1〜4に従って実施する。|

1. [サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」の手順1〜3を実施し、Docker、uvをインストールする(インストール済みの場合は不要)。

2. [サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」の手順4〜5に従い、setup_mongo.shを実行する。  
   ただし、ロボットのIDなどの既定値が`dj_ri`になるよう、以下のように`ROBOT_NAME=dj_ri`を付けて実行する。
   ```
   ROBOT_NAME=dj_ri $GUARDIAN_ROBOT_PATH/setup/mongo_docker/setup_mongo.sh
   ```

   以下の質問は、次のように答える。

   |質問|設定値|
   |---|---|
   |設定DB も新しく作りますか|サーバマシンに設定DBが無い場合は`Y`。<br>既にIndy用にサーバマシンを構築済みで、設定DBがある場合は`n`(robodj用のロボットDBだけを作り、今ある設定DBにrobodjのロボットを追加する)。|
   |今ある設定DB のホスト名|(上で`n`と答えた場合のみ)設定DBのホスト名|
   |ロボットの番号 / ロボットDB のポート|同じサーバの他のロボットとポートが重ならない番号(e.g. Indy用に1を使っている場合は2。ポートの既定値が9120になる)|
   |docker compose ファイルを置くフォルダ|既定値(`setup/mongo_docker/deploy/dj_ri`)のままでよい|
   |ロボットの ID|既定値(`dj_ri`)のままでよい|
   |表示名|dj_riの呼び名|
   |デモの ID|既定値(`dj_ri_demo`)のままでよい(robodjのデモは1つ)|

3. [サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」の手順6〜7に従い、データディレクトリを作成してMongoDBを起動する(`<ロボットID>`は`dj_ri`)。  
   ※設定DBを新しく作っていない場合、`docker compose ps`に表示されるのはmongo-robotのみである。

4. データを用意する。  
   既存のrobodj用データベースを移行する場合は「6.2.」、標準データから新しく作る場合は「6.3.」を実施する。

### 6.2. 既存のデータベースを移行する場合

1. [setup/mongo_docker/README.md](../../setup/mongo_docker/README.md)の「既存データの持ち込み」に従い、データを移行し、`setup_mongo.sh --answers`で設定DBの設定を投入する。

2. 既存のデータでは、ロボット名が`dj_ri1`、`dj_ken1`となっている。  
   本手順のロボット名(`dj_ri`、`dj_ken`)に合わせ、MongoDB管理画面で、ロボット名を含むデータ(トピック名など)を書き換える。  
   ※旧構成の`rism_configs.rism_config`の`robot_list`のキーと、`rism_configs.robot_config`の`robot_id`は、現在のシナリオマネージャ(rism2)では使用しない。ロボットの設定は、設定DBの`rism_configs.robot_list`に、ロボットごとに1つの文書として登録する(「6.3.」の手順3参照)。  
   ※旧構成の`rism_configs.rism_config`に書いていたロボット側の設定(Google音声認識中継サーバ、OpenWeatherMapのAPIキーなど)は、設定DBの`robot_list`、`common`に移す([setup/mongo_docker/README.md](../../setup/mongo_docker/README.md)の「稼働中の旧構成から移行するときの注意」参照)。

3. 旧構成のシナリオ(`rism_configs.scenarios`など)は、rism2では読まない。  
   rism2のシナリオは、ロボットDBの`demo_configs`(`scenarios`、`interruption_subscenarios`、`knowledge`)に置く。書き方は[rism2/docs/SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)を参照。

4. 「6.3.」の手順3に従い、dj_kenを設定DBの`robot_list`に追加する。

### 6.3. 標準データから作る場合

1. [サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」の手順8に従い、設定と標準データを投入する(`<ロボットID>`は`dj_ri`)。

2. サーバマシン構築.mdの「5. MongoDBの構築」の手順9に従い、プレースホルダを書き換える。

3. dj_kenを追加する。  
   setup_mongo.shが設定DBの`robot_list`に登録するのは1台分(dj_ri)のため、2台目(dj_ken)の文書をMongoDB管理画面で追加する。  
   dj_kenは、dj_riと同じロボットDB(robodjの`MONGO_URI`、`MONGO_PORT`)を使う。
   1. 設定DBの管理画面(`http://<設定DBのホスト名>:<設定DBのポート+1>/`)で、Databases「rism_configs」→ Collections「robot_list」の`robot_id: 'dj_ri'`のDocumentを開き、内容(`_id`を除く)をコピーする。
   2. 「New Document」で新しいDocumentを作成し、コピーした内容を貼り付けて、`robot_id`を`'dj_ken'`、`name_alias`をdj_kenの呼び名に変更して保存する。

   ※`SCENARIO_ROBOTS`に指定したロボットは、すべて設定DBの`robot_list`に登録されている必要がある。欠けていると、シナリオ起動時にエラーとなる。  
   ※デモ(設定DBの`demo_list`)は、2台で1つ(`dj_ri_demo`)を使う。dj_ken用のデモは作らない。  
   ※rism2で複数のロボット(dj_ri、dj_ken)を動かす構成は、まだ動作を確認していない。

4. サンプルのシナリオは、すべて1台目(`actor: 'robot1'`、dj_ri)用である。  
   dj_ken(`robot2`)を動かすシナリオは、[rism2/docs/SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)に従い、`actor: 'robot2'`のイベントを持つシナリオを、ロボットDBの`demo_configs.scenarios`に別途作成する。

## 7. 起動スクリプトの準備

1. [indy_ロボット搭載マシン構築.md](indy_ロボット搭載マシン構築.md)の「12. 起動スクリプトの準備」の手順1〜2を実施し、ホームディレクトリにmodule_launch、bin、tmuxの設定ファイルへのシンボリックリンクを作成する。

2. 以下のコマンドを実行し、robodj用の起動スクリプトを一括起動の対象に登録する。
   ```
   cd ~/module_launch/enable
   ln -s ../available/60_robodj_*.sh .
   ls -l
   ```

   ※別のマシンからrobodjのROSトピックにアクセスする場合は、`000_zenoh_bridge.sh`も同様に登録する(「3. 環境変数設定」の`ZENOH_MODE`の設定が必要)。

   登録されるスクリプトは以下の7つ。

   |スクリプト名|概要|
   |---|---|
   |60_robodj_chat_monitor.sh|会話ログ配信(HTTP API)|
   |60_robodj_sensors.sh|RealSenseカメラの起動|
   |60_robodj_tts_djken.sh|音声合成ノードの起動(dj_ken、左チャンネル)|
   |60_robodj_tts_djri.sh|音声合成ノードの起動(dj_ri、右チャンネル)|
   |60_robodj_watchdog_djken.sh|ロボット状態の監視・記録(dj_ken)|
   |60_robodj_watchdog_djri.sh|ロボット状態の監視・記録(dj_ri)|
   |60_robodj_watchdog_robodj.sh|ロボット状態の監視・記録(robodj)|

## 8. 起動・終了

1. 以下のコマンドを実行し、robodjの機能を一括起動する。
   ```
   ~/module_launch/module_launch.sh
   ```

2. 以下のコマンドを実行し、7つのセッションが起動していることを確認する。
   ```
   ~/module_launch/check_sessions.sh
   ```

3. 以下のコマンドを実行し、シナリオを起動する。  
   `SCENARIO_ROBOTS`に設定したdj_ri、dj_kenの2台がシナリオの対象となる(シナリオの`robot1`がdj_ri、`robot2`がdj_ken)。デモは`SCENARIO_DEMO`(未設定の場合は`dj_ri_demo`)を使う。  
   シナリオマネージャ(`modules/scenario_manager/rism2`)は、設定DB(`RISM_CONFIG_HOST`、`RISM_CONFIG_PORT`。未設定の場合は`MONGO_URI`と9100)に接続する。  
   ※シナリオマネージャの起動にはuvが必要である。robodjにuvが無い場合は、先に以下のコマンドでインストールし、新しいターミナルから実行する。初回の起動時に、依存パッケージが自動でインストールされる。
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   ```
   ~/module_launch/scenario_launch.sh
   ```

4. 会話ログは、ブラウザで`http://<robodjのホスト名>:3000/`を開いて確認する。  
   ※ポート番号はchat_monitorの`config_server.js`の`display_port`で変更できる。

5. 終了する場合は、以下のコマンドを実行する。
   ```
   ~/module_launch/kill_sessions.sh
   ```
