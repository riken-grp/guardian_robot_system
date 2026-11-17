# MongoDB（サーバマシン用）

ロボットが記憶・設定・ログの保存に使い、シナリオマネージャ（[rism2](../../modules/scenario_manager/rism2/README.md)）が読み書きする MongoDB を、Docker Compose で起動します。
MongoDB は次の 2 種類です。

| DB | 既定のポート | 中身 |
|---|---|---|
| 設定DB | 9100 | `rism_configs`（`rism_config`: rism2 全体の設定、`robot_list`: ロボットごとの設定、`demo_list`: デモがどのシナリオDB を使うか、`common`: 全ロボット共通の設定）。全ロボットで 1 つ |
| ロボットDB | ロボット 1, 2, 3, ... に 9110, 9120, 9130, ...（9100 + 10 × 番号） | `tBlackBoard`（観測、Actions など）、`demo_configs`（シナリオ）、`robot_config`・`memory_settings`・`persona` など。ロボットごとに 1 つ |

compose ファイルは手で書かず、対話式のツール `setup_mongo.sh` で作ります。環境変数のファイル（旧 `mongo.env`）を手で書く必要はありません。

## 構成

| ファイル・フォルダ | 内容 |
|---|---|
| `setup_mongo.sh` | 対話式のツール。`setup_mongo.py` を rism2 の uv 環境（`modules/scenario_manager/rism2`）で動かす wrapper |
| `setup_mongo.py` | 本体。rism2 の `tools/install.py` を呼び出し、compose ファイルを作り、DB に設定と標準データを入れる。Indy 用に、キャッシュ上限・ログのローテーション・下記の標準データを足す |
| `default_data/` | ロボットDB に入れる標準データ（`<db>.<collection>.json`） |
| `default_data_config/` | 設定DB に入れるロボット側の設定（`rism_configs.robot_list.json`: `robot_list` のそのロボットの文書に追記する項目、`rism_configs.common.json`: `common`） |
| `deploy/` | `setup_mongo.sh` が作るフォルダ（git 管理外）。ロボットごとに `deploy/<ロボットID>/` を作る |

`deploy/<ロボットID>/` に作られるファイル（以下、`deploy/<ロボットID>/` は対話で答える「docker compose ファイルを置くフォルダ」のこと。既定は `deploy/<ROBOT_NAME>` なので、ロボットの ID を `ROBOT_NAME` と同じにすれば一致する。違うフォルダを答えた場合は読み替える）：

| ファイル | 内容 |
|---|---|
| `docker-compose.yml` | MongoDB と Web UI の定義（rism2 の `tools/install.py` が作る） |
| `.env` | `MONGO_PUBLIC_HOST`（レプリカセットのメンバー名に使うホスト名）、`MONGO_IMAGE`、`COMPOSE_FILE` |
| `rs-healthcheck.js` | レプリカセットの初期化・メンバー名の修正・状態確認を行う healthcheck |
| `docker-compose.indy.yml` | Indy 用の追加（WiredTiger のキャッシュ上限、コンテナのログのローテーション）。`.env` の `COMPOSE_FILE` で自動で読むため、`docker compose` に `-f` は不要 |
| `install_answers.json` | 対話の答え（`--answers` で再利用する） |
| `indy_answers.json` | Indy 用の答え（キャッシュ上限、サーバの値） |

データはリポジトリの外（対話で答える「データを置くディレクトリ」）に置きます。

## 前提

- Docker Engine と Docker Compose v2（`docker compose` コマンド）
- 起動するユーザが `docker` グループに入っていること（入っていなければ `docker` のコマンドに `sudo` を付ける）
- uv（`setup_mongo.sh` が使う。無ければエラーで止まる）
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- rism2 の依存（`setup_mongo.sh` は rism2 の環境で動くため。初回実行時に uv が自動で入れる。先に入れておく場合は以下）
  ```bash
  cd $GUARDIAN_ROBOT_PATH/modules/scenario_manager/rism2
  uv sync
  ```
  ※rism2 は Python 3.10 で動作確認しています。pyindy が `numpy==1.24.4` 固定のため、Python 3.12 ではビルドできません（Ubuntu 22.04 の python3 は 3.10 のため、uv がそれを使います）。
- ロボット・シナリオマネージャから、このサーバのホスト名が名前解決でき、各 MongoDB のポートに到達できること

