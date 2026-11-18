# asrノード
## 前提
- 形態素解析器 JUMAN++(`jumanpp` コマンド、1.02)が必要(`asr_metadata` が `echo ... | jumanpp` で呼び出す)。
- 標準の起動スクリプト(`modules/module_launch/available/50_grsrv_asr.sh`)で使うコンテナイメージ `setup/container_image/ros2_12-6-3_on_server.sif` には同梱されている(`ros2_12-6-3_on_server.def` でビルド)。jumanpp を含まない古いイメージの場合は再ビルドする。
- コンテナ外で起動する場合は、以下の手順で個別にインストールする(Boost のヘッダ `libboost-dev` が必要)。`--prefix` が長すぎると実行時に `buffer overflow detected` で異常終了するため、短いパスにすること。
  ```
  wget http://lotus.kuee.kyoto-u.ac.jp/nl-resource/jumanpp/jumanpp-1.02.tar.xz
  tar xJf jumanpp-1.02.tar.xz
  cd jumanpp-1.02
  ./configure --prefix=$HOME/tools
  make
  make install
  # $HOME/tools/bin を PATH に追加する
  ```

## 起動手順
### ノード起動方法
- ROS2ワークスペースにて以下のコマンドを実行することで起動する。
```
source install/setup.bash
ros2 launch asr all_asr_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
```
- `asr_launch.py` は、環境変数 `ASR_GPU_ID` で指定した GPU 番号（未設定時は `3`）を `CUDA_VISIBLE_DEVICES` に設定して asr_node を起動する。GPU が4枚未満のマシンでは `ASR_GPU_ID` の設定が必要（`~/indy.env` に記載する）。

### パラメタ設定方法
MongoDBでパラメタを設定することができる。
DB: `robot_config`
Collection: `system_parameters`
Document: `name` が `asr` の Document の `config` フィールド（標準データは `setup/mongo_docker/default_data/robot_config.system_parameters.json`）

設定できるパラメタは以下の通り。
  - adin_server (デフォルト：localhost)
  - adin_ports (デフォルト：[5562])
  - adin_ports_priority (デフォルト：{5562:0})
  - device (デフォルト：cuda)
  - ignore_short_pause (デフォルト：0.5)
  - asr_model (デフォルト：whisper_large_v2)
  - socket_keepalive (デフォルト：[60, 10, 6])
  - debug_msgs (デフォルト：false)
  - always_respond (デフォルト：true)

*socket_keepaliveについて。*値が[X,Y,Z]の場合：
- socketがidle状態になってからX秒後に「keepalive packets」の送信を開始します。
- socketはY秒ごとに「keepalive packets」を送信します。
- 送信失敗した「keepalive packets」の数がZになると、socketの状態は「connection error」となります。

### オンザフライポート再割り当て

`asr/asr_ctl`のROSトピックで、ポート番号を変更出来ます。

例：`ros2 topic pub --once /$ROBOT_NAME/asr/asr_ctl std_msgs/msg/String 'data: "{\"sep_ports\":[5562, 5563, 5564]}"'`


### ASRのポートリセット

`asr/asr_ctl`のROSトピックで、

`ros2 topic pub --once /$ROBOT_NAME/asr/asr_ctl std_msgs/msg/String 'data: "{\"reset_ports\":true}"'`

って送ったら、全部のポートがMongoDBで設定した`adin_ports`にリセットされます。