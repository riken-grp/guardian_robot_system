# RISM のしくみ

RISM（Robot Interactive Scenario Manager）は、MongoDB に置いたシナリオを読み、ロボットへの動作を MongoDB 経由で送る。
ロボットのセンサーが書いた観測を見て、シナリオを選び、割り込みを起こす。

## 全体の流れ

```
 ロボット（ROS）                       MongoDB                                  RISM
 センサー ──観測──▶ tBlackBoard.physical_topic / cyber_topic ──Change Streams──▶ ObservationWatcher ─▶ 観測のキャッシュ
                                                                                     │
                                                                                     ▼
                                                     InterruptDetector（0.5秒ごと、と観測が届いたとき）
                                                       条件に合うサブシナリオ → InterruptQueue（優先度順）
                                                                                     │
 シナリオDB（demo_configs）                                                          ▼
   scenarios / interruption_subscenarios ─────────────────────▶ ScenarioInterpreter（メインスレッド）
                                                               イベントを順に実行し、イベントの合間や
                                                               動作を待つ間に、キューの割り込みを実行する
                                                                                     │
 ロボット（ROS）                                                                     ▼
 動作の実行 ◀──waiting を拾う── tBlackBoard.Actions ◀──書く・完了を待つ── ActionHandler（pyindy のマネージャー）
           ──is_playing / done を書く──▶          ──Change Streams──▶ ActionChangeNotifier
```

## モジュール

| 役割 | モジュール |
|---|---|
| 起動・再起動 | `main.py`（設定 DB を読み、`ScenarioInterpreter` を作ってシナリオの連鎖を動かす。SIGTERM / SIGINT で止まる） |
| 設定 | `database.py`（設定 DB の読み込み、共有の MongoClient）、`settings.py`（設定項目の一覧と起動時の検査） |
| シナリオの実行 | `interpreter.py`（シナリオの連鎖、待機モード）、`execution_context.py`（実行中の状態とフレーム、返事待ちの予約） |
| イベント | `event_model.py`（イベントの型）、`event_processor.py`（種類ごとに振り分け、`include`・`scenario_exit` など）、`event_action_handler.py`（動作を送って完了を待つ）、`event_generate_handler.py`（Event Generator で発話を作る）、`event_control_flow_handler.py`（repeat / random / if / until）、`event_observation_handler.py`（wait_for、待つ前の動作） |
| 割り込み | `interrupt_detector.py`（検知）、`interrupt_queue.py`（優先度キュー）、`interrupt_manager.py`（実行・入れ子・戻り方）、`navigation_suspender.py`（移動を止める・送り直す） |
| 観測 | `observation_watcher.py`（受け取り）、`observation_store.py`（読み出しと使用済みの印）、`observation_validator.py`（形の検査）、`condition_checker.py`（条件の照合）、`condition_waiter.py`（観測を待つ） |
| シナリオ DB | `scenario_repository.py`（読み込み・スキーマ検査・サブシナリオの使い回し）、`scenario_selector.py`（次のシナリオ・割り込みの選択）、`scenario_model.py`（シナリオの型） |
| 先読み | `prefetch_manager.py`（次の LLM 発話を先に作る） |
| 発話を作る | `event_generators/`（LLM、定型文、キーワード、知識、記憶など） |
| 状態の記録 | `state_manager.py`（`current_state`）、`scenario_history.py`（`scenario_history`） |

## 読み書きする DB

| DB | コレクション | RISM が | 内容 |
|---|---|---|---|
| 設定（9100）`rism_configs` | `rism_config` `robot_list` `demo_list` | 読む | 設定（docs/CONFIG.md） |
| シナリオ（`demo_list` の `scenario_db`） | `scenarios` `interruption_subscenarios` | 読む | シナリオ（docs/SCENARIO_SCHEMA.md） |
| | `knowledge` `memories` | 読む・書く | 知識と記憶の Generator |
| ロボット（例: 9110）`tBlackBoard` | `physical_topic` `cyber_topic` | 読む・使用済みにする | 観測（docs/OBSERVATIONS.md） |
| | `Actions` | 書く・状態を読む | ロボットへの動作 |
| | `current_state` | 書く | 実行中の状態（下記） |
| | `scenario_history` | 書く | 実行したシナリオと終わり方。`parent_history_id`（割り込まれたシナリオの記録の `_id`、メインは null）`depth`（メイン 0、割り込み 1 …）`robot`。終わらないまま次を読み込んだときとプロセスの終了時は、`exit_code: aborted` で閉じる |
| | `dialogue_history` | 読む（`use_db_hist` のときだけ） | ロボットが話した・聞いた発話（書くのはロボット側） |

## 割り込みの決まり

