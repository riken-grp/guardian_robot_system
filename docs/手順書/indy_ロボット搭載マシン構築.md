# ロボット搭載マシン構築手順

> **注意**  
> ロボット搭載マシンは、サーバマシン上のMongoDBに接続して動作する。  
> 本手順の前に、[サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」を実施し、MongoDBを構築しておくこと。  
> 「9. 環境変数設定」で設定する`MONGO_URI`、`MONGO_PORT`には、構築したMongoDBの値を使用する。

> **一括インストール**  
> 以下のパッケージのインストールは、`setup/robot/install_robot_packages.sh`で一括して実行できる。  
> 「1. 基本パッケージのインストール」、「2. ROS2のインストール」、「3. zenoh-bridge-ros2ddsのインストール」、「4. 時刻同期設定(chrony)」の手順1、「5. mic2sock環境構築」、「6. Avahi設定」の手順1、「8. ソフトウェアの準備」の手順2、「11. chat_monitorの準備」、「12. 起動スクリプトの準備」の手順6、手順7の`uv sync`  
> ```
> sudo apt update
> sudo apt install -y git
> git clone <guardian_robot_systemリポジトリ> <guardian_robot_systemのパス>
> cd <guardian_robot_systemのパス>/setup/robot
> ./install_robot_packages.sh
> ```
> ※sudoできる一般ユーザで実行すること(rootでは実行しない)。  
> ※ROS2、zenohのaptリポジトリが既に設定されている場合(既にROS2が入っているマシンなど)は、鍵とリポジトリの設定を変更せずにそのまま使う。  
> ※実行後、上記以外の手順(4. の手順2〜4、6. の手順2〜5、7.、9.、10.、12. の手順1〜5と手順7の起動スクリプトの登録、13.)を実施すること。  
> ※一部の手順だけを実行する場合は、`./install_robot_packages.sh --help`で手順名を確認し、`./install_robot_packages.sh pyindy check`のように指定する。

## 1. 基本パッケージのインストール

1. 以下のコマンドを実行し、システムを最新の状態に更新する。
   ```
   sudo apt update
   sudo apt upgrade -y
   ```

2. 以下のコマンドを実行し、各種パッケージをインストールする。
   ```
   sudo apt install -y vim
   sudo apt install -y openssh-server 
   sudo apt install -y git
   sudo apt install -y net-tools
   sudo apt install -y tmux
   sudo apt install -y ffmpeg
   sudo apt install -y can-utils
   sudo apt install -y python3-pip python3-dev build-essential libasound2-dev
   ```

## 2. ROS2のインストール

1. 以下のコマンドを実行し、ROS2リポジトリを追加する。
   ```
   sudo apt update && sudo apt install -y curl gnupg lsb-release
   sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(source /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
   ```

2. 以下のコマンドを実行し、ROS2をインストールする。
   ```
   sudo apt update
   sudo apt install -y ros-humble-desktop
   sudo apt install -y ros-dev-tools
   ```

3. 以下のコマンドを実行し、ROS2関連パッケージをインストールする。
   ```
   sudo apt install -y ros-humble-navigation2
   sudo apt install -y ros-humble-image-transport-plugins
   sudo apt install -y ros-humble-xacro
   sudo apt install -y ros-humble-image-proc
   sudo apt install -y ros-humble-rmw-cyclonedds-cpp
   sudo apt install -y ros-humble-urdf-launch
   sudo apt install -y ros-humble-pcl-ros
   sudo apt install -y ros-humble-moveit*
   sudo apt install -y ros-humble-diagnostic-updater
   sudo apt install -y ros-humble-laser-proc
   sudo apt install -y ros-humble-realsense2-camera
   sudo apt install -y ros-humble-slam-toolbox
   sudo apt install -y ros-humble-teleop-twist-keyboard
   ```

4. 以下のコマンドを実行し、Pythonライブラリをインストールする。
   ```
   pip install "numpy==1.24.4" "opencv-python<4.12" open3d
   ```

   ※numpyは`1.24.4`、opencv-pythonは`4.12`未満を指定すること。

## 3. zenoh-bridge-ros2ddsのインストール

ROSの通信はマシン内に限定しているため、サーバマシンなど別のマシンとのROS通信はzenoh-bridge-ros2ddsで中継する。  
別のマシン(rviz用のマシンなど)からROSトピックにアクセスする場合の設定は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「4.1. マシン間のROS通信(zenoh)」を参照。

1. 以下のコマンドを実行し、zenohのaptリポジトリを追加する。
   ```
   sudo mkdir -p /etc/apt/keyrings
   curl -fsSL https://download.eclipse.org/zenoh/debian-repo/zenoh-public-key | sudo gpg --dearmor --yes --output /etc/apt/keyrings/zenoh-public-key.gpg
   echo "deb [signed-by=/etc/apt/keyrings/zenoh-public-key.gpg] https://download.eclipse.org/zenoh/debian-repo/ /" | sudo tee /etc/apt/sources.list.d/zenoh.list > /dev/null
   ```

2. 以下のコマンドを実行し、zenoh-bridge-ros2dds 1.9.0をインストールする。
   ```
   sudo apt update
   sudo apt install -y zenoh-bridge-ros2dds=1.9.0
   sudo apt-mark hold zenoh-bridge-ros2dds
   ```

   ※1.10.0以降はglibc 2.38以上(Ubuntu 24.04以降)が必要なため、Ubuntu 22.04ではインストールできない。  
   　`apt upgrade`で更新されないよう、`apt-mark hold`でバージョンを固定している。

3. 以下のコマンドを実行し、インストールされたことを確認する。
   ```
   zenoh-bridge-ros2dds --version
   ```

## 4. 時刻同期設定(chrony)

ロボット搭載マシンは、サーバマシンをNTPサーバとして時刻同期する(NTPクライアントとして設定する)。  
※先に[サーバマシン構築.md](サーバマシン構築.md)の「1. 時刻同期設定(NTPサーバ)」を実施しておくこと。

1. 以下のコマンドを実行し、chronyをインストールする。
   ```
   sudo apt install -y chrony
   sudo systemctl enable chrony
   ```

2. 以下のコマンドを実行し、設定ファイルのバックアップを作成する。
   ```
   sudo cp -p /etc/chrony/chrony.conf /etc/chrony/chrony.conf.old
   ```

3. /etc/chrony/chrony.confを開き、既存のpool行をコメントアウトして、以下のように同期先(サーバマシン)の設定を追加する。
   ```
   sudo vi /etc/chrony/chrony.conf
   ```

   ```
   #pool ntp.ubuntu.com        iburst maxsources 4
   #pool 0.ubuntu.pool.ntp.org iburst maxsources 1
   #pool 1.ubuntu.pool.ntp.org iburst maxsources 1
   #pool 2.ubuntu.pool.ntp.org iburst maxsources 2
   server 192.168.0.1 iburst
   ```

   ※`server`には、サーバマシンのIPアドレスを設定すること(`192.168.0.1`は例)。

4. 以下のコマンドを実行し、設定を反映して時刻同期状態を確認する。  
   `Reference ID`がサーバマシンのIPアドレスで、`Leap status`が`Normal`であれば正常。
   ```
   sudo systemctl restart chrony
   chronyc tracking
   ```

## 5. mic2sock環境構築

1. 以下のコマンドを実行し、Rust環境を構築する。
   ```
   curl https://sh.rustup.rs -sSf | sh
   sudo apt install -y cargo
   ```

2. 以下のコマンドを実行し、JACK関連ライブラリをインストールする。
   ```
   sudo apt install -y jackd
   sudo apt install -y libjack-jackd2-dev
   ```

## 6. Avahi設定

Avahiにより、同じネットワーク内のマシンを`<ホスト名>.local`で名前解決できるようにする。  
設定するネットワークインタフェースはマシンごとに異なるため、マシンごとに確認して設定すること。

1. 以下のコマンドを実行し、Avahiをインストールする。
   ```
   sudo apt install -y avahi-daemon
   sudo apt install -y avahi-utils
   ```

2. 以下のコマンドを実行し、他のマシンと通信するネットワークインタフェースの名前を確認する。  
   インタフェース名はマシンごとに異なる(e.g. `enp2s0`、`enp0s31f6`、無線LANの場合は`wlp3s0`など)。  
   他のマシンと同じネットワークのIPアドレスが割り当てられているものを選ぶ。
   ```
   ip -br addr
   ```

3. /etc/avahi/avahi-daemon.confを開き、以下の通り設定を編集する。  
   `allow-interfaces`には、手順2で確認したインタフェース名を設定する(`enp2s0`は例)。
   ```
   sudo vi /etc/avahi/avahi-daemon.conf
   ```

   ```
   use-ipv4=yes
   use-ipv6=no
   allow-interfaces=enp2s0
   ```  

4. 以下のコマンドを実行し、設定を反映させる。
   ```
   sudo service avahi-daemon restart
   ```

5. 他のマシンから以下のコマンドを実行し、本マシンのホスト名(`<ホスト名>.local`)でIPアドレスが引けることを確認する。
   ```
   avahi-resolve -n <本マシンのホスト名>.local
   ```

## 7. CANインターフェースの起動時自動設定

1. /etc/rc.localを作成し、以下の内容を記述する。
   ```
   sudo vi /etc/rc.local
   ```

   ```
   #!/bin/bash
   
   # CAN I/F setting
   slcand -o -c -f -s8 /dev/usbcan_rightarm rightarm
   ip link set rightarm up
   slcand -o -c -f -s8 /dev/usbcan_leftarm leftarm
   ip link set leftarm up
   slcand -o -c -f -s8 /dev/usbcan_neck neck
   ip link set neck up
   
   exit 0
   ```

2. 以下のコマンドを実行し、実行権限を付与する。
   ```
   sudo chmod +x /etc/rc.local
   ```

## 8. ソフトウェアの準備

1. guardian_robot_systemリポジトリ(※guardian_robot_systemリポジトリのパス※)をクローンする。

2. 以下のコマンドを実行し、pyindy(各モジュールが共通で使用するPythonライブラリ)をインストールする。
   ```
   cd <guardian_robot_systemのパス>/modules/pyindy
   pip3 install .
   ```

## 9. 環境変数設定

ビルドや起動スクリプトは環境変数を参照するため、ビルドより先に本設定を行うこと。

1. 以下のコマンドを実行し、guardian_robot_system/indy.env.sampleをコピーして~/indy.envを作成する。
   ```
   cp <guardian_robot_systemのパス>/indy.env.sample ~/indy.env
   ```

2. ~/indy.envを開き、以下の項目をロボット搭載マシン用に設定する。
   ```
   vi ~/indy.env
   ```

   |変数名|設定値|
   |---|---|
   |ON_ROBOT|`1`(ロボット搭載マシンでは必須)<br>※`1`以外の場合、ロボット専用パッケージ(arm_motor_control、rover_wrapper、microphone_arrayなど)がビルドされない。<br>また、zenoh-bridge-ros2ddsがサーバ側として起動してしまう。|
   |GUARDIAN_ROBOT_PATH|guardian_robot_systemリポジトリのパス|
   |ROBOT_NAME|ロボット名|
   |MONGO_URI|このロボットのMongoDB(ロボットDB)のホスト名またはIPアドレス(MongoDBを動かすサーバマシン)<br>※サーバマシンで`setup/mongo_docker/setup_mongo.sh`を実行したときの最後に表示される値にする。|
   |MONGO_PORT|ロボットDBのポート番号(e.g. 9110)<br>※同上。|
   |RISM_CONFIG_HOST / RISM_CONFIG_PORT|設定DB(rism_configs)の接続先(任意。未設定の場合は`MONGO_URI`と`9100`)<br>※設定DBをロボットDBと別のサーバ・ポートに置いたときだけ設定する。|
   |ROS_DOMAIN_ID|ROS_DOMAIN_ID(サーバマシンと同じ値を設定)|
   |ZENOH_LISTEN|zenohの待ち受けIPアドレス(任意。空の場合は全インタフェースで待ち受け)|
   |ZENOH_PORT|zenohのポート番号(任意。サーバマシンと同じ値を設定。空の場合は7447)|

   ※`RMW_IMPLEMENTATION`、`CYCLONEDDS_URI`はサンプルの値から変更しないこと。  
   　CycloneDDSの設定にはリポジトリ内の`setup/ros2/zenoh/cyclonedds.xml`(通信をマシン内に限定する設定)が使用され、マシン間の通信はzenoh-bridge-ros2ddsが中継する。  
   　そのため、ホームディレクトリ等にcyclonedds.xmlを別途作成する必要はない。

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
   
   . "$HOME/.cargo/env"
   ```

   ※ビルド結果(install/local_setup.bash)は「10. ソフトウェアのビルド」の後に読み込まれるようになる。

4. 以下のコマンドを実行して設定を反映し、環境変数が設定されていることを確認する。
   ```
   source ~/.bashrc
   echo $ON_ROBOT $GUARDIAN_ROBOT_PATH $ROBOT_NAME $ROS_DOMAIN_ID
   ```

   ※起動スクリプトは、tmuxが起動した時点の環境変数を引き継ぐ。後から~/indy.envを変更した場合は、`~/module_launch/kill_sessions.sh`で全セッションを停止して`tmux kill-server`を実行し、新しいターミナルから起動し直すこと。

## 10. ソフトウェアのビルド

1. 以下のコマンドを実行し、ビルドする。
   ```
   cd $GUARDIAN_ROBOT_PATH/ros2_ws
   colcon build
   ```

2. 以下のコマンドを実行し、ビルド結果を反映する。
   ```
   source ~/.bashrc
   ```

## 11. chat_monitorの準備

会話ログ配信(chat_monitor)はNode.jsで動作する。  
chat_monitor(30_chat_monitor)は標準で起動するため、「12. 起動スクリプトの準備」より先に本章を実施すること。

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

## 12. 起動スクリプトの準備

起動スクリプト(module_launch)と運用ツール(tools/bin)は、迷わず実行できるよう、ホームディレクトリにシンボリックリンクを作成して使用する。  
※コピーではなくシンボリックリンクを作成すること。各スクリプトはリポジトリ内の`enable`フォルダを参照するため、コピーした先の`enable`に登録したスクリプトは起動されない。

1. 以下のコマンドを実行し、ホームディレクトリにmodule_launch、bin、tmuxの設定ファイルへのシンボリックリンクを作成する。
   ```
   ln -s $GUARDIAN_ROBOT_PATH/modules/module_launch ~/
   ln -s $GUARDIAN_ROBOT_PATH/tools/bin ~/bin
   ln -s $GUARDIAN_ROBOT_PATH/modules/indy_modules/tmux/.tmux.conf ~/
   ```

   ※~/binが既に存在する場合、2行目は~/bin/binを作成してしまう。その場合は2行目の代わりに以下を実行し、個別にリンクを作成する。
   ```
   ln -s $GUARDIAN_ROBOT_PATH/tools/bin/* ~/bin/
   ```

2. 一度ログアウトし、再度ログインする。  
   ~/binはログイン時にPATHに追加される(Ubuntu標準の~/.profileの設定による)。  
   以下のコマンドを実行し、binのスクリプトが見つかることを確認する。
   ```
   which 00_module_launch.sh
   ```

3. 以下のコマンドを実行し、一括起動するスクリプトを`enable`フォルダに登録する(標準の組み合わせ)。  
   各スクリプトの概要は、[Indyソフトウェア仕様書.md](../仕様書/Indyソフトウェア仕様書.md)の「1. ソフトウェア構成」の「① ロボット搭載マシン」を参照。
   ```
   cd ~/module_launch/enable
   ln -s ../available/000_zenoh_bridge.sh .
   ln -s ../available/00_charge_quiet.sh .
   ln -s ../available/00_indyXe_network_log.sh .
   ln -s ../available/01_indyXe_rover_sense.sh .
   ln -s ../available/02_indyXe_map.sh .
   ln -s ../available/02_indyXe_rover_base.sh .
   ln -s ../available/03_indyXe_slam_toolbox.sh .
   ln -s ../available/04_indyXe_robot_base.sh .
   ln -s ../available/10_indyXe_robot_sense.sh .
   ln -s ../available/20_grs_action_eye.sh .
   ln -s ../available/20_grs_action_gesture.sh .
   ln -s ../available/20_grs_action_nav.sh .
   ln -s ../available/20_grs_action_ros_command.sh .
   ln -s ../available/20_grs_action_tts.sh .
   ln -s ../available/20_grs_action_watchdog.sh .
   ln -s ../available/30_chat_monitor.sh .
   ls -l
   ```

   ※00_hv_watch(レスキューモード監視)は登録不要。`ON_ROBOT=1`の場合、module_launch.sh実行時に自動で起動される。  
   ※05_indyXe_microphone_array、10_indyXe_mic2sock_16ch、10_indyXe_send_audio_serverは標準では登録しない。必要な場合のみ、上記と同様に登録する。  
   　ただし、05_indyXe_microphone_arrayと10_indyXe_mic2sock_16chは同時に起動できないため、どちらか一方のみ登録すること。

4. ホームディレクトリで以下のコマンドを実行し、登録したスクリプトが一括起動されることを確認する。  
   起動・終了の詳細は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「2. 起動手順」「3. 終了手順」を参照。
   ```
   cd ~
   module_launch/module_launch.sh
   module_launch/check_sessions.sh
   ```

   ※初めての環境で動かす場合は、既定の地図(GRPの環境用)では自己位置推定・ナビゲーションが正しく動かない。「13. 地図の作成」で地図を作成・配置すること。

5. ブラウザで`http://<ロボット搭載マシンのホスト名>:3000/`を開き、会話ログ(chat_monitor)が表示されることを確認する。  
   ※chat_monitorは、MongoDBの接続先として~/indy.envの`MONGO_URI`、`MONGO_PORT`を使用する。  
   ※ポート番号はchat_monitorの`config_server.js`の`display_port`で変更できる。

6. 以下のコマンドを実行し、シナリオマネージャ(rism2)を動かすためのuvと依存パッケージをインストールする。  
   ※シナリオマネージャは、ロボット搭載マシンで`~/module_launch/scenario_launch.sh`により起動し、ホスト上でuvを使って動作する(起動方法は[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「2.5. シナリオの起動」を参照)。  
   ※rism2はPython 3.10で動作確認している(pyindyが`numpy==1.24.4`固定のため、Python 3.12ではビルドできない)。`.python-version`で3.10を指定しているため、Ubuntu 22.04のpython3(3.10)が使われる。python3が3.10以外の場合は、uvがPython 3.10を自動でダウンロードする。  
   ※依存パッケージ(pyindy経由のchromadb、onnxruntime、scipyなど)をダウンロードするため、インターネット接続と時間が必要。未実行の場合も、初回の`scenario_launch.sh`で自動でインストールされる。
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   新しいターミナルを開き、以下を実行する。
   ```
   uv --version
   cd $GUARDIAN_ROBOT_PATH/modules/scenario_manager/rism2
   uv sync
   ```

   ※シナリオマネージャは、サーバマシンの設定DB(既定のポート9100)とロボットDB(e.g. 9110)に接続する。ロボット搭載マシンから両方のポートに到達できること。

7. (任意)ロボットの状態表示・操作画面(indyxe_viewer)を使う場合は、以下のコマンドを実行し、依存パッケージのインストールと起動スクリプトの登録を行う。  
   ※indyxe_viewerは、カメラ、バッテリー、シナリオの状態、地図、聞き取った言葉、ロボットの行動を表示し、移動・発話を操作するWebページである。詳細は[README](../../modules/indy_modules/indyxe_viewer/Readme.md)を参照。  
   ※ロボット名・MongoDBの接続先は~/indy.envの`ROBOT_NAME`、`MONGO_URI`、`MONGO_PORT`を使用する。ポート番号は`INDYXE_VIEWER_PORT`(未設定の場合は8000)で変更できる。
   ```
   cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/indyxe_viewer
   uv sync
   cd ~/module_launch/enable
   ln -s ../available/30_indyxe_viewer.sh .
   ```

   module_launch.shで起動後、ブラウザで`http://<ロボット搭載マシンのホスト名>:8000/`を開き、画面が表示されることを確認する。  
   ※認証が無く、ロボットの移動・発話を操作できるため、信頼できるネットワーク内でのみ使用すること。

## 13. 地図の作成

自己位置推定(AMCL)とナビゲーションは、MongoDBの`map_server`パラメータで指定した地図を使用する。  
既定の地図(`grp_space.yaml`)はGRPの環境用のため、初めての環境で動かす場合は、SLAMで地図を作成し、worldパッケージに配置してから使用する。

### 13.1. SLAMの起動

1. 以下のコマンドを実行し、起動中のセッションをすべて停止する。  
   ※SLAM用のlaunchは、ローバのドライバ・LiDAR・rover_wrapperなども自分で起動する。通常の起動スクリプト(01_indyXe_rover_sense、02_indyXe_rover_baseなど)と同時に起動すると、ノードが重複して正しく動かない。  
   また、02_indyXe_mapが既存の地図を`/map`に配信するため、SLAMの地図と混ざる。
   ```
   ~/module_launch/kill_sessions.sh
   ~/module_launch/check_sessions.sh
   ```

2. (任意)別のマシンのrvizで地図を確認する場合は、以下のコマンドを実行し、zenoh-bridge-ros2ddsだけを起動する。
   ```
   ~/module_launch/available/000_zenoh_bridge.sh
   ```

3. ロボットを、地図の原点にしたい位置・向きに置く。  
   ※SLAMを開始した位置・向きが、地図の原点(x=0、y=0、yaw=0)になる。充電ステーションの前など、後で同じ位置に置き直しやすい場所を選ぶとよい。

4. 以下のコマンドを実行し、SLAM(slam_toolbox)を起動する。
   ```
   ros2 launch rover_tools slam_bringup.launch.py
   ```

   ※起動スクリプトの`03_indyXe_slam_toolbox`は、名前に反して地図を作成するものではない(作成済みの地図での自己位置推定とナビゲーションを起動する)。地図の作成には使用しないこと。

### 13.2. rvizでの地図の確認

1. 以下のコマンドを実行し、rvizを起動する。  
   ※ロボット搭載マシンにディスプレイがない場合は、別のマシンから起動する。別のマシンでは、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「4.1. マシン間のROS通信(zenoh)」の設定を行い、`export ROBOT_NAME=<ロボット名>`を設定してから`$GUARDIAN_ROBOT_PATH/tools/bin/60_rviz.sh`を実行する。
   ```
   60_rviz.sh
   ```

   ※60_rviz.shは、`modules/indy_modules/rviz2/robot_config.rviz`のロボット名を`ROBOT_NAME`に置き換えて起動する。Fixed Frameは`map`、Mapの表示は`/map`トピックに設定済みである。

2. 地図(Map)、LiDARの点群(LaserScan)、ロボットのモデル(RobotModel)が表示されることを確認する。  
   ※地図が表示されない場合は、別のターミナルで`ros2 topic list | grep map`を実行し、`/map`が配信されていることを確認する。

3. 「13.3. キーボードでの操作」でロボットを動かしながら、地図が広がっていくことを確認する。

### 13.3. キーボードでの操作

1. 別のターミナルで以下のコマンドを実行し、キーボード操作を起動する。  
   ※`/<ロボット名>/rover/cmd_vel`に速度指令を送る。速度はteleop_twist_keyboardの既定値(並進0.5m/s、回転1.0rad/s)で始まるため、地図の作成中は`z`キーで速度を下げてから動かすとよい。
   ```
   33_teleop_keyboard.sh
   ```

   ※「12. 起動スクリプトの準備」で~/binに個別にリンクを作成した場合は、`ln -s $GUARDIAN_ROBOT_PATH/tools/bin/33_teleop_keyboard.sh ~/bin/`でリンクを追加する。

   |キー|動作|
   |---|---|
   |`i`|前進|
   |`,`|後退|
   |`j`|左回転|
   |`l`|右回転|
   |`u` / `o`|左前 / 右前に進む|
   |`k`(その他のキー)|停止|
   |`q` / `z`|速度を10%上げる / 下げる|
   |`Ctrl+C`|終了|

   ※キーを押したときだけ速度指令が送られる。ローバのドライバは、最後の速度指令から1.0秒を超えると停止するため、動かし続けるときはキーを押し続ける。  
   ※SLAMの起動中は、障害物回避(vel_filter)が動いていない。障害物や人にぶつからないよう、目で確認しながら操作すること。

2. 対象の環境全体を、ゆっくりと走行する。  
   ※急な回転は地図のずれの原因になるため、回転はゆっくり行う。  
   ※一周して開始位置付近に戻ると、ループの閉じ込みにより地図のずれが補正される。

### 13.4. 地図の保存

SLAMを起動したまま、以下を行う。

1. 以下のコマンドを実行し、地図を保存する。  
   `<地図名>`には、環境を表す名前を付ける(e.g. `lab_1f`)。`<地図名>.pgm`(画像)と`<地図名>.yaml`(解像度・原点など)が作成される。
   ```
   mkdir -p ~/maps
   cd ~/maps
   ros2 run nav2_map_server map_saver_cli -f <地図名>
   ```

   ※`/map`トピックを受信して保存する。`Map saved successfully`と表示されれば成功。  
   ※`Failed to save the map`などで失敗した場合は、`ros2 topic list | grep map`で`/map`が配信されていることを確認し、もう一度実行する。

2. 以下のコマンドを実行し、保存した地図を確認する。  
   `image:`がパスを含まないファイル名(`<地図名>.pgm`)になっていること。パスが含まれている場合は、ファイル名だけに修正する。
   ```
   cat ~/maps/<地図名>.yaml
   ```

3. キーボード操作とSLAMを`Ctrl+C`で終了する。  
   ※地図の作成中、rover_wrapperが`~/config/rover_pose.txt`に新しい地図での現在位置を書き込んでいる。SLAMの終了後にロボットを動かさなければ、次の起動時にその位置から自己位置推定を始める。

### 13.5. 地図の配置

1. 以下のコマンドを実行し、保存した地図をworldパッケージの`map`フォルダにコピーする。
   ```
   cp ~/maps/<地図名>.pgm ~/maps/<地図名>.yaml $GUARDIAN_ROBOT_PATH/ros2_ws/indy/world/map/
   ```

2. 以下のコマンドを実行し、worldパッケージをビルドする。  
   ※地図はビルド時に`install/world/share/world/`へコピーされ、そこから読み込まれる。ビルドしないと新しい地図は使われない。
   ```
   cd $GUARDIAN_ROBOT_PATH/ros2_ws
   colcon build --packages-select world
   source ~/.bashrc
   ```

3. ロボットDBのMongoDB管理画面で、`robot_config`/`system_parameters`の`map_server`のDocumentを開き、以下の通り変更して保存する。  
   操作方法は、[Indyマニュアル.md](../マニュアル/Indyマニュアル.md)の「5.1. MongoDBでのパラメータ設定」を参照。

   |parameter名|設定値|
   |---|---|
   |map_yaml_file|`<地図名>.yaml`|
   |keepout_yaml_file|`""`(空)<br>※進入禁止エリアを設定する場合は、手順4で作成したファイル名にする。|

   ※既定の`keepout_yaml_file`(`grp_keepout.yaml`)はGRPの環境用で、大部分が進入禁止になっている。新しい地図で残したままにすると、ナビゲーションが動かなくなるため、必ず変更すること。  
   ※`keepout_yaml_file`が空の場合、進入禁止エリアの配信は起動しない。nav2のkeepoutフィルタは`Filter mask was not received`の警告を出すが、制限なしで動作する。

4. (任意)進入禁止エリアを設定する場合は、keepoutマップを作成する。
   1. `<地図名>.pgm`を画像編集ソフト(GIMPなど)で開き、ロボットが通ってよい場所を白、進入禁止の場所を黒で塗る。画像のサイズは変えないこと。
   2. `<地図名>_keepout.pgm`という名前でPGM形式(raw)で保存する。
   3. `<地図名>.yaml`をコピーして`<地図名>_keepout.yaml`を作成し、`image:`を`<地図名>_keepout.pgm`に変更する。`resolution`、`origin`は地図と同じ値のままにする。
   4. 2つのファイルを`world/map`に置き、手順2のビルドと、手順3の`keepout_yaml_file`の設定を行う。

   ※作成例は`world/map/grp_keepout.pgm`、`grp_keepout.yaml`を参照。

### 13.6. 新しい地図での動作確認

1. ロボットを、SLAMを終了した位置に置いたまま(または地図の原点に置き直して)、以下のコマンドを実行して起動する。
   ```
   cd ~
   module_launch/module_launch.sh
   module_launch/check_sessions.sh
   ```

   ※地図の原点に置き直した場合は、起動前に以下のコマンドを実行し、初期位置を原点にしておく。
   ```
   echo "0.0,0.0,0.0" > ~/config/rover_pose.txt
   ```

2. 以下のコマンドを実行してrvizを起動し、新しい地図が表示されることを確認する。
   ```
   60_rviz.sh
   ```

3. LiDARの点群(LaserScan)が地図の壁と重なっていない場合は、「2D Pose Estimate」で自己位置を設定する。
   1. rviz上部のツールバーで「2D Pose Estimate」を押下する。
   2. 地図上で、ロボットが実際にいる位置をクリックし、そのままロボットの向きの方向へドラッグして離す。
   3. LaserScanが地図の壁と重なることを確認する。ずれている場合は、もう一度設定する。

   ※設定した位置は`/<ロボット名>/rover/initialpose`に送られ、AMCLの自己位置が更新される(60_rviz.shの設定で変更済み)。

4. 「Goal Pose」で移動先を指定し、ナビゲーションで移動することを確認する。
   1. rviz上部のツールバーで「Goal Pose」を押下する。
   2. 地図上で、移動先の位置をクリックし、そのまま到着時に向かせたい方向へドラッグして離す。
   3. 経路(Path)が表示され、ロボットが移動先まで移動することを確認する。

   ※設定した移動先は`/<ロボット名>/rover/goal_pose`に送られる(60_rviz.shの設定で変更済み)。  
   ※rvizから送った移動先は、`40_stop_nav.py`(rover_wrapper経由の移動を止めるもの)では止まらない。途中で止める場合は、ロボットの現在位置付近をGoal Poseで指定し直す(新しい移動先で上書きされる)。

5. 新しい地図では座標が変わるため、地図の座標を使う設定(充電ステーションの位置、`40_goto_home.sh`の移動先、`20_set_poseangle_to_station.sh`の初期位置、シナリオで指定している移動先など)は、新しい地図の座標に合わせて変更すること。  
   ※Goal Poseで移動させた(または手で置いた)ロボットが目的の位置にある状態で`ros2 topic echo --once /<ロボット名>/rover/pose`を実行すると、その位置の座標を確認できる。
