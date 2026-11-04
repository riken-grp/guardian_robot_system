# sensor_tf_publisher
MongoDBから各センサーの位置・オイラー角を取得し、クォータニオンに変換したうえで、静的TFとしてTF2へ配信する。

## 起動方法
```
ros2 launch sensor_tf_publisher sensor_tf_publisher_launch.py mongo_uri:=<アドレス> mongo_port:=<ポート番号>
```

## 設定方法
### MongoDBパラメータ
- 以下は、MongoDBで設定されている。  
  DB: `robot_config`  
  Collection: `system_parameters`
  
  |document名|parameter名|概要|
  |:--|:--|:--|
  |sensor_tf|parent_frame|基準座標|
  |sensor_tf|child_frame|相対座標|
  |sensor_tf|pos|相対座標の位置情報（x,y,z）|
  |sensor_tf|angle|相対座標の姿勢情報（roll,pitch,yaw）|
