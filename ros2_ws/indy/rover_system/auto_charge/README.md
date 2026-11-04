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

## 操作方法

### 1. Action インターフェース (推奨)
nav2_msgs/action/NavigateToPose型のactionを使用します。

**Action名**: `navigate_to_charge`

**使用例**:
```bash
# コマンドラインから実行
ros2 action send_goal /navigate_to_charge nav2_msgs/action/NavigateToPose "{}"
```

**特徴**:
- Goal内のPoseStampedは無視され、自動的に充電ステーションへナビゲート
- 充電開始検出: `rover/battery`の`current`が0.01以下になると成功
- タイムアウト:
  - ドッキング開始待機: 10秒（この時間内にドッキングが開始されない場合は充電ステーションが見つからないと判断）
  - 全体のタイムアウト: 60秒
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
|auto_charge/in_docking_process|std_msgs/msg/Bool|ドッキング処理中か否かのステータス|
|auto_charge/dock_target_pose|geometry_msgs/msg/PoseStamped|充電ステーションの相対位置・姿勢情報|
|auto_charge/robot_pose_from_target|geometry_msgs/msg/PoseStamped|ロボットの相対位置・姿勢情報|
|rover/stop|std_msgs/msg/Empty|ローバ停止指令|
|rover/cmd_vel|geometry_msgs/msg/Twist|ローバの速度指令|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|auto_charge/dock_start|std_msgs/msg/Empty|ドッキング開始指令|
|auto_charge/in_docking_process|std_msgs/msg/Bool|ドッキング処理中か否かのステータス|
|auto_charge/dock_target_pose|geometry_msgs/msg/PoseStamped|充電ステーションの相対位置・姿勢情報|
|robot/action_ctl|std_msgs/msg/String|"battery charge"を受け取ると自動充電開始|
|rover/scan|sensor_msgs/msg/LaserScan|LiDARのスキャンデータ|
|rover/battery|sensor_msgs/msg/BatteryState|バッテリー全体の情報|

**使用例**:
```bash
ros2 topic pub --once /auto_charge/dock_start std_msgs/msg/Empty
```

## ノード構成
- **auto_charge**: メインのドッキング制御ノード
- **lidar_marker_finder**: LiDARで充電ステーションマーカーを検出
- **navigate_to_charge_server**: nav2準拠のAction Serverノード