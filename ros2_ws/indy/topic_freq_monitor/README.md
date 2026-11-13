# topic_freq_monitor
ROS2トピックの受信周波数を監視し、データベースに記録する。

## 起動方法
```
ros2 launch topic_freq_monitor topic_freq_monitor_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
```

## 設定方法
### rosパラメータ
config/topic_freq_monitor.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|update_rate|10.0|監視周期 [s]|
|timeout_time|3.0|タイムアウト時間 [s]|
|comp_ratio|3.0|補正率|
|queue_size|10|周期の計算に使う直近の受信時刻の保持件数（コード既定値は5）|
|topic_list|[human_tracker/recognition_result, human_tracker_msgs, TrackedPersons, "10.0", ...]|監視対象トピックリスト|