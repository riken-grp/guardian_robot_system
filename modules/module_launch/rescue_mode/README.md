# レスキューモード 仕様

## ディレクトリ構成

```
rescue_mode/
├── hv_watch.sh                        # 常駐監視（module_launch.sh から起動）
├── hv_to_rescue.sh                    # レスキューモード移行
├── hv_to_normal.sh                    # 通常モード復帰
├── scripts/
│   ├── 01_play_loop_audio_msg.sh      # 音声ループ再生
│   └── 02_motor_release.sh            # タイヤ解放
└── tools/
    ├── battery_check_tool             # バッテリー電流取得（バイナリ）
    ├── motor_release_tool             # タイヤ解放（バイナリ）
    ├── motor_release_tool_for_rescue  # タイヤ解放 & バッテリー電流取得（バイナリ）
    ├── send_slack_msg.sh              # Slack通知
    ├── check_nav_failures.py          # MongoDB ナビゲーション連続失敗チェック
    ├── help_request.wav               # 助けを求める音声
    ├── charging_detected.wav          # 充電検知の音声
    └── return_to_normal.wav           # 復帰音声
```

---

## 動作フロー概要

```
module_launch.sh
    └─ tmux: 00_hv_watch ─→ hv_watch.sh（MONGO_URI, MONGO_PORT を引数または環境変数から取得）
                                │
                         5秒ごとに3つのチェックを実行
                                │
              ┌─────────────────┼──────────────────────┐
              │                 │                      │
         check_ping        check_sessions        check_nav_failures
      MongoDBマシンへping   tmuxセッション数       MongoDB直近N件
         閾値超過で異常       N個以上停止で異常      全failedで異常
              │
              └─→ 異常検知 → Slack通知（理由付き）→ hv_to_rescue.sh をフォアグラウンドで呼び出し
                                                        │（充電検知後 hv_to_normal.sh へ）
                                                        └─→ 通常モード復帰後、監視を再開
```

---

## 各スクリプトの動作

### hv_watch.sh（常駐監視）

`module_launch.sh` から tmux セッション `00_hv_watch` として起動される。  
ロボット搭載マシン(`ON_ROBOT=1`)でのみ起動し、サーバマシンやrobodjでは起動しない。

**チェック内容（5秒ごと）:**

| チェック | 異常条件 |
|---|---|
| `check_ping` | MongoDBマシン(`$MONGO_URI`) への ping が無応答または 1000ms 超を **3回連続**で検知 |
| `check_sessions` | `check_sessions.sh`（`$GUARDIAN_ROBOT_PATH/modules/module_launch/enable/*.sh` が対象）で停止中のセッション数が n(デフォルト：3) 以上 |
| `check_nav_failures` | MongoDB の直近 n(デフォルト：3) 件のナビゲーションが全て `failed`。`ROBOT_NAME` 未設定の場合はスキップ |

起動時、`ROBOT_NAME` が設定されていれば `check_nav_failures.py --init` を実行し、直近のナビゲーション結果が `failed` なら `canceled` に書き換えて誤検知を防ぐ。

異常を検知すると Slack に理由を通知し、`hv_to_rescue.sh` をフォアグラウンドで呼び出す。  
`hv_to_rescue.sh`（→ `hv_to_normal.sh`）が終了するまで待ち、通常モードに戻った後は ping の失敗カウントをリセットして監視を再開する（hv_watch 自身は終了しない）。

---

### hv_to_rescue.sh（レスキューモード移行）

1. 以下のセッション停止処理を実行する
   - `$GUARDIAN_ROBOT_PATH/modules/module_launch/enable/*.sh` に対応する各セッションに Ctrl+C を送る
   - `scenario_manager` セッションに Ctrl+C を送る
   - `$GUARDIAN_ROBOT_PATH/tools/bin/50_cancel_all.py` を実行する
