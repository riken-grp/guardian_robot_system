# シナリオDBのスキーマ

シナリオDB（`demo_configs`）の文書の形を説明する。
機械で検証するための定義は `src/rism2/schemas/scenario.schema.json` にある。
メインシナリオは `#/$defs/scenario`、割り込みサブシナリオは `#/$defs/subscenario` で検証する。
スキーマに合わない文書は読み込み時に警告するが、実行は止めない。

## コレクション

| コレクション | 中身 |
|---|---|
| `scenarios` | メインシナリオ。active なものから priority の重みで次に実行するものを選ぶ |
| `interruption_subscenarios` | 割り込みサブシナリオ。condition に合う観測が来たら割り込んで実行する |

## シナリオとサブシナリオの共通フィールド

| フィールド | 型 | 意味 |
|---|---|---|
| `name` | 文字列 | 名前（必須） |
| `status` | `active` / `inactive` | inactive は自動では選ばれない。next_scenarios からは実行できる（必須） |
| `version` | `"2.0"` | 形式のバージョン |
| `priority` | 0〜1000 の整数 | 大きいほど優先（既定 1）。下の「優先度」を参照 |
| `condition` | 条件 | メインシナリオ: 選ばれる条件（空なら常に候補）。サブシナリオ: 発動の条件（必須） |
| `events` | イベントの配列 | 実行する内容（必須） |
| `next_scenarios` | ID の配列 | 次に実行するシナリオの候補。要素を配列にするとその中から選ぶ |
| `ignore_interruptions` | ID の配列 | このシナリオの実行中は発動させないサブシナリオ |
| `exit_condition` | 条件、または条件の配列 | 開始後にこの観測が来たら、このシナリオを打ち切る。配列ならどれか1つが合えば打ち切る |
| `exit_events` | イベントの配列、または {イベント名: イベントの配列} | exit_condition で打ち切ったときに実行する。イベント名ごとに書くと、打ち切ったきっかけの観測のものを実行する |

## 優先度（priority）

`priority` は 0〜1000 の整数で、大きいほど優先する。範囲外の値は範囲に収め、数値でない値は 1 として扱う。
0 は重み 0 で、条件の合うほかの候補（1 以上）があれば選ばない。候補が全部 0 のときだけ、その中から同じ確率で選ぶ。

- メインシナリオ: 次に実行するシナリオを、候補の中から priority を重みにして選ぶ（100 と 1 なら 100:1 の割合）
- サブシナリオ: 同時に条件が合ったときは priority を重みにして1つ選ぶ。キューにたまった割り込みは priority の大きい順に実行する

priority は順番と選ばれやすさだけを決める。移動中にナビを止めるかは `important` / `navigation_interrupt_mode` で、
実行中の動作の後に回すかは `interruptable` で決める。

目安:

| 範囲 | 使いどころ | 例 |
|---|---|---|
| 1〜99 | ロボット自身の小さな動き、移動の指示 | まばたき、視線、go_to_* |
| 100〜499 | あいさつ、音声コマンド、QR コードなど | 顔検知のあいさつ、〇〇の部屋を見てきて |
| 500〜999 | 人への反応を優先したいもの | 挙手への反応、音声対話 |
| 1000 | 安全・電池 | バンパー衝突、バッテリ補充、バッテリ補充（緊急）、バッテリ復活 |

## サブシナリオだけのフィールド

