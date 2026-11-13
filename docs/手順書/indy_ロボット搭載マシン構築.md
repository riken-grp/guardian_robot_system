# ロボット搭載マシン構築手順

> **注意**  
> ロボット搭載マシンは、サーバマシン上のMongoDBに接続して動作する。  
> 本手順の前に、[サーバマシン構築.md](サーバマシン構築.md)の「5. MongoDBの構築」を実施し、MongoDBを構築しておくこと。  
> 「9. 環境変数設定」で設定する`MONGO_URI`、`MONGO_PORT`には、構築したMongoDBの値を使用する。

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
   ```

4. 以下のコマンドを実行し、Pythonライブラリをインストールする。
   ```
   pip install opencv-python
   pip install open3d
   ```

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
   |MONGO_URI|MongoDBのホスト名またはIPアドレス(MongoDBを動かすサーバマシン)<br>※サーバマシンのmongo.envの`MONGO_PUBLIC_HOST`と同じ値にする。|
   |MONGO_PORT|MongoDBのポート番号<br>※サーバマシンのmongo.envの`MONGO_PORT`と同じ値にする。|
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

5. ブラウザで`http://<ロボット搭載マシンのホスト名>:3000/`を開き、会話ログ(chat_monitor)が表示されることを確認する。  
   ※chat_monitorは、MongoDBの接続先として~/indy.envの`MONGO_URI`、`MONGO_PORT`を使用する。  
   ※ポート番号はchat_monitorの`config_server.js`の`display_port`で変更できる。