## 1台目のロボット（設定DB とロボットDB を同じサーバに置く）

### 1. 対話で compose ファイルを作る

```bash
$GUARDIAN_ROBOT_PATH/setup/mongo_docker/setup_mongo.sh
```

`[ ]` の中が既定値で、Enter でその値を使います。
シェルで `ROBOT_NAME` が設定されていれば、ロボットの ID と compose を置くフォルダの既定値に使われます（未設定でも可）。

| 質問 | 既定 | 説明 |
|---|---|---|
| 設定DB も新しく作りますか | Y | 1台目は Y |
| 設定DB とロボットDB を同じサーバに置きますか | Y | n なら「設定DB とロボットDB を別のサーバに置く」を参照 |
| そのサーバのホスト名 | このマシンのホスト名 | ロボット・シナリオマネージャからつなぐ名前（例 `db.example.local`）。レプリカセットのメンバー名になるので、つなぐ側から引ける名前にする |
| 設定DB のポート | 9100 | |
| ロボットの番号 | 1 | ロボットDB のポートの既定が 9100 + 10 × 番号になる |
| ロボットDB のポート | 9110 | |
| Web UI | mongo-express | `mongo-express`（DB ごとに 1 つ、各 MongoDB のポート+1）、`dbgate`（1 つで全部、最初の DB のポート+1）、`none`。どれもログインなし |
| データを置くディレクトリ | `/srv/indy/mongodb` | 絶対パス。この下に `mongodb_for_rism_config/` と `mongodb_for_<ロボットID>/` を使う |
| MongoDB を動かすユーザー | 1001:1001 | uid:gid。データのディレクトリの持ち主 |
| docker compose ファイルを置くフォルダ | `setup/mongo_docker/deploy/<ROBOT_NAME>` | |
| ロボットの ID | `ROBOT_NAME` | `robot_list` のキー。ROS のトピック名にも使う。ロボットの `ROBOT_NAME` と同じにする |
| 表示名 | ロボットの ID の先頭を大文字にしたもの | |
| デモの ID | `<ロボットID>_demo` | `demo_list` のキー（scenario_launch.sh の `SCENARIO_DEMO`） |
| LLM サーバの URL | `http://localhost:8001/v1` | 発話を作る LLM サーバ（OpenAI 互換）。ホスト部は標準データの `__LLM_HOST__` にも入る |
| LLM のモデル名 | indy-instruct | |
| サンプルのシナリオと知識も入れますか | Y | n なら設定だけ |
| MongoDB のキャッシュ上限（GB） | 1 | 1 台のサーバで複数動かすときは小さめにする（「設計上の注意」参照） |
| 埋め込み API のホスト、音声合成サーバのホスト、adintool サーバの IP、音声の送り先の IP、Google 音声認識中継サーバの IP | （なし） | 標準データのプレースホルダに入る（「プレースホルダ」参照）。わからなければ Enter で飛ばし、あとで Web UI で書き換える |

答えを確認して進めると、`deploy/<ロボットID>/` にファイルを作り、次の 2 つのコマンドを表示します。

- データのディレクトリを作るコマンド（`sudo mkdir -p <dir>/mongodb_for_rism_config/{data,config,var_cache} <dir>/mongodb_for_<ロボットID>/{data,config,var_cache} && sudo chown -R <uid:gid> ...`）
- 起動のコマンド（`cd <deploy/<ロボットID>> && docker compose up -d`）

最後に「MongoDB は起動していますか？ [y/N]」と聞かれます。初回は N と答えると、手順4のコマンドを表示して終了します。

### 2. データディレクトリを作る

手順1で表示されたコマンドを、そのまま実行します。
**`docker compose up` より前に**作り、所有者を MongoDB を動かすユーザーに合わせてください。
作らずに起動すると Docker が root 所有で作ってしまい、mongod が書き込めず起動に失敗します。

### 3. 起動する

手順1で表示された起動のコマンドを実行し、状態を確認します。

```bash
cd $GUARDIAN_ROBOT_PATH/setup/mongo_docker/deploy/<ロボットID>
docker compose up -d
docker compose ps        # mongo-config と mongo-robot が (healthy) になれば完了
```

初回は、healthcheck がレプリカセットを自動で初期化します。
Web UI は、MongoDB が healthy になってから起動します。

### 4. 設定と標準データを DB に入れる

保存した答えを使い、DB に書き込みます（もう一度は聞きません）。

