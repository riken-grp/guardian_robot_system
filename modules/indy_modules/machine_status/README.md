# machine_status
マシンの状態を監視し、以下の情報をデータベースに記録する。

- CPU温度
- ロードアベレージ
- Wi-Fi信号強度
- Wi-Fi通信速度
- ディスク使用量
- メモリ空き容量

## ビルド方法
このパッケージは`ros2_ws`の外（`modules/indy_modules/machine_status`）にあるため、手順書の`colcon build`ではビルドされません。  
使用する場合は、以下のコマンドで`ros2_ws`にビルド・インストールしてください。
```
cd $GUARDIAN_ROBOT_PATH/ros2_ws
colcon build --base-paths $GUARDIAN_ROBOT_PATH/modules/indy_modules/machine_status
source install/setup.bash
```

## 起動方法
環境変数`ROBOT_NAME`が必須です（未設定の場合は起動しません）。ノードは`ROBOT_NAME`の名前空間で起動します。
```
ros2 launch machine_status machine_status_launch.py mongo_uri:=<アドレス> mongo_port:=<ポート番号>
```

## 設定方法
### rosパラメータ
config/default_param.yamlにて設定されている。

|parameter名|デフォルト値|概要|
|:--|:--|:--|
|report_rate|10.0|監視周期 [s]|