| フィールド | 型 | 意味 |
|---|---|---|
| `resume_after` | `resume` / `terminate` / `next_event` / `restart` | 終わった後の戻り方。resume: 元のシナリオの続きから（既定）。terminate: 元のシナリオを終えて next_scenarios へ。next_event: 割り込まれたイベント（動作の完了待ちや返事待ち）の残りを飛ばして次のイベントから。restart: 割り込まれたイベントをやり直す。イベントの合間に入った割り込みでは、next_event / restart も resume と同じ |
| `important` | 真偽 | 移動中でもナビを止めて実行する。interruption_probability にかかわらず必ず発動する。`interruptable: false` のイベントの直後でも、次のイベントの前に実行する |
| `force_interrupt` | 真偽 | 旧形式。`important` と同じ意味として読む。新しく書くときは `important` を使う |
| `navigation_interrupt_mode` | `parallel` / `suspend_and_resume` / `wait_completion` | 移動中の扱いを直接指定する |
| `navigation_wait_timeout` | 数値 | wait_completion で移動の終わりを待つ秒数 |
| `ignore_after_activated` | 数値 | 発動してからこの秒数は発動しない |
| `interruption_probability` | 0〜1 の数値 | 発動させる確率。なければ rism_config の `interruption_probability`（important なら常に発動） |
| `ignore_same_observations` | 真偽 | 発動したとき、まとめて届いた同じイベント（asr が続けて何件も、など）の残りも使用済みにして、同じまとまりで何度も発動しないようにする（既定 false） |
| `tags` | 文字列の配列 | 内部状態による優先度の調整に使う |

## 条件（condition / exit_condition）

観測イベント名をキーにした辞書で、すべてのキーが成り立つと合う。

```json
{"asr": null}                                         // asr が来ればよい
{"asr": {"text": {"$regex": "さようなら|またね"}}}     // contents.text が正規表現に合う
{"low_battery": {"current": {"$gt": 0.01}}}            // contents.current が 0.01 より大きい
```

演算子: `$gt` `$lt` `$gte` `$lte` `$eq` `$ne` `$in` `$nin` `$regex` `$and` `$or`。
1つのフィールドに演算子を複数書くと、すべてを満たすときに合う（`{"distance": {"$gte": 3.0, "$lte": 6.0}}` は 3 以上かつ 6 以下）。
値が `null` のフィールドは、比べる演算子には合わない。条件に合う観測が複数あれば、新しいものを使う

`exit_condition` は条件の配列にもでき、どれか1つが合えば打ち切る。
`exit_events` をイベント名ごとに書くと、打ち切ったきっかけによって終わり方を変えられる。
`exit_condition` でも `{triggered[名前]}` が使え、割り込みのきっかけの観測の値で置き換える。
話し相手が立ち去ったら打ち切るなら `{"person_disappear": {"instance_id": "{triggered[instance_id]}"}}`
（ほかの人が立ち去っても打ち切らない。`no_people` は最後の人を見失って 3 秒で出るが、person_disappear は
画像の端から出た・離れていったなら約 1 秒、画面の中で見失ったなら 15 秒戻らないときに出る）。

```json
"exit_condition": [{"no_people": null}, {"conversation_finished": null}],
"exit_events": {
  "no_people": [{"type": "action", "speak": {"type": "normal", "option": {"text": "あれ、行っちゃいましたね。"}}}],
  "conversation_finished": [{"type": "action", "speak": {"type": "normal", "option": {"text": "お話しできてうれしかったです。"}}}]
}
```

## 観測イベント

physical_topic / cyber_topic に入る観測の `event` は、小文字の snake_case（`no_people`、`face_detected`）で書く。
条件のキーには、この名前をそのまま書く。各イベントの contents の形は [OBSERVATIONS.md](OBSERVATIONS.md)。

