# arm_moveit_driver
目標関節角度や目標姿勢を受信し、MoveItで経路生成し、その結果をトピックとして配信する。

## ビルド方法
本パッケージは環境変数 `ON_ROBOT` が `1` の場合のみビルドされる。それ以外の場合はスキップされる。
```
export ON_ROBOT=1
colcon build --packages-select arm_moveit_driver
```

## 起動方法
事前に環境変数 `ROBOT_NAME` を設定しておく必要がある。未設定の場合、launchは何も起動せずに終了する。
```
export ROBOT_NAME=<ロボット名>
ros2 launch arm_moveit_driver bringup_arm_moveit_driver.launch.py
```

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/joint_trajectory|trajectory_msgs/JointTrajectory|MoveItから出力された、アームへの指令値を配信|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|/$ROBOT_NAME/right(left)_arm/goal_joints|sensor_msgs/JointState|モータごとの角度制御コマンド|
|/$ROBOT_NAME/right(left)_arm/goal_pose|geometry_msgs/Pose|手先位置制御コマンド（腕基準・位置のみ）|
|/$ROBOT_NAME/right(left)_arm/euler_goal_pose|flamingo_grp_msgs/EulerPoseStamped|手先位置制御コマンド（frame_id 基準・位置のみ）|
|/$ROBOT_NAME/right(left)_arm/euler_way_and_end_pose|flamingo_grp_msgs/EulerWayEndPoseStamped|経由点付き手先位置制御コマンド（frame_id 基準・位置のみ）|

### 操作方法
- 目標角度指令
  - 目標角度を入力して、モータを回転させる。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right(left)_arm/goal_joints sensor_msgs/msg/JointState "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  name: [bracket_arm_a_joint, bracket_arm_b_joint, bracket_arm_c_joint, bracket_arm_d_joint]
  position: [0.1, 0.2, 0.3, 0.4]
  velocity: [0.0, 0.0, 0.0, 0.0]
  effort: [0.0, 0.0, 0.0, 0.0]"
  ```
  - **`name` フィールドは使用されない。** 受信側は `position` のみを参照するため、値は
    SRDFのグループ `arm` に定義された並び順（bracket_arm_a → b → c → d）で指定すること。
    順序を誤ると意図しない関節が動作する。`velocity` と `effort` も使用されない。

- 手先位置指令の共通事項（goal_pose / euler_goal_pose / euler_way_and_end_pose）
  - 腕は4軸のため、**手先は位置のみ指定できる。姿勢（orientation / roll・pitch・yaw）は無視される。**
  - 本ノード内で IK を解き、関節制限（arm_motor_control.yaml の可動範囲から 0.05rad 内側）と
    胴体との干渉を判定したうえで、得た関節角を goal_joints と同じ経路で MoveIt に入力する。
    解が無い場合（到達範囲外・可動範囲外・胴体干渉）は指令を破棄し、ERROR ログに内訳を出す。
  - 冗長な1自由度（肘の向き）は、現在の関節角（`joints`）に最も近い解を選ぶ。`joints` が 1 秒以上届いていない場合は指令を破棄する。
  - 座標系（header.frame_id）
    - 空 / `world` / `base_link` : 腕モデルの base_link 基準（関節角がすべて 0 のとき腕が伸びる向きが +z）
    - `<ROBOT_NAME>_body_link` : 胴体基準（前 +x、左 +y、上 +z）。取り付け位置で腕基準に変換する
    - 上記以外 : 拒否
  - 腕の取り付け位置と干渉判定の箱は `amr_description/urdf/arm_mount.yaml` で定義する（amr.xacro と共有。**現在は仮値**）。
    このファイルまたは arm_motor_control.yaml を読めない場合、手先位置指令は無効になる（関節角指令は従来どおり動く）。
  - 関節角は arm_motor_control.yaml の gain の大きさで実角度に換算して IK を解く（実角度 = |gain| × 関節角指令。gain が ±1.0 なら換算なし）。
  - 胴体干渉は目標姿勢でのみ判定する。移動途中の干渉、反対側の腕・頭との干渉は判定しない。

- 手先位置指令(goal_pose)
  - 腕基準の目標位置を入力して、モータを回転させる。orientation は無視される。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right(left)_arm/goal_pose geometry_msgs/msg/Pose "position:
    x: 0.1
    y: 0.2
    z: 0.3
  orientation:
    x: 0.0
    y: 0.0
    z: 0.6
    w: 0.8"
  ```

