# ParamManager

## 概要
`ParamManager` はMongoDBのrobot_config/system_parametersから各種パラメータを取得するクラスです。
1. 指定されたホスト名・ポート番号でMongoDBに接続します。
2. MongoDBのrobot_config/system_parametersから各種パラメータを取得します。

## 使い方
### インポート・インスタンス化
```python
from pyindy.param_manager import ParamManager

pm = ParamManager("example.local", 9000)
```
- 引数
  - `env_uri`: ロボット用MongoDBのホスト名
  - `env_port`: ロボット用MongoDBのポート番号
- インスタンス化の時点でMongoDBに接続し、パラメータを一括で読み込みます（以後のメソッドは読み込んだ内容を返します）。
- MongoDBに接続できない場合（1秒でタイムアウト）は`ConnectionError`を送出します。
- 各ドキュメントは`name`（キー）と`config`（パラメータ）を持つ必要があります。`name`の無いドキュメントがあると`KeyError`を送出します。

### 主なメソッド

#### パラメータ取得
- `get_param(key_name)`
    - 指定したキーのローカルパラメータ（config: dict）を取得。キーが存在しない場合は`None`を返す
- `get_all_param()`
    - 全ローカルパラメータ（list of dict）を取得
- `get_all_key()`
    - ローカルパラメータのキー（list of str）一覧を取得
