# pyindy

Indyの各モジュール(ros2_ws/indy配下のパッケージ、modules配下のツール)が共通で使用するPythonライブラリです。

## 構成

|サブパッケージ|内容|
|---|---|
|`pyindy.mongo`|MongoDBへの接続、シナリオ・アクション・記憶などのデータ操作|
|`pyindy.param_manager`|MongoDBの`robot_config.system_parameters`からのパラメータ取得（[param_manager/README.md](pyindy/param_manager/README.md)参照）|
|`pyindy.llm`|LLM・埋め込みAPIの呼び出し|
|`pyindy.grp_tts`|音声合成・音声ファイルの再生|
|`pyindy.rover`|ローバ操作の補助|
|`pyindy.functions`|共通関数|
|`pyindy.sample`|サンプル|

## インストール方法

以下のコマンドでインストールします。依存ライブラリ（`pyproject.toml`の`dependencies`）も合わせてインストールされます。
```
cd $GUARDIAN_ROBOT_PATH/modules/pyindy
pip3 install .
```

- `pip3 install .`はソースをコピーしてインストールするため、pyindyのソースを更新した場合は再度インストールしてください。

- サーバマシンでは、Apptainerコンテナ上で上記のコマンドを実行してインストールします。
