# robodj構築手順

> **注意**  
> robodjは、サーバマシン上のMongoDBに接続して動作する。  
> 本手順の「6. MongoDBの準備」で、サーバマシン上にrobodj用のMongoDBを構築すること(「3. 環境変数設定」の`MONGO_URI`、`MONGO_PORT`には、そのMongoDBの値を使用する)。

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
   |MONGO_URI|robodj用MongoDBのホスト名またはIPアドレス<br>※サーバマシンのmongo.envの`MONGO_PUBLIC_HOST`と同じ値にする。|
   |MONGO_PORT|robodj用MongoDBのポート番号<br>※サーバマシンのmongo.envの`MONGO_PORT`と同じ値にする。|
   |ROS_DOMAIN_ID|ROS_DOMAIN_ID|
   |ZENOH_MODE|`listen`(zenohを使用する場合のみ)<br>※robodjは待ち受け側として起動する。`ZENOH_ROBOT_ADDR`は設定不要。|
   |DEEPL_API_KEY|DeepLのAPIキー(chat_monitorで自動翻訳を使う場合のみ)|

   ※`RMW_IMPLEMENTATION`、`CYCLONEDDS_URI`はサンプルの値から変更しないこと。  
   　サンプルの`CYCLONEDDS_URI`は、ROSの通信をマシン内に限定する設定である。

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

robodj用のMongoDBを、サーバマシン上に構築する。  
以下の作業は**サーバマシン**で実施する。

### 6.1. MongoDBの起動

robodjのためにサーバマシンを新しく構築する場合、[サーバマシン構築.md](サーバマシン構築.md)のうち必要な章は以下のみである(6章以降は不要)。  
既にIndy用にサーバマシンを構築済みの場合は、手順1から実施する。

|章|実施内容|
|---|---|
|1. 時刻同期設定(NTPサーバ)|すべて実施する。|
|2. Avahi設定|`MONGO_URI`などに`<ホスト名>.local`を使用する場合のみ実施する。|
|3. ソフトウェアの準備|すべて実施する。|
|4. 環境変数設定|~/indy.envは`GUARDIAN_ROBOT_PATH`、`MONGO_URI`、`MONGO_PORT`のみ設定すればよい。<br>`MONGO_URI`、`MONGO_PORT`には、robodj用MongoDBの値(mongo.envの`MONGO_PUBLIC_HOST`、`MONGO_PORT`と同じ値)を設定する。<br>※サンプルの値(`xxxx`など)のまま残すと、MongoDBの構築でmongo.envの値より優先されてしまうため、必ず設定すること。|
|5. MongoDBの構築|以下の手順1〜2に従って実施する。|

1. [サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」の手順1〜7を実施し、robodj用のMongoDBを起動する。  
   ※同じサーバマシンで他のロボット用のMongoDBも動かす場合は、ロボットごとにenvファイルとプロジェクト名を分ける。  
   　この場合、mongo.envの代わりにmongo_robodj.envを作成し、手順5の`. ./mongo.env`は`. ./mongo_robodj.env`に読み替える。  
   　`docker compose`のコマンドは、以下のように先頭に`env -u MONGO_PORT`、オプションに`-p robodj --env-file mongo_robodj.env`を付ける。
   ```
   env -u MONGO_PORT docker compose -p robodj --env-file mongo_robodj.env up -d
   ```
   　※~/indy.envを読み込んだシェルでは`MONGO_PORT`が設定されており、envファイルの値より優先されるため、`env -u MONGO_PORT`で外す必要がある。  
   　ポート番号・データの置き場所は他のロボットと重ならないようにすること([setup/mongo_docker/README.md](../../setup/mongo_docker/README.md)の「複数台分を起動する」参照)。

2. データを用意する。  
   既存のrobodj用データベースを移行する場合は「6.2.」、標準データから新しく作る場合は「6.3.」を実施する。

### 6.2. 既存のデータベースを移行する場合

1. [setup/mongo_docker/README.md](../../setup/mongo_docker/README.md)の「既存データの持ち込み」に従い、データを移行する。

2. 既存のデータでは、ロボット名が`dj_ri1`、`dj_ken1`となっている。  
   本手順のロボット名(`dj_ri`、`dj_ken`)に合わせ、MongoDB管理画面(Mongo Express)で以下を書き換える。
   - rism_configs.rism_config の`robot_list`のキー
   - rism_configs.robot_config の`robot_id`
   - 上記以外にロボット名を含むデータ(シナリオ中のトピック名など)

### 6.3. 標準データから作る場合

1. 以下のコマンドを実行し、dj_ri用として標準データを投入する。
   ```
   cd $GUARDIAN_ROBOT_PATH/setup/mongo_docker
   ./import_default_data.sh dj_ri

   # 複数台分を起動している場合
   ./import_default_data.sh -p robodj --env-file mongo_robodj.env dj_ri
   ```

2. サーバマシン構築.mdの「5. MongoDBの構築」の手順9に従い、プレースホルダを書き換える。

3. dj_kenを追加する。  
   標準データは1台分のため、2台目(dj_ken)の設定をMongoDB管理画面(Mongo Express)で追加する。
   1. Databases「rism_configs」→ Collections「rism_config」のDocumentを開く。
   2. `robot_list`の中の`dj_ri`の項目を複製し、キーを`dj_ken`に変更して保存する。
   3. Collections「robot_config」の`robot_id: 'dj_ri'`のDocumentを開き、内容(`_id`を除く)をコピーする。
   4. 「New Document」で新しいDocumentを作成し、コピーした内容を貼り付けて、`robot_id`を`'dj_ken'`、`name_alias`をdj_kenの呼び名に変更して保存する。

   ※`SCENARIO_ROBOTS`に指定したロボットは、`rism_config`の`robot_list`と、`robot_config`の`robot_id`の両方に登録されている必要がある。  
   　どちらかが欠けていると、シナリオ起動時にエラーとなる。

4. 標準データのシナリオは、すべて1台目(`actor: 'robot1'`、dj_ri)用である。  
   dj_ken(`robot2`)を動かすシナリオは、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.2. 新規シナリオの追加」に従い、`actor: 'robot2'`のイベントを持つシナリオを別途作成する。

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
   `SCENARIO_ROBOTS`に設定したdj_ri、dj_kenの2台がシナリオの対象となる。
   ```
   ~/module_launch/scenario_launch.sh
   ```

4. 会話ログは、ブラウザで`http://<robodjのホスト名>:3000/`を開いて確認する。  
   ※ポート番号はchat_monitorの`config_server.js`の`display_port`で変更できる。

5. 終了する場合は、以下のコマンドを実行する。
   ```
   ~/module_launch/kill_sessions.sh
   ```