- 手先位置指令(euler_goal_pose)
  - header.frame_id 基準の目標位置を入力して、モータを回転させる。
  - `point` が位置 [m]。`vector`（roll, pitch, yaw）は無視される。
  - 例は右腕で胴体の右前方へ動かす場合（frame_id を空にすると腕基準）。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right_arm/euler_goal_pose flamingo_grp_msgs/msg/EulerPoseStamped "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: '<ROBOT_NAME>_body_link'
  point:
    x: 0.17
    y: -0.46
    z: 0.10
  vector:
    x: 0.0
    y: 0.0
    z: 0.0"
  ```

- 経由点付き手先位置指令(euler_way_and_end_pose)
  - header.frame_id 基準の経由点→終点の位置を入力して、モータを回転させる。way_vector / end_vector は無視される。
  - 経由点・終点とも解がある場合のみ、経由点、終点の順に関節角指令を出す（終点の IK は経由点の解を初期値にする）。
  - 注意: arm_motor_control は新しい joint_trajectory を受けると実行中の指令を打ち切るため、経由点を通過する保証はない（従来からの挙動）。
  - 例は右腕・胴体基準。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right_arm/euler_way_and_end_pose flamingo_grp_msgs/msg/EulerWayEndPoseStamped "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: '<ROBOT_NAME>_body_link'
  way_point:
    x: 0.10
    y: -0.33
    z: 0.01
  way_vector:
    x: 0.0
    y: 0.0
    z: 0.0
  end_point:
    x: 0.17
    y: -0.46
    z: 0.10
  end_vector:
    x: 0.0
    y: 0.0
    z: 0.0"
  ```

- アームへの指令値配信
  - モータの動作指令を受けた場合、以下の値を配信する。
  ```
  header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: world
  joint_names:
  - bracket_arm_a_joint
  - bracket_arm_b_joint
  - bracket_arm_c_joint
  - bracket_arm_d_joint
  points:
  - positions:
    - 0.0
    - 0.0
    - 0.0
    - 0.0
    velocities:
    - -0.0
    - -0.0
    - 0.0
    - 0.0
    accelerations:
    - 0.0
    - 0.0
    - 0.0
    - 0.0
    effort: []
    time_from_start:
      sec: 0
      nanosec: 0
  - positions:
    - -0.04962529595860957
    - -0.19811454556171196
    - 0.2972205471571707
    - 0.3963928789388916
    velocities:
    - -0.010617059237718633
    - -0.04238551781810546
    - 0.06358870198913855
    - 0.08480607713884875
    accelerations:
    - 0.12519219843701282
    - 0.4997934021775235
    - -0.7498130338667006
    - -1.0000000000105913
    effort: []
    time_from_start:
      sec: 1
      nanosec: 500000000
  ```

## 設定方法
MoveItの設定は `config/` 配下にある。主なものは以下の通り。

|ファイル|概要|
|---|---|
|guardian.urdf.xacro|ロボットモデル（guardian_urdfのURDFを参照）|
|guardian.srdf|プランニンググループ `arm` と関節の定義|
|kinematics.yaml|IKソルバの設定（move_group 用）|
|kinematics_pose_ik.yaml|手先位置指令用の IK 設定（本ノード内のみで使用。位置のみで解く）|
|joint_limits.yaml|速度・加速度制限。`default_velocity_scaling_factor` で全体をスケールする|
|moveit_controllers.yaml|コントローラ設定|

速度制限は arm_motor_control 側の `max_velocity` とは独立に設定されている。
片方のみを変更すると不整合になるため注意すること。
