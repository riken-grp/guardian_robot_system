# machine_status
マシンの状態を監視し、以下の情報をデータベースに記録する。

- CPU温度
- ロードアベレージ
- Wi-Fi信号強度
- Wi-Fi通信速度
- ディスク使用量
- メモリ空き容量

## 起動方法
```
ros2 launch machine_status machine_status_launch.py mongo_uri:=<アドレス> mongo_port:=<ポート番号>
```

## 設定方法
### rosパラメータ
config/default_param.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|report_rate|10.0|監視周期 [s]|
