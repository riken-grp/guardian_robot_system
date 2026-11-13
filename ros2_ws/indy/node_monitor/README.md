# node_monitor
ROS2ノードの生存状態を監視し、データベースに記録する。

## 起動方法
```
ros2 launch node_monitor node_monitor.launch.py mongo_uri:=<アドレス> mongo_port:=<ポート番号>
```

## 設定方法
### rosパラメータ
config/node_monitor.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|report_rate|10.0|監視周期 [s]|
|node_list|- joint_state_publisher<br>- robot_state_publisher<br>- AttributeRecognitionNode<br>- ...|監視対象ノードリスト（`/<ROBOT_NAME>/`からの相対名）|