| イベント | 送るもの | `contents` の主な中身 | 使い方の例 |
|---|---|---|---|
| `face_detected` | 顔認識 | `face_location` など | 挨拶・音声対話の開始 |
| `no_people` | 人数の判定 | `num_people`（0） | 対話の打ち切り（exit_condition） |
| `person_disappear` | 人の追跡（db_management） | `instance_id`、`reason`、`stay_sec` | 話し相手が立ち去ったときの対話の打ち切り（exit_condition） |
| `person_too_near` | 人の追跡（db_management） | `instance_id`、`distance` | 近づきすぎた人への声かけ |
| `many_people` | 人数の判定 | `num_people` | |
| `asr` | 音声認識 | `text`、`words`、`confidence` | 返事待ち、別れの言葉の判定 |
| `keyword_wake` | 話しかけの意図の判定（llm_mic_watchdog_node） | `activate` | 話しかけられたときの対話の開始 |
| `person_in_range` / `person_noticed` | 6 m 以内に入った人（依頼中）と、その人がロボットに気づいたか | `instance_id`、`distance` / `noticed` | 遠くの人に手を挙げる |
| `conversation_finished` | 会話の終わりの判定（会話内容を解釈するプログラム） | `reason`（`farewell` / `topic_end` / `leave` など）、`confidence`、`text` | 対話の打ち切り（exit_condition） |
| `indy_ignored_in_chat` | 会話の中で無視されたことの判定 | | |
| `qr_code` / `qr_code_detect_only` | QR コード | `text` | |
| `low_battery` / `full_battery` / `request_battery_charge` | バッテリ | `percentage`、`current`、`voltage` | 充電 |
| `bumper` | バンパー | | |
| `weather` | 天気（cyber_topic） | | |

`conversation_finished` は、`{"conversation_finished": {"confidence": {"$gte": 0.7}}}` のように、確からしいときだけ打ち切ることもできる。

届いた観測は `src/rism2/schemas/observation.schema.json` で検査し、合わなければ `[ObservationCheck]` の警告をログに出す（実行は止めない。同じ問題は1回だけ）。
イベント名が snake_case でないとき、contents の形がイベントに合わないとき（`person_found` に `distance` がないなど）に知らせる。
スキーマにないイベント名は INFO で1回知らせる。新しいイベントを足したら、このスキーマにも足す。

## イベント

すべてのイベントに書けるフィールド:

| フィールド | 意味 |
|---|---|
| `type` | イベントの種類（下の表） |
| `actor` | 実行するロボット（`robot1` など） |
| `interruptable` | false なら、この間に検知した割り込みは後で実行する（既定 true）。important の割り込みはこのイベントが終わった直後に、ほかは次の interruptable なイベントで実行する |
| `ignore_interruptions` | このイベント（分岐の中も含む）の間は発動させないサブシナリオの ID |

| type | 主なフィールド | 動き |
|---|---|---|
| `action` | `speak` `gesture` `eye` `navigation` `ros_command` | 書いた動作をまとめて実行し、全部終わるまで待つ |
| `wait_for` | `condition` `timeout` `success` `failure` | 観測を待つ。来たら success、来なければ failure |
| `if` | `condition` `timeout` `true` `false` `failure` | 観測を待って分ける。条件に合えば true、同じイベントだが中身が違えば false、来なければ failure |
| `until` | `condition` `loop_timeout` `loop` `failure` | 条件に合う観測が来るまで loop を繰り返す。時間切れなら failure |
| `repeat` | `times` `variable` `subevents` | subevents を times 回繰り返す。`{変数名}` に何回目かが入る |
| `random` | `choices` `weights` | choices（イベント配列の配列）から1つを重みで選ぶ。`weights` は省略でき、省略するとどれも同じ確率。次のイベントとして先読みするときに候補を決めておき、その候補の LLM 発話を先に作る |
| `shuffle` | `choices` | choices（イベント配列の配列）を、順番をシャッフルして**全部**実行する（random は1つだけ選ぶ。shuffle はどれも1回ずつ）。見回りの行き先の順番を毎回変えるときなどに使う。順番は次のイベントとして先読みするときに決め、最初の候補の LLM 発話を先に作る。候補の境目も1つの並びとしてつながるので、次の候補の最初の発話も先に作られる |
| `scenario_exit` | `exit_code` `exit_data` `next_scenario` | シナリオを終える（ループの中からでも） |
| `include` | `scenario` | 指定したシナリオかサブシナリオ（status は問わない）のイベントを、その場で実行する。対話のやりとりなどを inactive のサブシナリオにしておき、いろいろなシナリオから使い回す。入れ子は 5 段まで |
| `suspend_navigation` | | 実行中の移動をその場で止める。割り込みの中なら、割り込みが終わったら送り直す（`navigation_interrupt_mode: parallel` で始めて、途中で止めたいとき） |
| `face_person` | `instance_id` `min_angle_deg` | 体をその人の方へ回す（その場で回る `rotate` を送り、回り終わるのを待つ）。人の位置は観測から読む: 直前の wait_for の結果、割り込みのきっかけの観測の順に、`location_sensor`（体）か `face_location_sensor`（顔）を探す（頭のカメラから見た位置。首が正面を向いている前提）。`instance_id`（例: `{triggered[instance_id]}`、省略可）があれば、その人の観測だけを使う。人の位置がわからないとき、回る角度が `min_angle_deg`（既定 15 度）より小さいときは回らない。移動を止めてから使う |