```bash
$GUARDIAN_ROBOT_PATH/setup/mongo_docker/setup_mongo.sh --answers $GUARDIAN_ROBOT_PATH/setup/mongo_docker/deploy/<ロボットID>/install_answers.json
```

次の順に、書き込む内容を表示してから、確認して書き込みます。

1. rism2 の設定とサンプル（dry-run で表示 → 確認して書き込み）
   - 設定DB: `rism_configs.rism_config`、`robot_list`、`demo_list`
   - ロボットDB: `demo_configs.scenarios`、`interruption_subscenarios`、`knowledge`（サンプルを入れる場合）
2. OpenWeatherMap の API キーを聞く（設定DB に `common` が無いときだけ。ファイルには保存しない。Enter で飛ばせる）
3. Indy 用のデータ（表示 → 確認して書き込み）
   - ロボットDB: `default_data/` の標準データ。同じ `_id` のドキュメントがあれば入れません。標準データの内容で上書きしたいときは `--overwrite` を付けます（標準データに無いドキュメントは削除されません）
   - 設定DB: `robot_list` のそのロボットの文書に、`default_data_config/rism_configs.robot_list.json` の項目を追記。`common` が無ければ作る
4. 置き換えていないプレースホルダ（`__TTS_HOST__` など）と、その場所を表示
5. `~/indy.env` に書く値を表示（「6. ~/indy.env に書く」参照）

### 5. プレースホルダを書き換える

手順4で表示されたプレースホルダを、Web UI で環境に合わせて書き換えます（「プレースホルダ」参照）。
Web UI は、ブラウザで `http://<ホスト名>:<各 MongoDB のポート+1>/`（例 `http://db.example.local:9101/` が設定DB、`http://db.example.local:9111/` がロボットDB）を開きます。
Web UI にはログインが無いため、信頼できるネットワーク内でのみ使ってください。

### 6. ~/indy.env に書く

手順4の最後に、ロボット・シナリオを動かすマシンの `~/indy.env` に書く値が表示されます。

| 変数 | 表示されるとき | 値 |
|---|---|---|
| `ROBOT_NAME` | 常に | ロボットの ID |
| `MONGO_URI` / `MONGO_PORT` | 常に | ロボットDB のホスト名とポート |
| `RISM_CONFIG_HOST` | 設定DB がロボットDB と別のサーバのときだけ | 設定DB のホスト名（未設定の場合は `MONGO_URI` を使う） |
| `RISM_CONFIG_PORT` | 設定DB のポートが 9100 以外のときだけ | 設定DB のポート（未設定の場合は 9100） |
| `SCENARIO_DEMO` | デモの ID が `<ロボットID>_demo` 以外のときだけ | デモの ID |

これらの値は、ロボット搭載マシンとサーバマシンの両方の `~/indy.env` に設定します。
シナリオは、ロボット搭載マシン（robodj の場合は robodj）で `$GUARDIAN_ROBOT_PATH/modules/module_launch/scenario_launch.sh` により起動します（[module_launch/README.md](../../modules/module_launch/README.md) 参照）。サーバ側でシナリオマネージャを動かす必要はありません。

## 2台目以降のロボット（設定DB が既にある）

同じ手順で `setup_mongo.sh` を実行し、次のように答えます。

- 「設定DB も新しく作りますか」に `n`
- 「今ある設定DB のホスト名」に、1台目で作った設定DB のホスト名
- 「ロボットの番号」に `2`（ロボットDB のポートの既定が 9120 になる）など
- compose を置くフォルダ・ロボットの ID は、1台目と重ならないもの（`ROBOT_NAME` を 2台目の名前にしておけば、既定値がそれになる）

ロボットDB だけの compose（プロジェクト名 `rism2-<ロボットID>`。1台目とぶつからない）が `deploy/<ロボットID>/` に作られます。
1台目と同様に、表示されたコマンドでデータディレクトリを作って `docker compose up -d` し、`--answers` で DB に入れます。
このとき、`rism_config` は既にあるため入れず、`robot_list`・`demo_list`・シナリオを追加します。`common` も既にあるため入れません。

## 設定DB とロボットDB を別のサーバに置く

「設定DB とロボットDB を同じサーバに置きますか」に `n` と答え、それぞれのサーバのホスト名を答えます。
`deploy/<ロボットID>/config/`（設定DB 用）と `deploy/<ロボットID>/robot/`（ロボットDB 用）の 2 つのフォルダができます。

