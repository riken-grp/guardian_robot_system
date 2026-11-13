# MongoDB（サーバマシン用）

ロボットが記憶・設定・ログの保存に使う MongoDB を、Docker Compose で起動します。
標準では**ロボット 1 台分**として、MongoDB を 1 つと、その Web 管理画面 mongo-express を起動します。
同じサーバで複数台分を動かす方法は、「複数台分を起動する（オプション）」を参照してください。

## 構成

| ファイル | 内容 |
|---|---|
| `docker-compose.yml` | MongoDB と mongo-express の定義 |
| `mongo.env.sample` | MongoDB サーバ用の設定の雛形。`mongo.env` にコピーして使う（`*.env` は git 管理外）。ロボット・ROS 側の `indy.env` とは別のファイル |
| `rs-healthcheck.js` | レプリカセットの初期化・メンバー名の修正・状態確認を行う healthcheck |
| `default_data/` | 標準データ（設定系コレクションの JSON。`<db>.<collection>.json`） |
| `import_default_data.sh` | 標準データを投入するスクリプト |

データはリポジトリの外（`mongo.env` の `MONGO_DATA_DIR`）に置きます。

`mongo.env` は、docker compose が自動では読まないファイル名にしてあります（ロボット側の `indy.env` と区別するため）。
**`docker compose` のコマンドには、毎回 `--env-file mongo.env` を付けてください。** 付け忘れると、設定不足のエラーで止まります。

**注意：シェルの環境変数は `--env-file` より優先されます。**
docker compose は、同じ名前の変数がシェルで export されていると、`--env-file` のファイルの値ではなくシェルの値を使います。
サーバで `~/indy.env` を読み込んでいると `MONGO_PORT` が export されているため、`mongo.env` の `MONGO_PORT` と値が違うと、シェル側の値で起動してしまいます。
また、`set -a; . ./mongo_xxx.env` のように env ファイルをシェルに読み込むと、その値が以後のコマンドに残ります。
値が異なる場合は、次のどちらかで回避してください。

- `env -u MONGO_PORT docker compose --env-file mongo.env ...` のように、シェルの変数を外して実行する
- env ファイルをシェルに読み込むときは、`( ... )` のサブシェル内で行い、値をシェルに残さない

## 前提

- Docker Engine と Docker Compose v2（`docker compose` コマンド）
- 起動するユーザが `docker` グループに入っていること（入っていなければ以下のコマンドに `sudo` を付ける）
- ロボットから、このサーバのホスト名が名前解決でき、`MONGO_PORT` に到達できること

## セットアップ

### 1. `mongo.env` を作る

```bash
cd $GUARDIAN_ROBOT_PATH/setup/mongo_docker
cp mongo.env.sample mongo.env
```

`mongo.env` の各項目を書き換えます。

| 変数 | 既定 | 内容 |
|---|---|---|
| `MONGO_PUBLIC_HOST` | （必須） | ロボットから到達できる、このサーバのホスト名または IP アドレス。ロボットの `MONGO_URI` と同じ値 |
| `MONGO_PORT` | （必須） | MongoDB のポート。ロボットの `MONGO_PORT` と同じ値 |
| `ME_PORT` | 8081 | mongo-express のポート |
| `MONGO_IMAGE` | （必須） | MongoDB のイメージ。既存データを持ち込む場合は、そのデータと同じメジャーバージョン |
| `MONGO_DATA_DIR` | （必須） | データの置き場所 |
| `MONGO_UID` / `MONGO_GID` | 1001 | mongod を動かす uid / gid。データディレクトリの所有者と合わせる |
| `MONGO_CACHE_GB` | 1 | キャッシュの上限（GB）。後述 |
| `ME_IMAGE` | mongo-express:1.0.2 | mongo-express のイメージ（任意。通常は変更不要） |
| `ME_BIND_ADDR` | 0.0.0.0 | mongo-express を公開するアドレス。`0.0.0.0` で同じネットワーク内の他のマシンから開ける（認証が無いため、信頼できるネットワーク内でのみ使う）。このマシンからのみに限定するときは `127.0.0.1` |

### 2. データディレクトリを作る

**`docker compose up` より前に**作り、所有者を `MONGO_UID` / `MONGO_GID` に合わせます。
作らずに起動すると Docker が root 所有で作ってしまい、mongod が書き込めず起動に失敗します。

```bash
( set -a; . ./mongo.env; set +a
  mkdir -p "$MONGO_DATA_DIR"/{data,config,var_cache}
  sudo chown -R "$MONGO_UID:$MONGO_GID" "$MONGO_DATA_DIR" )
```
（サブシェル `( ... )` で実行し、`mongo.env` の値をシェルに残さないようにしています。）

### 3. 起動する

```bash
docker compose --env-file mongo.env config -q     # 設定漏れがあればここでエラーになる
docker compose --env-file mongo.env up -d
docker compose --env-file mongo.env ps            # mongo が (healthy) になれば完了
```

