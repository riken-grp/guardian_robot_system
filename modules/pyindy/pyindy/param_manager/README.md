# ParamManager

## 概要
`ParamManager` はMongoDBのrobot_config/system_parametersから各種パラメータを取得するクラスです。
1. 指定されたホスト名・ポート番号でMongoDBに接続します。
2. MongoDBのrobot_config/system_parametersから各種パラメータを取得します。

## 使い方
### インポート・インスタンス化
```python
from pyindy.param_manager import ParamManager

pm = ParamManager("example.local", 3000)
```
- 引数
  - `env_uri`: ロボット用MongoDBのホスト名
  - `env_port`: ロボット用MongoDBのポート番号

### 主なメソッド

#### パラメータ取得
- `get_param(key_name)`
    - 指定したキーのローカルパラメータ（config: dict）を取得
- `get_all_param()`
    - 全ローカルパラメータ（list of dict）を取得
- `get_all_key()`
    - ローカルパラメータのキー（list of str）一覧を取得