- それぞれのサーバにフォルダごとコピーし、表示されたコマンドでデータディレクトリを作ってから、そのフォルダの中で `docker compose up -d` を実行します（`.env` に `COMPOSE_FILE` があるため `-f` は不要）。
- ロボット・シナリオを動かすマシンの `~/indy.env` には、`RISM_CONFIG_HOST`（設定DB のホスト名）も書きます（手順4の最後に表示されます）。

※この構成は、compose ファイルの生成と `docker compose config` までを確認しています。2 台のサーバでの起動は未確認です。

## プレースホルダ

標準データのうち、環境によって変わる値は `__名前__` のプレースホルダになっています。
`setup_mongo.sh` が置き換えるもの、対話で聞くものは次のとおりです。対話で Enter で飛ばしたものは、置き換えずに残します（手順4の最後に一覧が出るので、Web UI で書き換えてください）。

| プレースホルダ | 置き換え | 場所 | 内容 |
|---|---|---|---|
| `__ROBOT_NAME__` | 自動（ロボットの ID） | ロボットDB `robot_config.system_parameters`、`memory_settings.module_settings` | ロボット名 |
| `__MONGO_HOST__` / `__MONGO_PORT__` | 自動（ロボットDB のホスト名・ポート） | ロボットDB `robot_config.system_parameters` | MongoDB の接続先 |
| `__LLM_HOST__` | 自動（「LLM サーバの URL」のホスト部） | ロボットDB `robot_config.system_parameters`（memory / llm_responder） | LLM サーバ（OpenAI 互換 API）のホスト |
| `__EMBED_HOST__` | 対話 | ロボットDB `robot_config.system_parameters`（memory / llm_responder） | 埋め込み API のホスト |
| `__TTS_HOST__` | 対話 | ロボットDB `persona.Voice` | 音声合成サーバのホスト（`type` が `hoya` のとき使用） |
| `__ADIN_SERVER__` | 対話 | ロボットDB `robot_config.system_parameters`（asr） | 音声認識の入力（adintool）サーバの IP |
| `__AUDIO_IP__` | 対話 | ロボットDB `robot_config.system_parameters`（ros_audio_tracker） | 音声の送り先の IP |
| `__GOOGLE_ASR_SERVER__` | 対話 | 設定DB `rism_configs.robot_list`（`google_asr`） | Google 音声認識中継サーバの IP |
| `__OPENWEATHERMAP_TOKEN__` | `--answers` で DB に入れるときに聞く（`common` が無いときだけ。ファイルには保存しない） | 設定DB `rism_configs.common` | OpenWeatherMap の API キー（天気の話題で使用） |

Indy 用の答え（キャッシュ上限と、対話で答えたサーバの値）は `deploy/<ロボットID>/indy_answers.json` に保存され、`--answers` で再利用されます。

## 標準データの中身

ロボットDB（`default_data/`）：

| コレクション | 件数 | 内容 |
|---|---|---|
| `robot_config.system_parameters` | 8 | 各モジュールのパラメータ（human_tracker / ros_audio_tracker / asr / sensor_tf / memory / llm_responder / gestures_modes / map_server） |
| `memory_settings.llm_prompts` / `module_settings` | 44 / 4 | LLM のプロンプト、記憶モジュールの設定 |
| `persona.Voice` / `ActionPrimitives` | 1 / 66 | 声の設定、ジェスチャーの定義 |
| `tBlackBoard.internal_state` | 6 | 内部状態の初期値 |

設定DB（`default_data_config/`）：

| コレクション | 内容 |
|---|---|
| `rism_configs.robot_list` | そのロボットの文書に追記する、ロボット側のプログラムが読む設定（`google_asr`、`asr_target_angle`、`ignore_non_looking`、`recognition_available_regions`、`personality`、`llm.system_prompt`） |
| `rism_configs.common` | 全ロボット共通の設定（`city`、`language`、`openweathermap_token`）。無いときだけ作る |