wait_for / if / until で待っている観測は、割り込みには使わない。
wait_for が答えにするのは、直前の action イベント（問いかけの発話など）を始めた後に RISM が受け取った観測だけ。
それより前の観測は、まだ使われていなくても使わない（問いかける前に聞こえた発話を答えにしない）。
直前の動作の最中に届いた観測（次の wait_for が始まる前に来た返事）は使う。
wait_for の間は、旧 RISM の observation イベントと同じく、Actions に `command: observation`（`option.trigger` に条件、
`timeout`、イベントのほかの項目）を `waiting` で書き、終わったら `done`（`found` に答えの観測）/ `timeout` / `cancelled` にする。
ロボット側の llm_responder はこれを見て `llm-kd` の返事を作る（`reply` / `prompt` はプロンプト名、`hist_to_prompt` などもここから読む）。
割り込みのきっかけになった観測の値は、発話やプロンプトで `{triggered[名前]}` として参照できる。
受け取った観測は `{wait_for.contents.text}` のように参照でき、asr なら相手の発話として会話履歴に入る。

### 動作

| 動作 | 形 |
|---|---|
| `speak` | `{"type": "normal" / "blank" / "generate" / "file", "option": {...}}` |
| `gesture` | `{"type": "normal", "option": {"command": "raise_hand", "duration": 2}}` |
| `eye` | `{"type": "normal", "image": "smile.jpg", "duration": 2}` |
| `navigation` | `{"type": "normal", "option": {"navigation": [x, y, 向き]}}`（`destination` `rotate` `move` も可。`{"dock": true}` で充電ステーションに入る） |
| `ros_command` | `{"type": "normal", "topic": "...", "topic_type": "...", "data": "..."}`（`topic_type` が `std_msgs/msg/Int32` なら `data` は整数。例: 音量 `{"topic": "/robot1/robot/set_volume", "topic_type": "std_msgs/msg/Int32", "data": 20}`） |

`speak.option` の主なキー:

| キー | 意味 |
|---|---|
| `text` | 発話する文（blank では `{変数}` を埋める） |
| `except` | blank で変数が埋められないときの文 |
| `generator` | generate で使うジェネレータ（`LlmJPEventGenerator` など） |
| `prompt` | LLMへの指示。`{greeting}`（時間帯の挨拶）と `{now}`（時刻）を埋める |
| `hitorigoto` | 独り言として作る |
| `hist_len` | LLMに渡す直近の履歴の数。0 は渡さない |
| `llm_max_tokens` | 生成の長さの上限 |
| `fallback_text` | 生成に失敗したときの文（なければ「[発話生成に失敗しました]」） |
| `temperature` | LLM の温度（既定 0.6） |
| `llm_timeout` | LLM の応答を待つ秒数（既定 60） |
| `stop` | 生成を止める文字列（既定 `["\n", "###"]`） |
| `use_memories` | 記憶（`memory_recall` の観測）をいくつ使うか（既定 0） |
| `use_db_hist` / `hist_count` | 会話履歴を dialogue_history から読む（`hist_count` 件、既定 10） |

