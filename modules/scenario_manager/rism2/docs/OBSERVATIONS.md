# 観測イベントの形式（tBlackBoard.physical_topic / cyber_topic）

RISM はこのコレクションに入った観測を読み、シナリオの条件（`condition` / `exit_condition` / `wait_for` など）と照らし合わせる。

## 共通の形

pyindy の `PhysicalDBWriter(uri, port, "tBlackBoard", <イベント名>).insert(contents, priority)` で書くと、この形になる。

```json
{
  "event": "face_detected",          // イベント名（小文字の snake_case）
  "priority": 50,                    // 既定 50
  "inserted": "2026-11-07T00:23:42", // 書いた時刻（ローカル時刻）
  "contents": { ... },               // イベントごとの中身（下記）
  "mentioned": false,                // RISM が使ったら true にする
  "last_mentioned": null
}
```

- イベント名は小文字の snake_case にする（`no_people`、`face_detected`）。スペースやハイフンは使わない。
- シナリオの条件では、`contents` の中のキーを直接書く。例：`{"asr": {"text": {"$regex": "またね"}}}` は `contents.text` を見る。
- RISM が使った観測は `mentioned: true` になり、もう一度は使われない。

## asr（音声認識）

送るもの：`llm_responder` の `llm_mic_watchdog_node`（ROS の `asr/meta_data` を受けて書く）。priority 100。

```json
"contents": {
  "words": "じゃあまたね",   // 認識結果（asr/meta_data のまま）
  "text": "じゃあまたね",    // words をつなげた文字列。シナリオの条件はふつうこちらを見る
  "confidence": 0.93,        // scores を数値にしたもの
  "scores": "0.93",
  "sep_port": 5580,          // マイク（adintool）のポート
  "turn_end": true
}
```

シナリオでの使い方：返事待ち `{"asr": null}`、別れの言葉 `{"asr": {"text": {"$regex": "さようなら|またね"}}}`。

## face_detected（顔の検出）

1人（追跡している1人）につき1回だけ送られる。

```json
"contents": {
  "instance_id": 81954,                     // 追跡している人の番号
  "face_location": [561.0, 211.0, 170.0, 170.0]  // 画像上の顔の位置 [x, y, 幅, 高さ]（ピクセル）
  // ほかに顔の位置に関する項目がある（未確認）
}
```

シナリオでの使い方：挨拶・音声対話の開始 `{"face_detected": null}`、見回りでの在席確認（wait_for）。

## no_people / many_people（人数）

送るもの：`db_management` の `register_db_recog_node`（`dbmanager.check_events`）。0.5 秒ごとに tracking の人（`class_id: 0`）の数を数え、変わったときに送る。priority 50。

| イベント | 送るとき | contents |
|---|---|---|
| `no_people` | 人数が 0 になったとき | `{"num_people": 0}` |
| `many_people` | 人数が 3 以下から 4 以上になったとき（`many_people_threshold`） | `{"num_people": 5}` |

シナリオでの使い方：対話の打ち切り `"exit_condition": [{"no_people": null}, ...]`。

## conversation_finished（会話の終わり）

送るもの：会話内容を解釈して、話が終わったと判断するプログラム（別途用意する想定）。

```json
"contents": {
  "reason": "farewell",     // 理由：farewell（別れの挨拶）/ topic_end（話題が尽きた）/ leave（立ち去りそう）など
  "confidence": 0.9,        // 確からしさ（0〜1）
  "text": "じゃあまたね"     // 判断のもとになった発話
}
```

中身は空でもよい。シナリオでの使い方：対話の打ち切り `{"conversation_finished": null}`。
確からしいときだけ打ち切るなら `{"conversation_finished": {"confidence": {"$gte": 0.7}}}`。

## person_found / person_in_range / person_appear / person_noticed（人と、その人の反応）

送るもの：ロボット側の db_management（`dbmanager.py`）。どれも1人（`instance_id`）につき1回だけ出し、見失ったら消す。
見失って 15 秒（`lost_grace_sec`）以内に同じ `instance_id` が戻ってきたら同じ人として扱い、person_found などは出し直さない（挨拶し直さない）。

