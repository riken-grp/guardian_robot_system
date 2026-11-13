# network_check
ネットワーク接続状況を監視し、以下の情報をデータベースに記録する。

- ロボット名
- ホスト名
- ネットワーク接続状況
- Wi-Fi信号強度
- Wi-Fi信号アクセスポイント名
- ロボットの位置
- ロボットの姿勢

## 起動方法
```
ros2 launch network_check network_check_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
```
- launch引数
  - mongo_uri / mongo_port：記録先MongoDBの接続先。
  - network_interface：監視する無線インターフェース名（例: `wlan0`）。省略時（デフォルト値：`''`）は`iw dev`で検出したインターフェースのうち、接続中の最初のものを使用する。

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|network_check/info|network_msgs/NetworkInfo|ネットワーク情報|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|rover/pose|geometry_msgs/PoseStamped|ロボットの現在位置・姿勢|

## 設定方法
## rosパラメータ
config/default_param.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|report_rate|10.0|監視周期[s]|