初回は、healthcheck がレプリカセットを自動で初期化します。healthy になるまで 20〜30 秒ほどかかります。
mongo-express は、MongoDB が healthy になってから起動します。

### 4. 確認する

- mongo-express：ブラウザで `http://<MONGO_PUBLIC_HOST>:<ME_PORT>/`（`ME_BIND_ADDR=127.0.0.1` の場合は、このマシンのブラウザで `http://127.0.0.1:<ME_PORT>/`）
- 接続確認：
  ```bash
  docker compose --env-file mongo.env exec mongo sh -c 'mongosh --quiet --port $MONGO_PORT --eval "rs.status().members[0].name"'
  ```
  `<MONGO_PUBLIC_HOST>:<MONGO_PORT>` と表示されれば正常です。

### 5. 標準データを入れる

ロボットを動かすのに必要な設定（パラメータ、シナリオ、プロンプト、声、動作など）を、空の MongoDB に入れます。
既存の環境からデータを引き継ぐ場合は不要です（「既存データの持ち込み」を参照）。

```bash
./import_default_data.sh <ROBOT_NAME>      # ロボット側 indy.env の ROBOT_NAME と同じ値
```

- スクリプトは既定で `mongo.env` を読みます。
- `__ROBOT_NAME__`、`__MONGO_HOST__`（`mongo.env` の `MONGO_PUBLIC_HOST`）、`__MONGO_PORT__`（`mongo.env` の `MONGO_PORT`）は、スクリプトが置き換えます。
- 既に同じ `_id` のドキュメントがある場合は上書きしません。標準データの内容で上書きしたいときは `--overwrite` を付けます（標準データに無いドキュメントは削除されません）。
- 複数台分を起動している場合は、`-p <名前> --env-file mongo_<名前>.env` を付けます。

投入後、次のプレースホルダを mongo-express などで環境に合わせて書き換えます（スクリプトの最後にも一覧が出ます）。

| プレースホルダ | 場所 | 内容 |
|---|---|---|
| `__LLM_HOST__` | `robot_config.system_parameters`（memory / llm_responder）、`rism_configs.rism_config` | LLM サーバ（OpenAI 互換 API）のホスト |
| `__EMBED_HOST__` | `robot_config.system_parameters`（memory / llm_responder） | 埋め込み API のホスト |
| `__TTS_HOST__` | `persona.Voice` | 音声合成サーバのホスト（`type` が `hoya` のとき使用） |
| `__ADIN_SERVER__` | `robot_config.system_parameters`（asr） | 音声認識の入力（adintool）サーバの IP |
| `__AUDIO_IP__` | `robot_config.system_parameters`（ros_audio_tracker） | 音声の送り先の IP |
| `__GOOGLE_ASR_SERVER__` | `rism_configs.rism_config` | Google 音声認識中継サーバの IP |
| `__OPENWEATHERMAP_TOKEN__` | `rism_configs.rism_config` | OpenWeatherMap の API キー（天気の話題で使用） |

標準データの中身：

| コレクション | 内容 |
|---|---|
| `robot_config.system_parameters` | 各モジュールのパラメータ（human_tracker / ros_audio_tracker / asr / sensor_tf / memory / llm_responder / gestures_modes / map_server） |
| `rism_configs.*` | シナリオ管理の設定（`rism_config`）、シナリオ、割り込み・対話サブシナリオ、ロボットの人物設定 |
| `memory_settings.llm_prompts` / `module_settings` | LLM のプロンプト、記憶モジュールの設定 |
| `persona.Voice` / `ActionPrimitives` | 声の設定、ジェスチャーの定義 |
| `tBlackBoard.internal_state` | シナリオ管理の初期状態 |

## 日常の操作

```bash
docker compose --env-file mongo.env ps                # 状態
docker compose --env-file mongo.env logs -f mongo     # ログ（10MB × 3 世代でローテーション）
docker compose --env-file mongo.env stop              # 停止（データは残る）
docker compose --env-file mongo.env up -d             # 再開
docker compose --env-file mongo.env down              # コンテナ削除（データは MONGO_DATA_DIR に残る）
```

## 既存データの持ち込み

### mongodump / mongorestore（推奨）

移行元が動いたままでも、整合の取れたデータを取れます。

移行元（この構成で動いているサーバ）で：
```bash
docker compose --env-file mongo.env exec -T mongo sh -c 'mongodump --port $MONGO_PORT --oplog --gzip --archive' > mongo.archive.gz
```
- `-T` を必ず付けてください。付けないと出力が壊れます。
- 書き出し先のディスクの空きを先に確認してください。移行元のディスクが一杯になると、MongoDB が書き込めなくなります。
- 全件を読むので、その間は移行元が重くなります。ロボットを動かしていない時間帯に行ってください。

