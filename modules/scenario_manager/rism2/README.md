# RISM2 - Robot Interactive Scenario Manager

MongoDB に置いたシナリオを読み、ロボットへの動作を MongoDB 経由で送るシナリオマネージャ。
ロボットのセンサーが書いた観測（顔検出、音声認識、人数、バッテリなど）を見て、次のシナリオを選び、割り込みを起こす。

- シナリオ・サブシナリオ（割り込み）を条件と優先度で選んで実行する
- 移動中の割り込みでは、移動を止めて話し、終わったら送り直す
- 発話は定型文のほか、LLM などの Event Generator で作れる（次の発話は先に作っておく）
- 実行中の状態を `tBlackBoard.current_state` に書く

## 文書

| 文書 | 内容 |
|---|---|
| [docs/SCENARIO_SCHEMA.md](docs/SCENARIO_SCHEMA.md) | シナリオの書き方（フィールド、条件、イベント、動作、Event Generator） |
| [docs/OBSERVATIONS.md](docs/OBSERVATIONS.md) | 観測イベントの形（ロボット側が physical_topic に書くもの） |
| [docs/CONFIG.md](docs/CONFIG.md) | 設定（rism_config）の項目・型・既定値と、ロボットごとの設定 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | しくみ（流れ、モジュール、読み書きする DB、割り込みの決まり、current_state） |
| [docs/ACTION_DB_VERSION_ROUTING.md](docs/ACTION_DB_VERSION_ROUTING.md) | Actions の v1.0 / v2.0 の形 |
| [docs/IS_NAVIGATING_FLAG.md](docs/IS_NAVIGATING_FLAG.md) | `is_navigating` の扱い |
| [docs/TODO.md](docs/TODO.md) | 保留中の検討 |

`src/rism2/schemas/scenario.schema.json` と `src/rism2/schemas/observation.schema.json` は、シナリオと観測の形の定義。
RISM は読んだシナリオと届いた観測をこれで検査し、合わなければ警告をログに出す（実行は止めない）。

## セットアップ

### 1. RISM を入れる

