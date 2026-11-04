# vel_filter
障害物回避機能

## 機能概要
- rover/cmd_velトピックを受け取り、RealSenseで取得したpointcloud情報を参照して、障害物を回避するrover/cmd_vel_filteredトピックを配信する。

## 起動方法
```
ros2 launch vel_filter vel_filter.launch.py
```

## 操作方法
### 主なROSトピック
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|rover/cmd_vel_filtered|geometry_msgs/Twist|障害物回避処理後の速度制御トピック|
|rover/nearest_camera_point|geometry_msgs/Vector3|Depthカメラで検出した最も近い障害物の座標|
|rover/nearest_scan_point|geometry_msgs/Vector3|LiDARで検出した最も近い障害物の座標|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|rover/cmd_vel|geometry_msgs/Twist|ローバの速度制御トピック|
|rover/scan|sensor_msgs/LaserScan|LiDARのスキャンデータ|
|vel_filter/set_max_velocity|std_msgs/Float64|ローバの最大速度制御トピック|
|($ROBOT_NAME)_camera_td/depth/camera_info|sensor_msgs/CameraInfo|Depthカメラの内部パラメータ|
|($ROBOT_NAME)_camera_td/depth/image_rect_raw|sensor_msgs/Image|Depthカメラの震度画像|

## 設定方法
### rosパラメータ
config/default_param.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|robot_height|1.5|ロボットの高さ [m]|
|robot_width|0.55|ロボットの幅 [m]|
|max_velocity|0.7|前進時の最大速度 [m/s]|
|min_back_velocity|‐0.1|後退時の最大速度 [m/s]|
|max_recog_range|10.0|カメラの最大認識距離 [m]|
|min_obstacle_range|0.28|最小障害物検知距離 [m]|
|max_obstacle_range|1.5|最大障害物検知距離(カメラ) [m]|
|max_scan_obstacle_range|0.5|最大障害物検知距離(LiDAR) [m]|
|min_cliff_range|0.7|最小段差検知距離 [m]|
|max_cliff_range|2.0|最大段差検知距離 [m]|
|filtering_factor|1.0|速度フィルターの補正係数|