```json
// person_found: 初めて見つけた人（距離に関係なく）。奥行きが取れないと distance は null
"contents": {"instance_id": 7, "distance": 9.3}

// person_in_range: 6 m 以内に初めて入った人（依頼中）。distance はそのときの距離（必ず数値）
"contents": {"instance_id": 7, "distance": 5.8}

// person_appear: 3 m 以内に初めて入った人（register_db_recog_node の distance_threshold）
"contents": {"instance_id": 7, "distance": 2.7, ...}

// person_noticed: その人がロボットに気づいている間だけ1件ある（noticed_node の判定。6 m より遠い人は出ない）
"contents": {"instance_id": 7, "noticed": {"noticed": true, "looking": true, "waving_hand": false,
             "raising_hand": false, "approaching": false, "distance": 4.1, ...}}
```

```json
// person_too_near: 0.5 m（too_near_distance）より近づいた人。0.7 m より離れたら消え、また近づいたら出る
"contents": {"instance_id": 7, "distance": 0.4, "location_sensor": [0.0, 0.1, 0.4]}

// person_disappear: 立ち去った人。priority 50。見失ったときの様子で出す時を変える
//   画像の左右の端で消えた（out_of_view_left / right）・0.3 m/s 以上で離れていく途中だった（walked_away）・
//   6 m より遠かった（too_far）: 見失って約 1 秒で出す
//   画面の中で見失った（隠れた・検出漏れかもしれない）: 15 秒たっても戻らなければ出す（lost）
//   出したあとで 15 秒以内に戻ってきたら消える
"contents": {"instance_id": 7, "reason": "out_of_view_left", "lost_sec": 1.2, "stay_sec": 42.0, "min_distance": 1.2,
             "events": ["face_detected", "person_found", "person_noticed"],  // 追跡中に出たイベント
             "attributes": {"skirt": 0.8}, "first_seen": ..., "last_seen": ...}
```

person_appear の contents には、その時点で分かっている服装などの属性（`attributes`: 属性名 → 確からしさ。まだ無ければ空）も入る。

`instance_id` はどれも同じ人には同じ値。シナリオ「遠くの人に手を挙げる」（`samples/subscenarios/notice_and_talk.json`）は
person_in_range（3 m 以上）で発動し、`{"person_noticed": {"instance_id": "{triggered[instance_id]}"}}` で手を挙げた相手の反応だけを待つ。
person_found は最初に見つけたときに1回しか出ないので、距離の条件を付けると、遠くで見つけた人が近づいてきても発動しない。

## raising_hand / waving_hand / wheelchair / looking / long_looking / many_looking（人の動作）

送るもの：db_management の `register_db_recog_node`（action_recognition の結果を tracking に書くときに判定する）。
contents は tracking のその人の記録（位置 `location_sensor`・`location_global`、`hand_state` など。姿勢は除く）。

| イベント | 送るとき | priority |
|---|---|---|
| `raising_hand` | 手を挙げている間だけ1件（下ろしたら消える）。認識可能領域（`recognition_available_regions`）の中の人だけ | 30 |
| `waving_hand` | 手を振っている間だけ1件（やめたら消える）。認識可能領域の中の人だけ | 100 |
| `wheelchair` | 車椅子に座っている人。追跡中1回 | 100 |
| `looking` / `long_looking` | target（1 / 2）を 0.2 秒 / 1 秒以上見続けている人がいる間。target ごとに1件（`{"target": 1, "duration": 秒}`） | 50 |
| `many_looking` | target を 1 秒以上見ている人が 5 人以上（`{"target": 1, "num_person": 5}`） | 50 |

## keyword_wake（話しかけの意図）

送るもの：`llm_mic_watchdog_node`。待機中の発話を LLM で判定し、話しかけたがっていれば送る（対話の最中は判定しない）。

```json
"contents": {"activate": true}
```

今はロボットが `keyword-wake`（ハイフン）で送っている。シナリオでは未使用。

## 検査

RISM は届いた観測を `src/rism2/schemas/observation.schema.json` で検査し、合わなければ `[ObservationCheck]` の警告をログに出す
（イベント名が snake_case でない、contents の形が合わないなど。実行は止めない）。新しいイベントを足したら、スキーマにも足す。
