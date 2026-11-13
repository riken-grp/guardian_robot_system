# sensor_tf_publisher
MongoDBから各センサーの位置・オイラー角を取得し、クォータニオンに変換したうえで、静的TFとしてTF2へ配信する。

## 起動方法
```
ros2 launch sensor_tf_publisher sensor_tf_publisher_launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
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
  |sensor_tf|angle|相対座標の姿勢情報（roll,pitch,yaw）[rad]|

  `name`が`sensor_tf`のDocumentの`config`には、TFごとに任意のキー（TFの識別名）を置き、その下に上記4項目を入れ子で記述する。

  ```json
  {
    "name": "sensor_tf",
    "config": {
      "<TFの識別名>": {
        "parent_frame": "base_link",
        "child_frame": "<センサのフレーム名>",
        "pos": [0.0, 0.0, 0.0],
        "angle": [0.0, 0.0, 0.0]
      }
    }
  }
  ```

  - ノードは`/$ROBOT_NAME`名前空間で起動し、配信するTFのフレーム名には`<ROBOT_NAME>_`が先頭に付く（上の例では`<ROBOT_NAME>_base_link`→`<ROBOT_NAME>_<センサのフレーム名>`）。
  - 標準データ（`setup/mongo_docker/default_data/robot_config.system_parameters.json`）の`sensor_tf`の`config`は空のため、そのままではTFは配信されない。