このほか、rism2 の `tools/setup_db.py` が、設定DB の `rism_configs.rism_config`・`robot_list`・`demo_list` と、ロボットDB の `demo_configs`（サンプルのシナリオ `scenarios` 4 件、割り込みサブシナリオ `interruption_subscenarios` 7 件、`knowledge`）を入れます。
シナリオの書き方は [rism2/docs/SCENARIO_SCHEMA.md](../../modules/scenario_manager/rism2/docs/SCENARIO_SCHEMA.md)、設定の項目は [rism2/docs/CONFIG.md](../../modules/scenario_manager/rism2/docs/CONFIG.md) を参照してください。

## 日常の操作

`deploy/<ロボットID>/`（別のサーバに置いた場合は `config/` または `robot/`）の中で実行します。

```bash
docker compose ps                    # 状態
docker compose logs -f mongo-robot   # ログ（設定DB は mongo-config。10MB × 3 世代でローテーション）
docker compose stop                  # 停止（データは残る）
docker compose up -d                 # 再開
docker compose down                  # コンテナ削除（データはデータのディレクトリに残る）
```

compose ファイルを作り直すときは、`setup_mongo.sh` を実行し直します（前回の答えを使う場合は `--answers deploy/<ロボットID>/install_answers.json`。compose ファイルだけを作る場合は `--compose-only` も付ける）。

## 既存データの持ち込み

持ち込み先は、ロボットDB のデータディレクトリ `<データを置くディレクトリ>/mongodb_for_<ロボットID>/` です。

### mongodump / mongorestore（推奨）

移行元が動いたままでも、整合の取れたデータを取れます。

移行元で：
```bash
# 移行元がこの構成（setup_mongo.sh で作ったもの）の場合。deploy/<ロボットID>/ の中で
docker compose exec -T mongo-robot sh -c 'mongodump --port $MONGO_PORT --oplog --gzip --archive' > mongo.archive.gz

# 移行元が旧構成（setup/mongo_docker/docker-compose.yml と mongo.env）の場合
docker compose --env-file mongo.env exec -T mongo sh -c 'mongodump --port $MONGO_PORT --oplog --gzip --archive' > mongo.archive.gz
```
- `-T` を必ず付けてください。付けないと出力が壊れます。
- 書き出し先のディスクの空きを先に確認してください。移行元のディスクが一杯になると、MongoDB が書き込めなくなります。
- 全件を読むので、その間は移行元が重くなります。ロボットを動かしていない時間帯に行ってください。

移行先で、「1台目のロボット」の手順1〜3（または「2台目以降のロボット」）で空の状態で起動して healthy になってから、`deploy/<ロボットID>/` の中で：
```bash
docker compose exec -T mongo-robot sh -c 'mongorestore --port $MONGO_PORT --gzip --archive --oplogReplay' < mongo.archive.gz
```

その後、`setup_mongo.sh --answers ...` で設定DB の設定を入れます。標準データは、同じ `_id` のドキュメントがあれば入れません（`--overwrite` を付けなければ、持ち込んだデータは上書きされません）。  
※mongorestore と `--answers` をこの順に実行する手順は、まだ確認していません。

### データファイルを直接コピーする

**移行元の mongod を止めてから**コピーしてください。
動いたままコピーするとファイルが壊れ、`mongod --repair` でも直らないことがあります。

```bash
# 移行元を止める（この構成の場合は deploy/<ロボットID>/ の中で docker compose stop。
#               旧構成の場合は docker compose --env-file mongo.env stop）
rsync -aH --numeric-ids <移行元のデータディレクトリ>/ <データを置くディレクトリ>/mongodb_for_<ロボットID>/
```
- 移行元のデータディレクトリは、`data`・`config`・`var_cache` を含むディレクトリです（旧構成では `mongo.env` の `MONGO_DATA_DIR`、この構成では `mongodb_for_<ロボットID>/`）。
- 移行先では、所有者を MongoDB を動かすユーザー（uid:gid）に直し、MongoDB のイメージ（`.env` の `MONGO_IMAGE`）を移行元と同じメジャーバージョンにして起動します。
- レプリカセットのメンバー名は、移行元のホスト名のまま入っています。これは healthcheck（`rs-healthcheck.js`）が `.env` の `MONGO_PUBLIC_HOST` に自動で書き換えます。

## 稼働中の旧構成から移行するときの注意

旧構成（`setup/mongo_docker/docker-compose.yml` と `mongo.env` で起動していたもの）から移行するときは、次の点に注意してください。

