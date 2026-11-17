# RISM の設定

設定 DB（ポート 9100）の `rism_configs.rism_config` に書く。項目・型・既定値は `src/rism2/settings.py` が決め、この表もそこから作る（`uv run python -m rism2.settings` で出力）。

起動時に設定を検査し、知らない項目（打ち間違いや、もう使っていない項目）と型の違う値を `[Settings]` の警告としてログに出す。書いていない項目には既定値が入る。

ロボットごとの設定（`robot_list`）とデモの設定（`demo_list`）は、この表には含まない。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `latest_N` | int | 100 | 観測を読むときの最大件数 |
| `observation_cache_size` | int | 10000 | 観測のキャッシュの最大件数 |
| `use_change_streams` | bool | true | 観測を Change Streams で受け取る（false ならポーリング） |
| `cleanup_topics_on_start` | bool | true | 起動時に、それまでの未使用の観測を使用済みにする |
| `max_history_length` | int | 10 | LLM に渡す会話履歴の最大件数 |
| `finished_queue_length` | int | 100 | 実行したイベントを覚えておく件数 |
| `interruption_probability` | number | 1.0 | 割り込みを発動させる確率（サブシナリオの interruption_probability が優先） |
| `default_scenario_exit_code` | str | "success" | scenario_exit がないシナリオの終わり方 |
| `default_navigation_interrupt_mode` | str | "parallel" | 割り込みで移動をどうするか（parallel / suspend_and_resume / wait_completion） |
| `internal_state_priority_rules` | list | [] | 内部状態による割り込みの優先度の調整規則 |
| `executor.default_timeout` | number | 30 | 動作の完了待ちと、timeout のない wait_for / if / until の待ち時間（秒） |
| `executor.default_utterance_timeout` | number | （なし） | 発話の完了待ち（秒）。なければ default_timeout |
| `executor.default_gesture_timeout` | number | （なし） | ジェスチャーの完了待ち（秒）。なければ default_timeout |
| `executor.default_navigation_timeout` | number | （なし） | 移動の完了待ち（秒）。なければ default_timeout |
| `executor.default_dock_timeout` | number | 200 | ドッキング（navigation の dock）の完了待ち（秒） |
| `executor.default_eye_timeout` | number | （なし） | 目の表示の完了待ち（秒）。なければ default_timeout |
| `executor.default_ros_command_timeout` | number | （なし） | ROS コマンドの完了待ち（秒）。なければ default_timeout |
| `executor.default_command_event_timeout` | number | （なし） | command_event の完了待ち（秒）。なければ default_timeout |
| `executor.navigation_quick_fail_sec` | number | 5 | 送ってこの秒数以内に失敗した移動は、ロボットに拒否されたとみなして送り直す |
| `executor.navigation_resends` | int | 2 | すぐ失敗した移動を送り直す回数 |
| `executor.navigation_resend_delay` | number | 3 | すぐ失敗した移動を送り直すまで待つ秒数 |
| `prefetch.enabled` | bool | true | 次の LLM 発話を先に作っておく |
| `prefetch.wait_timeout` | number | 30.0 | 先に作っている発話を待つ最大秒数 |
| `error_recovery.default_retry_count` | int | 0 | 動作が失敗したときのリトライ回数（イベントの retry がなければ） |
| `error_recovery.default_retry_delay` | number | 1.0 | リトライまで待つ秒数 |
| `error_recovery.max_retry_count` | int | 5 | リトライ回数の上限 |
| `error_recovery.min_retry_delay` | number | 0.1 | リトライまで待つ秒数の下限 |
| `stress_level.increment` | number | 0.2 | 割り込みがキューに入るたびに増やす量 |
| `stress_level.decrement` | number | 0.1 | シナリオが終わるたびに減らす量 |
| `stress_level.thresholds` | list | [] | 閾値を超えたときに入れる割り込み |
| `debug.visualize_interrupt_queue` | bool | false | 割り込みキューを画面に表示する |
| `debug.track_interrupt_queue` | bool | false | 割り込みキューを MongoDB に記録する |
| `debug_mode.enabled` | bool | false | シナリオのデバッグモード |
| `debug_mode.show_state_dump` | bool | true | イベントの前後の状態を出す |
| `debug_mode.show_llm_prompts` | bool | false | LLM に渡すプロンプトを出す |
| `debug_mode.show_llm_responses` | bool | false | LLM の応答を出す |
| `timezone.mode` | str | "system" | 時刻の扱い（system / explicit） |
| `timezone.explicit` | str | （なし） | mode が explicit のときのタイムゾーン（例: Asia/Tokyo） |

## ロボットごとの設定（`robot_list`）

`rism_configs.robot_list` に、ロボットごとに1つの文書を書く（`robot_id` がキー）。主な項目:

| 項目 | 内容 |
|---|---|
| `robot_id` | ロボットの ID（`--robots` で指定する名前） |
| `name_alias` | 表示名 |
| `action_db` | 動作を書く DB: `host` `port` `dbname`（tBlackBoard）`version`（"1.0" / "2.0"、docs/ACTION_DB_VERSION_ROUTING.md）`col_name`（既定 Actions） |
| `physical_topic` / `cyber_topic` | 観測を読む DB の `host` `port`（なければ `demo` の host / port） |
| `llm` | LlmJPEventGenerator が使う LLM: `url` `model` `system_prompt` `defaults`（`temperature` など）`log_db` |
| `internalstate_db` | 内部状態の DB: `host` `port` `dbname` `col_name`（internal_state） |
| `personality` | ロボットの性格: `first_person`（一人称）`interests`（興味のある話題） |

次の項目は RISM ではなく、ロボット側のプログラムが読む:

| 項目 | 内容 | 読むプログラム |
|---|---|---|
| `google_asr` | Google ASR のサーバ（`NumASR` `ServerConf` `AliveMesgInterval`） | indy_google_asr |
| `asr_target_angle` | 音声認識に使う音源の角度の範囲（度） | db_management |
| `ignore_non_looking` | ロボットを見ていない人の音声認識を登録しない | db_management |
| `recognition_available_regions` | 認識してよい範囲（なければすべて） | db_management |

## 全ロボット共通の設定（`common`）

`rism_configs.common` の1つの文書。ロボット側のプログラム（db_management の天気の登録）が読む。

| 項目 | 内容 |
|---|---|
| `city` | 天気を取る場所（例: Kyoto,JP） |
| `language` | 天気の言語 |
| `openweathermap_token` | OpenWeatherMap のトークン |

## 2つの `rism_config` について

設定DB の `rism_configs.rism_config` は RISM の設定（上の表）。ロボット側のプログラムの設定は、
`robot_list` のそのロボットの文書と `common` に書く（ロボット側は pyindy の `load_robot_settings` で設定DB から読む）。
古い構成では、各ロボットの DB に同じ名前の `rism_configs.rism_config` があり、ロボット側の設定を書いていた。
今はそこを読まないので、残っていれば `robot_list` と `common` に移してから片付ける。

## デモの設定（`demo_list`）

`rism_configs.demo_list` に、デモごとに1つの文書を書く（`demo_id` がキー、`--demo` で指定する）。
`host` `port` と `scenario_db`（`host` `port` `db_name`: シナリオを読む DB）を書く。
