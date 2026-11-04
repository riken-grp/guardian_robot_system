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
|/$ROBOT_NAME/right(left)_arm/goal_pose|geometry_msgs/Pose|手先位置制御コマンド（Quaternion）|
|/$ROBOT_NAME/right(left)_arm/euler_goal_pose|flamingo_grp_msgs/EulerPoseStamped|手先位置制御コマンド（Euler角）|
|/$ROBOT_NAME/right(left)_arm/euler_way_and_end_pose|flamingo_grp_msgs/EulerWayEndPoseStamped|経由点付き手先位置制御コマンド（Euler角）|

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

- 手先位置指令(Quaternion)
  - 目標位置・姿勢を入力して、モータを回転させる。
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

- 手先位置指令(Euler角)
  - 目標位置・姿勢を roll, pitch, yaw で入力して、モータを回転させる。
  - `point` が位置 [m]、`vector` が姿勢 (x=roll, y=pitch, z=yaw) [rad]。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right(left)_arm/euler_goal_pose flamingo_grp_msgs/msg/EulerPoseStamped "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  point:
    x: 0.1
    y: 0.2
    z: 0.3
  vector:
    x: 0.0
    y: 0.0
    z: 0.0"
  ```

- 経由点付き手先位置指令
  - 経由点と目標位置・姿勢(roll, pitch, yaw)を入力して、モータを回転させる。
  ```
  ros2 topic pub -1 /$ROBOT_NAME/right(left)_arm/euler_way_and_end_pose flamingo_grp_msgs/msg/EulerWayEndPoseStamped "header:
    stamp:
      sec: 0
      nanosec: 0
    frame_id: ''
  way_point:
    x: 0.1
    y: 0.2
    z: 0.3
  way_vector:
    x: 0.0
    y: 0.0
    z: 0.0
  end_point:
    x: 0.2
    y: 0.3
    z: 0.4
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
|kinematics.yaml|IKソルバの設定|
|joint_limits.yaml|速度・加速度制限。`default_velocity_scaling_factor` で全体をスケールする|
|moveit_controllers.yaml|コントローラ設定|

速度制限は arm_motor_control 側の `max_velocity` とは独立に設定されている。
片方のみを変更すると不整合になるため注意すること。