Python 3.10 以上と [uv](https://docs.astral.sh/uv/) を使う。

```bash
git clone <このリポジトリ> && cd <フォルダ>
uv sync                  # 依存（pymongo, jsonschema, pyindy など）を .venv に入れる。テスト用の pytest と mongomock も入る
uv sync --extra viz      # 割り込みキューの表示（rich）も使うとき
```

ロボットへの動作は pyindy（`pyindy.mongo`）で送る。pyindy の場所は `pyproject.toml` の `[tool.uv.sources]` に書く。

### 2. MongoDB を用意する（対話のインストーラ）

RISM は2種類の MongoDB を使う。ロボットごとにロボットDB を1つ用意する。

| DB | 既定のポート | 中身 |
|---|---|---|
| 設定DB | 9100 | `rism_configs`（rism_config: 全体の設定、robot_list: ロボットごとの設定、demo_list: デモがどのシナリオDBを使うか） |
| ロボットDB | ロボット 1, 2, 3, ... に 9110, 9120, 9130, ...（9100 + 10 × 番号） | `tBlackBoard`（観測、Actions、current_state など）と `demo_configs`（シナリオ） |

Web UI は、それぞれのポート+1（9101、9111、9121、...）で開く。

`tools/install.py` が、対話で聞きながら次をする。

1. MongoDB と Web UI の docker compose ファイルを作る
   - 設定DB とロボットDB が**同じサーバ**なら、`deploy/` に `docker-compose.yml`・`.env`・`rs-healthcheck.js`
   - **別のサーバ**なら、`deploy/config/`（`docker-compose.config.yml` など、設定DB のサーバ用）と
     `deploy/robot/`（`docker-compose.robot.yml` など、ロボットDB のサーバ用）の2つのフォルダ
   - **2台目からのロボット**（設定DB がもうある）なら、ロボットDB だけの `docker-compose.yml` など
2. 答えを `install_answers.json` に保存する
3. MongoDB が起動していれば、RISM を動かすのに要る設定とサンプルのシナリオを DB に入れる（何を入れるか見せてから書く）

```bash
uv run python tools/install.py
```

聞かれること:

| 質問 | 既定 | 説明 |
|---|---|---|
| 設定DB も新しく作るか | はい | 1台目ははい。2台目からのロボットで設定DB がもうあれば、いいえ（ロボットDB だけ作り、今の設定DB にロボットを足す） |
| 同じサーバに置くか | はい | 設定DB を作るときだけ聞く。いいえなら、フォルダを2つに分ける |
| ホスト名 | このマシンの名前 | RISM とロボットがつなぐ名前（例 `db.example.local`）。レプリカセットのメンバー名になるので、つなぐ側から引ける名前にする |
| 設定DB のポート | 9100 | |
| ロボットの番号 | 1 | ロボットDB のポートの既定が 9100 + 10 × 番号（1 なら 9110）になる |
| ロボットDB のポート | 9110 | 番号から決まるもの以外にもできる。同じサーバでは、Web UI がポート+1 を使うので、設定DB と2つ以上離す |
| Web UI | mongo-express | mongo-express（DB ごとに1つ、ポート+1）、DbGate（1つで全部、最初の DB のポート+1）、なし。どれもログインなし |
| データを置くディレクトリ | /srv/rism2/mongodb | DB のデータを置くホストの絶対パス。この下に `mongodb_for_rism_config/` と `mongodb_for_<ロボットID>/`（それぞれ `data`・`config`・`var_cache`）を使う |
| MongoDB を動かすユーザー | 1001:1001 | uid:gid。データのディレクトリはこのユーザーの持ち物にする |
| フォルダ | deploy | compose ファイルと `install_answers.json` を置く（git に入れない）。ロボットごとに分けるなら `deploy/robot2` など |
| ロボットの ID・表示名・デモの ID | `robot<番号>` | robot_list・demo_list に入れる。デモの ID（既定 `<ロボットID>_demo`）は main.py の `--demo` |
| LLM の URL・モデル | localhost:8001/v1、indy-instruct | 発話を作る LLM サーバ（OpenAI 互換） |
| サンプルを入れるか | はい | `samples/` のシナリオと知識。いいえなら設定だけ |

MongoDB を起動する（設定DB とロボット1 を同じサーバに置いた場合）。インストーラが最後に、そのとおりのコマンドを出す:

```bash
# 初めてのときだけ、データのディレクトリを作り、MongoDB を動かすユーザーの持ち物にする
sudo mkdir -p /srv/rism2/mongodb/mongodb_for_rism_config/{data,config,var_cache} \
              /srv/rism2/mongodb/mongodb_for_robot1/{data,config,var_cache}
sudo chown -R 1001:1001 /srv/rism2/mongodb/mongodb_for_rism_config /srv/rism2/mongodb/mongodb_for_robot1

cd deploy
docker compose up -d
docker compose ps        # mongo-config と mongo-robot が healthy になるまで待つ
```

- 別のサーバの場合は、`deploy/config/` を設定DB のサーバへ、`deploy/robot/` をロボットDB のサーバへフォルダごとコピーし、
  それぞれのサーバでディレクトリを作ってから、そのフォルダの中で `docker compose -f <ファイル> up -d` を実行する
- 2台目からのロボットは、`deploy/robot2` などの別のフォルダに作り、ロボットDB を置くサーバでそのフォルダの中で
  `docker compose up -d` を実行する（compose のプロジェクト名が `rism2-<ロボットID>` なので、1台目とぶつからない）

起動したら、保存した答えを使って設定を DB に入れる（もう聞かない。入れる前に確かめる）:

```bash
uv run python tools/install.py --answers deploy/install_answers.json
```

- MongoDB はレプリカセット `rs0` で動く（RISM は変更ストリームで観測を受け取るため）。メンバー名は `.env` の
  `MONGO_PUBLIC_HOST` とポート。healthcheck が `rs-healthcheck.js` で、最初の起動時にレプリカセットを作り、
  メンバー名が違っていれば（`.env` のホスト名を変えたときなど）直す
- データはホストのディレクトリに残る（`docker compose down` しても消えない）
- Web UI は `http://<ホスト名>:<ポート+1>/`（例 http://db.example.local:9101/）。ログインがないので、外から入れないネットワークで使う
- healthy にならないとき: `docker compose logs mongo-config`。データのディレクトリの持ち主が MongoDB を動かすユーザーか、
  コンテナの中から `<ホスト名>:<ポート>` に届くか（ホストのファイアウォールが docker からホストのポートへの通信を止めていないか）を見る
- 版は固定（MongoDB 8.0.34 は `.env` の `MONGO_IMAGE`、mongo-express 1.0.2、DbGate 7.3.3）。作るときの版は `tools/install.py` の先頭

### DB に設定だけ入れる（MongoDB がもうあるとき）

`tools/setup_db.py` は、インストーラが中で使うもの。直接使うこともできる。

```bash
uv run python tools/setup_db.py --host db.example.local --scenario-port 9110 --robot-id robot1 \
  --llm-url http://llm.example.local:8001/v1 --llm-model <モデル名> --dry-run   # 何を入れるか確認
```

- 設定DB（`--config-host` `--config-port`、既定 9100）の `rism_configs` に rism_config・robot_list・demo_list を入れる
- ロボットDB（`--scenario-host` `--scenario-port`、既定 9110）の `demo_configs` に `samples/` のシナリオと知識を入れる。
  ロボット2 なら `--scenario-port 9120`
- 設定DB とロボットDB が同じサーバなら `--host` だけでよい（別なら `--config-host` と `--scenario-host`）
- 同じ名前の文書があれば入れない（`--update` で置き換える）。`--only config` などで一部だけ入れられる
- サンプルの移動先と充電ステーションの座標は、使う場所に合わせて直す
- サンプルは `samples/` の JSON を編集する。別の文書は `"@名前"`、ロボットの ID は `"{robot_id}"` と書く

## 起動

```bash
uv run python main.py --robots robot1 --demo robot1_demo --host db.example.local --port 9100
```

| 引数 | 内容 |
|---|---|
| `--robots` | ロボット ID（`robot_list` のキー）。複数書ける。必須 |
| `--demo` | デモ ID（`demo_list` のキー）。必須 |
| `--entry_point` | 最初に実行するシナリオの ID。なければ条件に合うシナリオから選ぶ |
| `--host` `--port` | 設定 DB のホストとポート（ポートの既定 9100）。ホストは毎回指定する |
| `--loglevel` | ログレベル（既定 INFO） |

止めるときは SIGTERM か SIGINT（Ctrl+C）を送る。割り込みの検知と観測の監視を止め、まだ始まっていない動作を取り消してから終わる。
起動時に設定を検査し、知らない項目や型の違う値を `[Settings]` の警告としてログに出す。

## テスト

```bash
uv run pytest tests                 # すべて（3分ほど）
uv run pytest tests/test_e2e.py     # 通しのテストだけ
```

`tests/test_e2e.py` は、ロボットも MongoDB もなしで、シナリオを最初から最後まで流すテスト。
`tests/e2e_harness.py` の `RismSimulation` が、MongoDB を mongomock の偽 DB に、ロボットを
Actions の動作を完了にしていく偽のロボットに置き換えて、本物の `ScenarioInterpreter` を動かす。

```python
with RismSimulation(scenarios=[...], subscenarios=[...]) as sim:
    sim.start("見回り")
    sim.observe("face_detected", {"instance_id": 1})   # センサーの代わりに観測を入れる
    sim.wait_for_speech("こんにちは")                   # ロボットに送られた発話を待つ
```

`tests/test_basic.py` は、本物の設定 DB につないで確かめるスクリプト（`uv run python tests/test_basic.py`）。

## ディレクトリ

```
main.py                 起動
src/rism2/              本体（モジュールの役割は docs/ARCHITECTURE.md）
  event_generators/     発話を作る Event Generator
src/rism2/schemas/      シナリオと観測のスキーマ（実行時に読む）
samples/                サンプルのシナリオ・サブシナリオ・知識（tools/setup_db.py が入れる）
tools/                  インストーラ（install.py）、DB の準備（setup_db.py）、ログの解析（analyzer）。実行には使わない
tests/                  テスト（e2e_harness.py は通しのテストの土台）
docs/                   文書
```

## 困ったとき

| 症状 | 見るところ |
|---|---|
| 起動しない | 設定 DB につながるか（`mongosh --host <ホスト> --port 9100`）、`rism_configs.rism_config` があるか（なければ tools/install.py） |
| シナリオが始まらない | シナリオ DB の `scenarios` に `status: "active"` で条件に合うものがあるか。ログの `[SchemaCheck]` |
| 割り込みが起きない | 観測が届いているか（ログの `New observation`）、`[ObservationCheck]` の警告、サブシナリオの `status`・`condition`・`ignore_after_activated`・`interruption_probability` |
| 動作が実行されない | `tBlackBoard.Actions` に `waiting` のまま残っていないか（ロボット側が拾っているか） |
| 設定が効かない | ログの `[Settings]` の警告（項目名の打ち間違いなど）。項目は docs/CONFIG.md |