1. **ポートが重なる**  
   新しい構成の既定のポート（設定DB 9100、ロボットDB 9110 など、Web UI はそれぞれ+1）は、旧構成で使っていたポートと重なることがあります。
   同じサーバで旧構成の MongoDB が動いたままだと、新しい構成は起動できません。`docker ps` で使用中のポートを確認し、旧構成のコンテナを止めてから起動するか、対話で重ならないポートを答えてください。
2. **データディレクトリの階層が違う**  
   旧構成は `MONGO_DATA_DIR` の直下に `data`・`config`・`var_cache` を置いていました。
   新しい構成は `<データを置くディレクトリ>/mongodb_for_rism_config/` と `<データを置くディレクトリ>/mongodb_for_<ロボットID>/` の下に置きます。
   旧構成のデータを使う場合は、「既存データの持ち込み」に従って `mongodb_for_<ロボットID>/` へ移してください。
3. **旧ロボットDB の `rism_configs.rism_config` の値は `robot_list` / `common` に移す**  
   旧構成では、ロボットDB の `rism_configs.rism_config` に、ロボット側のプログラムの設定（Google 音声認識中継サーバ、音声認識の角度、認識してよい範囲、人物設定、OpenWeatherMap の API キーなど）を書いていました。
   今は、ロボット側のプログラム（pyindy の `load_robot_settings`）は設定DB の `rism_configs.robot_list`（そのロボットの文書）と `rism_configs.common` を読み、ロボットDB の `rism_configs.rism_config` は読みません。
   旧データの値を使う場合は、Web UI で設定DB の `robot_list` / `common` に移してください（項目は [rism2/docs/CONFIG.md](../../modules/scenario_manager/rism2/docs/CONFIG.md) の「ロボットごとの設定」「全ロボット共通の設定」を参照）。

## ポートの割り当て

| ロボット | MongoDB | Web UI（mongo-express） |
|---|---|---|
| indy_environment | 9000 | 9001 |
| indy1 / indy2 / indy3 / indy4 | 9010 / 9020 / 9030 / 9040 | 9011 / 9021 / 9031 / 9041 |
| 設定DB（rism_configs） | 9100 | 9101 |
| indy1e / indy2e / indy3e / indy4e | 9110 / 9120 / 9130 / 9140 | 9111 / 9121 / 9131 / 9141 |
| environment_s | 9300 | 9301 |
| indy1s | 9310 | 9311 |

- ロボットDB の既定のポートは、ロボットの番号 N に対して 9100 + 10 × N です。
- 同じサーバでは、Web UI がポート+1 を使うため、MongoDB のポートは 2 つ以上離します。
- 9000 は旧シナリオマネージャの設定DB のポートのため、設定DB のポートには使えません（ツールが受け付けません）。

## 設計上の注意

### レプリカセット
MongoDB は、メンバー 1 つのレプリカセット `rs0` として動きます（rism2 は変更ストリームで観測を受け取るため）。
メンバー名は `<MONGO_PUBLIC_HOST>:<ポート>` です（`MONGO_PUBLIC_HOST` は `.env`、対話で答えたホスト名）。`?replicaSet=rs0` を付けて接続するクライアントは、この名前で接続し直します。
そのため、ロボットからこの名前が引けない場合は、接続文字列に `?directConnection=true` を付けてください。

ホスト名が IP アドレスや `localhost` でない場合、コンテナ内では `MONGO_PUBLIC_HOST` をホスト自身に向けています（`extra_hosts: host-gateway`）。
mongod がメンバー名を自分自身だと確認できるようにするためで、サーバのホスト名が DNS に登録されていなくても動きます。

healthy にならないときは、`docker compose logs mongo-robot`（設定DB は `mongo-config`）を見て、データのディレクトリの持ち主が MongoDB を動かすユーザーか、コンテナの中から `<ホスト名>:<ポート>` に届くか（ホストのファイアウォールが Docker からホストのポートへの通信を止めていないか）を確認してください。

### メモリ
mongod は、何も指定しないと「(搭載メモリ − 1GB) × 50%」をキャッシュに使います。
サーバでは音声認識や LLM なども動くので、`docker-compose.indy.yml` で上限を決めています（対話の「MongoDB のキャッシュ上限」、既定 1GB）。
1 台のサーバで複数の MongoDB を動かすときは、「起動数 × 値」が搭載メモリの半分程度に収まるようにします。
データが大きく、検索が遅い場合は増やしてください（`setup_mongo.sh` を実行し直して compose ファイルを作り直す）。
