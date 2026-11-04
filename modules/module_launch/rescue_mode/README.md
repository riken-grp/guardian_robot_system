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
              └─→ 異常検知 → Slack通知（理由付き）→ hv_to_rescue.sh 呼び出し
```

---

## 各スクリプトの動作

### hv_watch.sh（常駐監視）

`module_launch.sh` から tmux セッション `00_hv_watch` として起動される。

**チェック内容（5秒ごと）:**

| チェック | 異常条件 |
|---|---|
| `check_ping` | MongoDBマシン(`$MONGO_URI`) への ping が無応答または 1000ms 超を **3回連続**で検知 |
| `check_sessions` | `enable/*.sh` のセッション停止数が n(デフォルト：3) 以上 |
| `check_nav_failures` | MongoDB の直近 n(デフォルト：3) 件のナビゲーションが全て `failed` |

異常を検知すると Slack に理由を通知し、`hv_to_rescue.sh` を呼び出して自身は終了する。

---

### hv_to_rescue.sh（レスキューモード移行）

1. `$HOME/module_launch/enable/*.sh` のセッションを個別 kill
2. `hv_watch` セッションを kill
3. tmux セッション `hv_play_audio` 起動 → `help_request.wav` をループ再生
4. Slack 通知：`レスキューモードに入りました。充電ステーションへの誘導をお願いします。`
5. `motor_release_tool_for_rescue` 起動 → タイヤ解放コマンドを 50ms 周期で送信
6. バッテリー電流を 10 秒ごとに監視し、**電流がマイナス**（充電開始）を検知したら `hv_to_normal.sh` へ

---

### hv_to_normal.sh（通常モード復帰）

1. `hv_play_audio` セッションを kill（音声停止）
2. `return_to_normal.wav` を 1 回再生
3. サーバマシン への ping 平均が **20ms 以下**になるまで待機
4. `module_launch.sh` を実行してノード群を再起動
5. `check_sessions.sh` で停止セッション数が **0**になるまで監視（未達なら `module_launch.sh` をリトライ）
6. 充電ステーション位置に初期位置をセット
7. Slack 通知：`通常モードに戻りました。`

---

## Slack 通知タイミング

| タイミング | メッセージ |
|---|---|
| レスキュー移行直前 | `[ROBOT_NAME] レスキューモードに移行します。理由: <原因>` |
| レスキューモード開始後 | `[ROBOT_NAME] レスキューモードに入りました。充電ステーションへの誘導をお願いします。` |
| 通常モード復帰完了 | `[ROBOT_NAME] 通常モードに戻りました。` |

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
