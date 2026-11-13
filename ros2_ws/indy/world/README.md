# world
MongoDBで設定された2種類のマップファイル(通常マップ、keepoutマップ)を読み込み、ROSトピックとして配信する。

## 起動方法
```
ros2 launch world map_grp_space.launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT
```

## 設定方法
### MongoDBパラメータ
- 以下は、MongoDBで設定されている。  
  DB: `robot_config`  
  Collection: `system_parameters`
  
  |document名|parameter名|概要|
  |:--|:--|:--|
  |map_server|map_yaml_file|通常マップのyamlファイル名|
  |map_server|keepout_yaml_file|keepoutマップのyamlファイル名|