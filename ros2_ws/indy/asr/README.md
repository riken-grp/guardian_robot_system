# asrノード
## 起動手順
### ノード起動方法
- ROS2ワークスペースにて以下のコマンドを実行することで起動する。
```
source install/setup.bash
ros2 launch asr all_asr_launch.py mongo_uri:=<アドレス> mongo_port:=<ポート番号>
```

### パラメタ設定方法
MongoDBでパラメタを設定することができる。
DB: `robot_config`
Collection: `system_parameters`

設定できるパラメタは以下の通り。
  - adinserver (デフォルト：localhost)
  - adin_ports (デフォルト：[5560])
  - adin_ports_priority (デフォルト：{5562:0})
  - device (デフォルト：cuda)
  - ignore_short_pause (デフォルト：0.5)
  - asr_model (デフォルト：whisper_large_v2)
  - socket_keepalive (デフォルト：[60, 10, 6])
  - debug_msgs (デフォルト：false)

*socket_keepaliveについて。*値が[X,Y,Z]の場合：
- socketがidle状態になってからX秒後に「keepalive packets」の送信を開始します。
- socketはY秒ごとに「keepalive packets」を送信します。
- 送信失敗した「keepalive packets」の数がZになると、socketの状態は「connection error」となります。

### オンザフライポート再割り当て

`asr_ctrl`のROSトピックで、ポート番号を変更出来ます。

例：`ros2 topic pub --once /$ROBOT_NAME/asr/asr_ctl std_msgs/msg/String 'data: "{\"sep_ports\":[5562, 5563, 5564]}"'`


### ASRのポートリセット

`asr_ctrl`のROSトピックで、

`ros2 topic pub --once /$ROBOT_NAME/asr/asr_ctl std_msgs/msg/String 'data: "{\"reset_ports\":True}"'`

って送ったら、全部のポートをリセットされます。