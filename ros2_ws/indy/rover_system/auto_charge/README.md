# auto_charge
自動充電機能

## 機能概要
- 充電ステーションへの自動ドッキングを行う
  - ロボットの背後3m x 3mの空間内の充電ステーションを探してドッキングする
- 2つのインターフェースを提供：
  1. **トピックベース**: `auto_charge/dock_start`トピックでドッキング開始
  2. **Actionベース**: nav2準拠の`navigate_to_charge` actionでドッキング開始と進行状況のフィードバック

## 起動方法
```bash
ros2 launch auto_charge auto_charge.launch.py
```
- 3つのノードはすべて`/$ROBOT_NAME`名前空間で起動する（環境変数`ROBOT_NAME`が必要）。以下のトピック名・Action名は名前空間からの相対名で、実際の名前は`/$ROBOT_NAME/...`となる。

## 操作方法

### 1. Action インターフェース (推奨)
nav2_msgs/action/NavigateToPose型のactionを使用します。

**Action名**: `navigate_to_charge`（実際の名前は`/$ROBOT_NAME/navigate_to_charge`）

**使用例**:
```bash
# コマンドラインから実行
ros2 action send_goal /$ROBOT_NAME/navigate_to_charge nav2_msgs/action/NavigateToPose "{}"
```

**特徴**:
- Goal内のPoseStampedは無視され、自動的に充電ステーションへナビゲート
- 成功の判定（2段階）:
  1. `rover/battery`の`current`が0.01以下の状態が3秒続く（パラメータ `charge_confirm_time`）。
     一瞬だけ0.01以下になっても成功にしない（接点が触れただけでauto_chargeが動き続けることがあるため）。
     途中で0.01を超えたら数え直す。
  2. auto_chargeがまだ動いていれば`auto_charge/dock_cancel`で止め、止まった（`in_docking_process`がFalse）あとも
     充電が2秒続いたら成功（パラメータ `charge_settle_time`）。ここで充電が止まったら失敗。
     auto_chargeが5秒以内に止まらなければ失敗（パラメータ `stop_wait_timeout`）。
  - 成功したときは auto_charge は止まっている
- タイムアウト:
  - ドッキング開始待機: 10秒（この時間内にドッキングが開始されない場合は充電ステーションが見つからないと判断）
  - 全体のタイムアウト: 180秒（充電が始まるまで。パラメータ `docking_timeout`、開始待機は `docking_start_wait_timeout`）
    - launch 引数でも変えられる: `ros2 launch auto_charge auto_charge.launch.py docking_timeout:=150.0`
    - RISM は dock の完了を `executor.default_dock_timeout`（既定200秒）まで待つ。ロボットが先に失敗を返すよう、
      これより短くすること（成功の確認に最大7秒ほど足される）。長くするときは RISM 側の設定も合わせて延ばす
- 失敗・キャンセルのときは `auto_charge/dock_cancel` を送って auto_charge を止め、`in_docking_process` が False に
  なる（ローバが止まった）のを確かめてから結果を返す。止まらなければ0.5秒ごとに送り直す（最大3秒、パラメータ
  `cancel_confirm_timeout`）
- 失敗のログに理由・経過時間・`docking_timeout` の値が出る（例: `Navigate to charge failed: overall docking timeout
  (elapsed 180.1 s, docking_timeout 180.0 s, ...)`）
- 動いているノードが新しいコードか確かめるには、goal を受けたときのログ
  `Executing navigate to charge (docking_timeout 180.0 s, ...)` を見る。古いコード（60秒で打ち切り、`dock_cancel`
  なし）はこの行を出さない
  - `settings/module_launch/available/02_indyXe_rover_base.sh` は tmux のセッションが残っていると起動し直さない
    （`already exists`）。ビルドし直したあとは `tmux kill-session -t 02_indyXe_rover_base` してから起動する
- Feedbackで進行状況を取得可能

**Result**:
- ROS2 Humbleの`NavigateToPose`では、Resultは`std_msgs/Empty`
- 成功/失敗は`ActionClient`のステータスで判定:
  - `SUCCEEDED`: 充電開始に成功
  - `ABORTED`: タイムアウトまたはドッキング失敗
  - `CANCELED`: ユーザーによるキャンセル

### 2. トピック インターフェース (従来方式)

**主なROSトピック**

**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|auto_charge/dock_start|std_msgs/msg/Empty|ドッキング開始指令|
|auto_charge/dock_cancel|std_msgs/msg/Empty|ドッキング中止指令（受信するとローバを停止し内部状態を初期化する）|
|auto_charge/in_docking_process|std_msgs/msg/Bool|ドッキング処理中か否かのステータス（終了処理でローバを止めたあとFalseになる）|
|auto_charge/dock_target_pose|geometry_msgs/msg/PoseStamped|充電ステーションの相対位置・姿勢情報|
|auto_charge/robot_pose_from_target|geometry_msgs/msg/PoseStamped|ロボットの相対位置・姿勢情報|
|rover/stop|std_msgs/msg/Empty|ローバ停止指令|
|rover/cmd_vel|geometry_msgs/msg/Twist|ローバの速度指令|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|auto_charge/dock_start|std_msgs/msg/Empty|ドッキング開始指令|
|auto_charge/dock_cancel|std_msgs/msg/Empty|ドッキング中止指令（受信するとローバを停止し内部状態を初期化する）|
|auto_charge/in_docking_process|std_msgs/msg/Bool|ドッキング処理中か否かのステータス|
|auto_charge/dock_target_pose|geometry_msgs/msg/PoseStamped|充電ステーションの相対位置・姿勢情報|
|robot/action_ctl|std_msgs/msg/String|"battery charge"を受け取ると自動充電開始|
|rover/scan|sensor_msgs/msg/LaserScan|LiDARのスキャンデータ|
|rover/battery|sensor_msgs/msg/BatteryState|バッテリー全体の情報|

**使用例**:
```bash
ros2 topic pub --once /$ROBOT_NAME/auto_charge/dock_start std_msgs/msg/Empty
```

ドッキング中に届いた `dock_start` は捨てる（終わったあとに続けてドッキングを始めない）。

## ノード構成
- **auto_charge**: メインのドッキング制御ノード
- **lidar_marker_finder**: LiDARで充電ステーションマーカーを検出
- **navigate_to_charge_server**: nav2準拠のAction Serverノード