2. 1 のセッション停止処理を、バックグラウンドで **20 秒ごと**に繰り返す（充電検知まで）
3. tmux セッション `hv_play_audio` 起動 → `help_request.wav` をループ再生（再生間隔 5 秒。環境変数 `PLAY_INTERVAL` で変更可）
4. Slack 通知：`レスキューモードに入りました。充電ステーションへの誘導をお願いします。`
5. `motor_release_tool_for_rescue` 起動 → タイヤ解放コマンドを 50ms 周期で送信
6. バッテリー電流を 10 秒ごとに監視し、**電流がマイナス**（充電開始）を検知したら `motor_release_tool_for_rescue` が終了する
7. 2 の定期停止処理を止め、`charging_detected.wav`（「充電状態に入りました。セルフチェックを開始します。」）を再生して `hv_to_normal.sh` に移る

※ `hv_watch` セッションは停止しない（`hv_watch.sh` は `hv_to_rescue.sh` の終了を待っている）。

---

### hv_to_normal.sh（通常モード復帰）

`ROBOT_NAME` または `MONGO_URI` が未設定の場合は、エラーで終了する。

1. `hv_play_audio` セッションが無くなるまで Ctrl+C を送る（音声停止）
2. MongoDBマシン（`$MONGO_URI`）への ping 平均が **20ms 以下**になるまで待機
3. `return_to_normal.wav` を 1 回再生（バックグラウンドで再生し、終了を待たずに次へ進む）
4. `$GUARDIAN_ROBOT_PATH/tools/bin/50_cancel_all.py` を実行
5. `module_launch.sh` を実行してノード群を再起動
6. 起動確認を**最大 6 回**繰り返す
   - `hv_play_audio` セッションが残っていれば（`module_launch.sh` が起動をスキップするため）、停止してから `module_launch.sh` をやり直す
   - 残っていなければ `check_sessions.sh` で停止セッション数を確認し、**0** なら次へ。0 でなければ `module_launch.sh` をやり直す
7. `check_sessions.sh` で最終確認し、起動していないセッションを調べる
8. 充電ステーション位置に初期位置をセット（`/<ROBOT_NAME>/rover/set_initialpose` に publish。座標はスクリプト内に固定値で記述）
   - 購読側（ローバ）が起動していないと publish が待ち続けるため、30 秒で打ち切る
9. Slack 通知
   - すべてのセッションが起動していれば：`通常モードに戻りました。`
   - 起動していないセッションがある、または初期位置を設定できなかった場合：`通常モードへの復帰処理を終えましたが、問題があります。<内容> 確認をお願いします。`（終了コード 1 で終了する）  
     `<内容>`は`起動していないセッションがあります: <セッション名>`、`初期位置を設定できませんでした。`のいずれか、または両方
   - いずれの場合も、hv_watch は監視を再開する

---

## Slack 通知タイミング

| タイミング | メッセージ |
|---|---|
| レスキュー移行直前 | `[ROBOT_NAME] レスキューモードに移行します。理由: <原因>` |
| レスキューモード開始後 | `[ROBOT_NAME] レスキューモードに入りました。充電ステーションへの誘導をお願いします。` |
| 通常モード復帰完了 | `[ROBOT_NAME] 通常モードに戻りました。` |
| 通常モード復帰処理後、起動していないセッションがある、または初期位置を設定できなかった | `[ROBOT_NAME] 通常モードへの復帰処理を終えましたが、問題があります。<内容> 確認をお願いします。` |

Webhook URL は環境変数 `SLACK_WEBHOOK_URL` で指定する。未設定の場合は通知をスキップする（エラーにはならない）。

---

## チェック条件の追加方法

`hv_watch.sh` に以下の手順で追加できる。

1. `check_*()` 関数を追加し、異常時に `trigger_rescue "理由"` を呼ぶ
2. `run_checks()` 内にその関数呼び出しを 1 行追加する

```bash
# 例: 独自チェック
check_custom() {
    # 異常を検知したら:
    trigger_rescue "custom condition detected"
}

run_checks() {
    check_ping
    check_sessions
    check_nav_failures
    check_custom   # ← 追加
}
```