移行先で、空の状態で起動して healthy になってから：
```bash
docker compose --env-file mongo.env exec -T mongo sh -c 'mongorestore --port $MONGO_PORT --gzip --archive --oplogReplay' < mongo.archive.gz
```

### データファイルを直接コピーする

**移行元の mongod を止めてから**コピーしてください。
動いたままコピーするとファイルが壊れ、`mongod --repair` でも直らないことがあります。

```bash
# 移行元
docker compose --env-file mongo.env stop
rsync -aH --numeric-ids <移行元の MONGO_DATA_DIR>/ <移行先の MONGO_DATA_DIR>/
docker compose --env-file mongo.env start
```
移行先では、所有者を `MONGO_UID` / `MONGO_GID` に直し、`MONGO_IMAGE` を移行元と同じメジャーバージョンにして起動します。
レプリカセットのメンバー名は、移行元のホスト名のまま入っています。これは healthcheck が `MONGO_PUBLIC_HOST` に自動で書き換えます。

## 複数台分を起動する（オプション）

1 台のサーバで複数のロボットの MongoDB を動かすときは、ロボットごとに env ファイル（`mongo_<ロボット名>.env`）を作ります。
そのうえで、`-p`（プロジェクト名）と `--env-file` を変えて、同じ `docker-compose.yml` を起動します。
プロジェクトごとにコンテナとネットワークが分かれるので、互いに干渉しません。

```bash
cd $GUARDIAN_ROBOT_PATH/setup/mongo_docker
cp mongo.env.sample mongo_indy1e.env      # MONGO_PORT / ME_PORT / MONGO_DATA_DIR をロボットごとに変える
cp mongo.env.sample mongo_indy2e.env

# env ファイルごとに、データディレクトリを作って所有者を合わせる（サブシェルで実行し、値をシェルに残さない）
for f in mongo_indy1e.env mongo_indy2e.env; do
  ( set -a; . ./$f; set +a
    mkdir -p "$MONGO_DATA_DIR"/{data,config,var_cache}
    sudo chown -R "$MONGO_UID:$MONGO_GID" "$MONGO_DATA_DIR" )
done

env -u MONGO_PORT docker compose -p indy1e --env-file mongo_indy1e.env up -d
env -u MONGO_PORT docker compose -p indy2e --env-file mongo_indy2e.env up -d
env -u MONGO_PORT docker compose -p indy1e --env-file mongo_indy1e.env ps     # 以後の操作も env -u MONGO_PORT・-p・--env-file を付ける
./import_default_data.sh -p indy1e --env-file mongo_indy1e.env indy1e
```

- `MONGO_PORT`・`ME_PORT`・`MONGO_DATA_DIR` は、ロボットごとに重ならないようにします。
- `~/indy.env` を読み込んだシェルでは `MONGO_PORT` が export されており、各 env ファイルの `MONGO_PORT` より優先されます。上の例のように `env -u MONGO_PORT` を付け、シェルの `MONGO_PORT` を外して実行してください。
- `MONGO_CACHE_GB` は、「起動数 × 値」が搭載メモリの半分程度に収まるようにします。
- `-p` を付けずに起動すると、プロジェクト名がディレクトリ名（`mongo_docker`）になり、別のロボットの分を上書きします。

ポートの割り当て（例）：

| ロボット | MongoDB | mongo-express |
|---|---|---|
| indy_environment | 9000 | 9001 |
| indy1 / indy2 / indy3 / indy4 | 9010 / 9020 / 9030 / 9040 | 9011 / 9021 / 9031 / 9041 |
| indyXe_environment | 9100 | 9101 |
| indy1e / indy2e / indy3e / indy4e | 9110 / 9120 / 9130 / 9140 | 9111 / 9121 / 9131 / 9141 |
| environment_s | 9300 | 9301 |
| indy1s | 9310 | 9311 |

## 設計上の注意

### レプリカセット
MongoDB は、メンバー 1 つのレプリカセット `rs0` として動きます。
メンバー名は `<MONGO_PUBLIC_HOST>:<MONGO_PORT>` です。`?replicaSet=rs0` を付けて接続するクライアントは、この名前で接続し直します。
そのため、ロボットからこの名前が引けない場合は、接続文字列に `?directConnection=true` を付けてください。

コンテナ内では、`MONGO_PUBLIC_HOST` をホスト自身に向けています（`extra_hosts: host-gateway`）。
mongod がメンバー名を自分自身だと確認できるようにするためで、サーバのホスト名が DNS に登録されていなくても動きます。

### メモリ
mongod は、何も指定しないと「(搭載メモリ − 1GB) × 50%」をキャッシュに使います。
サーバでは音声認識や LLM なども動くので、`MONGO_CACHE_GB` で上限を決めています（既定 1GB）。
データが大きく、検索が遅い場合は増やしてください。