LlmJPEventGenerator の応答に付いたハッシュタグ（`#smiling` など）は、ジェスチャーと目の表示になる。
generate のイベントに `gesture` / `eye` を書いておけば、そちらが優先する。
応答の先頭が「待つ：」「それから？：」「聞き返し：」「無視：」なら、それぞれ少し待つ・相槌・前の発話の繰り返し・発話しない、になる。

どの動作の `option` にも書ける、リトライとタイムアウトのキー:

| キー | 意味 |
|---|---|
| `retry` / `retry_delay` | 失敗したら何回、何秒おいて送り直すか（既定は設定の `error_recovery`。generate なら生成のリトライ） |
| `timeout` | 完了を待つ秒数（既定は設定の `executor.default_{動作}_timeout`、なければ `executor.default_timeout`） |
| `timeout_fallback_text` | 時間切れのとき代わりに話す文 |
| `on_timeout` | 時間切れのとき代わりに実行する動作（`{"action": "speak", "text": "..."}` など） |

移動（navigation）が送ってすぐ失敗したら、ロボットが前の移動を終えていないとみなして、少し待って送り直す（設定の `executor.navigation_*`）。

`{"dock": true}` は、ロボットの `navigate_to_charge`（auto_charge）でステーションに入り、充電が始まったら done、
入れなければ failed になる。完了待ちは `executor.default_dock_timeout`（既定 200 秒）。
すぐ失敗しても送り直さず、ignored（dock を扱えない古いロボット）も失敗として扱う。
目の表示（eye）は送れば切り替わるので、完了を待たない。

## Event Generator

`speak.type` が `generate` のとき、`speak.option.generator` で文の作り方を選ぶ（省略時は LlmJPEventGenerator）。

| generator | 内容 | 主な option |
|---|---|---|
| `LlmJPEventGenerator` | LLM で話す文を作る | `prompt` `hitorigoto` `hist_len` `llm_max_tokens` `use_observations` `observation_window` |
| `TemplateEventGenerator` | 定型文から1つ選ぶ（LLMなし） | `templates` `fallback_text` |
| `KeywordResponseEventGenerator` | 聞いた発話のキーワードで決まった答え。当てはまらなければ別の Generator に任せる | `responses` `fallback_generator` `fallback_text` |
| `KnowledgeEventGenerator` | 登録した知識だけを使って LLM が答える（作り話を防ぐ） | `knowledge` `use_db` `top_k` `no_match_text` `no_match_generator` `prompt` |
| `MemoryEventGenerator` | 前に話したことを思い出して LLM が話す。会話を要約して覚える | `recall` `save` `person_field` `summary_hist_len` `prompt` |
| `EchoBackEventGenerator` | 聞いた発話をそのまま返す（デバッグ用） | `default_text` |
| `MultiGenAndSelectEventGenerator` | 複数の Generator で候補を作って1つ選ぶ | `generators` `selection_strategy` |

prompt・templates・text では `{greeting}` `{now}` `{heard}`（聞いた発話）`{triggered[名前]}` `{wait_for.contents.text}` などの変数が使える。

### 知識（シナリオDBの `knowledge` コレクション）

```json
{"title": "トイレ", "keywords": ["トイレ", "お手洗い"], "text": "エレベーターの横、右手です。", "status": "active"}
```

keywords のどれかが聞いた発話に含まれる知識を、当てはまった数の多い順に使う。`status` が `inactive` のものは使わない。

### 記憶（シナリオDBの `memories` コレクション）

```json
{"person": "山田", "text": "見学に来て、ロボットの研究を見たいと言っていた", "created": "2026-11-01T15:00:00"}
```

MemoryEventGenerator が `save: true` のときに書き込む。`person` は `person_field` で人がわかったときだけ入り、わからなければ null（全員共通の記憶）。
