# human_tracker
複数センサー（LiDAR／カメラ／音声）の情報を統合して人間を検出・追跡し、ROSトピック・RVizへ配信する。

## 起動方法
```
ros2 launch human_tracker human_tracker.launch.py
```

## 操作方法
### 主なrosパラメータ
**publish**
|トピック名|トピックタイプ|概要|
|---|---|---|
|human_tracker/person_all_info|human_tracker_msgs/PersonAllInfoList|すべての人間の追跡情報（ID、位置、姿勢、顔の角度）|
|human_tracker/audio_info|human_tracker_msgs/AudioInfoList|音声情報（位置、時間情報、人間の識別情報）|
|human_tracker/facepose_on_world|human_tracker_msgs/FacePoses|顔の位置と方向（ワールド座標系）|
|human_tracker/recognition_result|human_tracker_msgs/TrackedPersons|追跡された人間のリスト（ID、位置、分離ID）|
|human_tracker/human_pose_marker|visualization_msgs/MarkerArray|追跡された人間の位置と方向（ワールド座標系）|

**subscribe**
|トピック名|トピックタイプ|概要|
|---|---|---|
|human_tracker/audio_info|human_tracker_msgs/AudioInfoList|音声情報（位置、時間情報、人間の識別情報）|
|human_tracker/recognition_result|human_tracker_msgs/TrackedPersons|追跡された人間のリスト（ID、位置、分離ID）|
|scan|sensor_msgs/LaserScan|LiDARスキャンデータ|
|recog/person/pose/associated|recognition_msgs/Persons|カメラ認識結果（人物のポーズ）|

## 設定方法
### rosパラメータ
- 以下は、config/human_tracker.yamlにて設定されている。
  |parameter名|デフォルト値|概要|
  |:--|:--|:--|
  |scan_topic_name|'scan'|LiDARスキャントピック名|
  |seperate_acceptable_angle|5.0|分離時の許容角度 [deg]|
  |seperate_distance|0.2|分離時の距離閾値 [m]|
  |camera_link|'camera_link'|カメラリンク名|
  |robot_link|'base_link'|ロボットリンク名|
  |lidar_link|'lidar_link'|LiDARリンク名|
  |max_recog_range|4.0|最大認識距離 [m]|
  |upper_recog_angle|45.0|認識角度上限値 [deg]|
  |lower_recog_angle|-45.0|認識角度下限値 [deg]|
  |camera_integration|false|カメラ統合の有無|
  |camera_associated_topic|'recog/person/pose/associated'|カメラ関連トピック名|
  |camera_topic_hold_time|5.0|カメラトピック保持時間 [s]|
  |camera_obj_distance|0.3|カメラオブジェクト距離 [m]|
  |camera_max_fov|30.0|最大カメラ視野角 [deg]|
  |camera_min_fov|-30.0|最小カメラ視野角 [deg]|
  |camera_max_range|5.0|カメラ認識距離上限値 [m]|
  |outrange_hold_time|-1.0|距離外保持時間 [s] (値が0.0未満の場合は制限なし)|
  |outrange_hold_range|-1.0|距離外保持距離 [m] (値が0.0未満の場合は制限なし)|
  |fusion_side_arm|false|サイドアーム融合フラグ|
  |arm_range|0.2|アーム認識距離 [m]|
  |min_object_size|0.15|最小物体サイズ [m]|
  |max_object_size|0.7|最大物体サイズ [m]|
  |too_close_range|0.4|過剰近距離閾値 [m]|
  |object_queue_size|20|オブジェクトキューのサイズ|
  |priority_range|1.8|優先範囲 [m]|
  |priority_min_angle|-45.0|最小優先角度 [deg]|
  |priority_max_angle|45.0|最大優先角度 [deg]|
  |sep_hold_time|5.0|分離保持時間 [s]|
  |range_weight|2.0|距離重み(値が大きいほど、距離が近い人間が優先的に追跡対象となる)|
  |angle_weight|1.0|角度重み(値が大きいほど、正面に近い人間が優先的に追跡対象となる)|
  |face_direction_weight|0.5|顔方向重み(値が大きいほど、ロボットの方を向いている人間が優先的に追跡対なる)|
  |prority_sep_num|2|優先分離数|
  |max_sep_id|6|最大分離ID|
  |trace_range|0.2|追跡範囲 [m]|
  |trace_count|50|追跡回数|
  |human_trace_rate|0.8|人間追跡率|
  |max_trace_rate|0.6|最大追跡率|
  |min_trace_rate|0.2|最小追跡率|
  |human_hold_time|5.0|人間保持時間 [s]|
  |human_center|0.15|人間中心位置 [m]|
  |rviz_fixed_frame|'base_link'|RViz固定フレーム|
  |rviz_view_text|"human_id"|RViz表示テキスト（"name" or "human_id" or "sep_id"）|
  |client_number|10|クライアント数|
  |check_linearity|false|直線性チェックフラグ|
  |linearity_limit|1.0|直線性制限|
  |check_rightangle|false|直角チェックフラグ|
  |min_rightangle_limit|85.0|直角下限値 [deg]|
  |max_rightangle_limit|95.0|直角上限値 [deg]|
  |check_dent|false|凹凸チェックフラグ|
  |dent_limit|0.3|凹凸制限 [m]|
  

- 以下は、config/facepose_publisher.yamlにて設定されている。
  |parameter名|デフォルト値|概要|
  |:--|:--|:--|
  |world_frame|"map"|ワールドフレーム名|
  |robot_frame|"body_link"|ロボットフレーム名|
  

- 以下は、config/ros_audio_tracker.yamlにて設定されている。
  |parameter名|デフォルト値|概要|
  |:--|:--|:--|
  |client_number|10|クライアント数|
  |msg_size|4096|メッセージサイズ|
  |socket_length|13|ソケット長|
  |need_transform|false|座標変換フラグ|
  |audio_ip|"192.168.1.85"|音声IPアドレス|
  |audio_port|7890|音声サーバのポート番号|
  |client_number|10|クライアント数|
  |msg_size|4096|メッセージサイズ|
  |socket_length|13|ソケット長|
  |need_transform|true|座標変換フラグ|
  |robot_link|`<ROBOT_NAME>_base_link`（launchで設定）|ロボットリンク名|
  |camera_link|at_camera_link|カメラリンク名|

### MongoDBパラメータ
- 以下は、MongoDBで設定されている。  
  DB: `robot_config`  
  Collection: `system_parameters`
  
  |document名|parameter名|概要|
  |:--|:--|:--|
  |human_tracker|audio_port|追跡結果配信用の待受ポート番号|
  |ros_audio_tracker|audio_ip|音声サーバのIPアドレス|
  |ros_audio_tracker|audio_port|音声サーバのポート番号|

  ※human_tracker/audio_portとros_audio_tracker/audio_portはそれぞれ別のポートを指します。  
  ※config/ros_audio_tracker.yamlのaudio_portとros_audio_tracker/audio_portは同じポートを指します。  
  　どちらも設定されている場合は、MongoDB側の値が優先されます。