- 条件に合うサブシナリオが複数あれば、今は発動させないもの（実行中のイベントやシナリオの `ignore_interruptions`、同じサブシナリオを実行中、`ignore_after_activated` の間）を外してから、優先度を重みに1つ選ぶ。
- `interruption_probability`（サブシナリオか設定）の確率で発動する。`important`（旧形式の `force_interrupt` も同じ）なら必ず発動する。
- 割り込みの実行中は、それより優先度の高い割り込みだけを入れ子で実行し、ほかは終わってから実行する。
- 返事待ち（wait_for / if / until）が待っている観測と、次のイベントが待つ観測は、割り込みに使わない。
- 移動中なら `navigation_interrupt_mode` に従い、止める（`suspend_and_resume`、終わったら送り直す）、終わるまで待つ（`wait_completion`）、そのまま（`parallel`）のどれか。途中で止めるなら `suspend_navigation` イベント。

## 実行中のシナリオ（フレーム）

`ExecutionContext.frames` に、実行中のシナリオ1つにつき `Frame` を1つ積む（`execution_context.py`）。
一番下がメインシナリオで、割り込みが始まるたびに積み、終わったら外す。割り込みの中の割り込みは、その上に積む。

| フレームが持つもの | 内容 |
|---|---|
| `scenario` `kind` `started_at` | シナリオ、種類（main / interrupt）、始めた時刻（`exit_condition` は、これより後の観測だけを見る） |
| `history_id` | `scenario_history` の記録の ID |
| `triggered_observation` | 割り込みのきっかけの観測（`{triggered[...]}`） |
| `wait_for_result` | wait_for で受け取った観測（`{wait_for...}`） |
| `suspended_navigations` | この割り込みで止めた移動（終わったら送り直す） |
| `reserved_events` `upcoming_wait_events` | 返事待ちが今待っている、このあと待つイベント名（その観測は割り込みに使わない） |
| `event_ignores` | 実行中のイベントの `ignore_interruptions` |
| `resume_mode` | 中の割り込みが `next_event` / `restart` で終わったという印 |
| `exit_requested` `exit_condition_met` `exit_trigger_events` `exit_status` | このシナリオの終わり方（`scenario_exit`、`exit_condition`） |
| `event_index` | 実行中のイベントの位置（メインシナリオ） |

- `{triggered[...]}` や `{wait_for...}`、打ち切りの印と終わり方は、一番内側のフレームの値を読み書きする。内側の割り込みが終われば、外側の値に戻る。
- メインシナリオ（`current_scenario`、`scenario_start_time`、`current_event_index`）は `frames[0]` にある。
  割り込みの中の `exit_main` / `redirect` / `terminate` は、メインシナリオのフレームの終わり方として書く。
  次のシナリオの選び方（`terminate_main_scenario`、`redirect_scenario_id`）は、メインシナリオが終わったあとにも読むので `ExecutionContext` に持つ。
- 割り込み検知は、すべてのフレームの予約と `ignore_interruptions` を見る（割り込みの最中も、外側の返事待ちが待つ観測は取らない）。
- 割り込みの `resume_after` が `next_event` / `restart` なら、割り込まれたフレームに印を付ける。
  割り込みを実行した待ち（動作の完了待ち、返事待ちなど）が `EventInterrupted` を送ってイベントを抜け、
  そのフレームのイベントの並びが、次のイベントへ進むか、同じイベントをやり直す。
  イベントの合間や待機中に入った割り込みでは、抜けるイベントがないので `resume` と同じ。

## current_state

`tBlackBoard.current_state` の1つの文書（`_id: current_state_singleton`）に、実行中の状態を書く。

| フィールド | 内容 |
|---|---|
| `interpreter.status` | `running` / `interrupted` / `idle` / `completed` / `error` など |
| `scenario` | 実行中のシナリオの `id` `name` `status` |
| `event` | 実行中のイベントの `index` `type` |
| `actors` | ロボットごとの `name` と `status`（`running` / `waiting`） |
| `interrupt` | `is_interrupted` `depth` `subscenario_id` `subscenario_name` |
| `processing` | `is_tts_processing` `is_llm_generating` `is_asr_waiting` `is_navigating` `is_prefetching` |
| `internal_state` | 内部状態（`stress_level` など） |
| `waiting` | 今の待ち（外側から順のリスト。入れ子: until の中の wait_for、待ちの最中の割り込みの中の待ちなど）。各要素は `kind`（wait_for / if / until / pre_wait_action / action / command_event）`actor` `scenario_name` `is_interruption` `condition`（JSON 文字列）`timeout` `started_at` `deadline_at`（UTC）`interruptable` `actions`（動作の完了待ちなら `[{command, action_id}]`）。待っていなければ `[]` |
| `last_wait` | 直近に終わった待ち: `kind` `scenario_name` `condition` `timeout` `started_at` `ended_at` `result`（matched / unmatched / timeout / exit / done / failed） |
| `last_updated` | 最後に書いた時刻（UTC） |

## スレッド

メインスレッドがシナリオを実行する。ほかに、観測の受け取り（physical / cyber）、割り込みの検知（0.5 秒ごと）、
サブシナリオと Actions の変更通知、先読みの生成が、それぞれスレッドで動く。
割り込みはメインスレッドが、イベントの合間と動作を待つ間に実行する（検知スレッドはキューに入れるだけ）。
