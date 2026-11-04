# audio_publisher
TCPで受信したマイクの音声データ（16bit PCM）をROSトピックとして配信する。

## 起動方法
```
ros2 launch audio_publisher mic_info.launch.py
```
- 環境変数`ROBOT_NAME`が必須。ノードは`ROBOT_NAME`の名前空間で起動する。
- launch引数
  |引数名|デフォルト値|概要|
  |:--|:--|:--|
  |mongo_uri|''|パラメータ取得先のMongoDB URI|
  |mongo_port|1|パラメータ取得先のMongoDBポート番号|

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|audio|std_msgs/Int16MultiArray|受信した音声データ（リトルエンディアンの16bit符号付き整数列）|

**subscribe**
- なし

### 音声データの受信
- `receive_port`でTCP接続を待ち受け、接続したクライアントごとにスレッドを立てて受信する。
- 受信データは2バイトごとにリトルエンディアンの16bit符号付き整数として解釈する。
- 受信データのバイト数が奇数の場合、または接続が切断された場合は、そのクライアントの受信を終了する。

## 設定方法
### rosパラメータ
- 以下は、config/mic_info.yamlにて設定されている。
  |parameter名|デフォルト値|概要|
  |:--|:--|:--|
  |receive_port|5661|音声データ受信用TCPポート番号|
  |client_number|10|TCP接続の待ち受けキュー数|
  |msg_size|8192|1回の受信で読み込む最大バイト数|
