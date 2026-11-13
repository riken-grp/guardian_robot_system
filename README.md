# guardian_robot_system (公開準備中)

自律対話ロボット「Indy」を動かすためのソフトウェア一式です。  
また、本リポジトリの機能を使った別のロボットシステム「robodj」も含みます。

|システム|概要|必要なマシン|
|---|---|---|
|Indy|自律対話ロボット|ロボット搭載マシン + サーバマシン|
|robodj|2台のロボットによる会話システム|robodj + サーバマシン(MongoDB・時刻同期のみ)|

※Indyを動かすには、ロボット搭載マシンとサーバマシンの両方の構築が必要です。robodjの構築は不要です。  
※robodjを動かす場合も、MongoDBはサーバマシン上に構築します(robodj用のMongoDB)。

## はじめに読むドキュメント

|目的|ドキュメント|
|---|---|
|起動・終了、操作、設定の変更(パラメータ、シナリオ)、トラブル時の対応を知る|[docs/マニュアル/Indyマニュアル.md](docs/マニュアル/Indyマニュアル.md)|
|サーバマシンを構築する(Indy・robodj共通。**最初に実施**。MongoDB、時刻同期サーバを含む)|[docs/手順書/サーバマシン構築.md](docs/手順書/サーバマシン構築.md)|
|ロボット搭載マシンを構築する(Indy)|[docs/手順書/indy_ロボット搭載マシン構築.md](docs/手順書/indy_ロボット搭載マシン構築.md)|
|robodjを構築する(robodjを使う場合のみ)|[docs/手順書/robodj構築.md](docs/手順書/robodj構築.md)|
|ソフトウェアの構成(起動スクリプトの一覧)、マシン間の通信、MongoDBのデータ構成を知る|[docs/仕様書/Indyソフトウェア仕様書.md](docs/仕様書/Indyソフトウェア仕様書.md)|
|ローバのドライバ(amr_ros_driver。ソースコードは含まれない)のROSインターフェースを知る|[docs/仕様書/amr_ros_driver仕様書.md](docs/仕様書/amr_ros_driver仕様書.md)|
|ハードウェアの仕様を知る|[docs/仕様書/Indyハードウェア仕様書.md](docs/仕様書/Indyハードウェア仕様書.md)|

※他のマシンはサーバマシン上のMongoDBに接続して動作するため、サーバマシンを先に構築してください。  
※各パッケージ・ツールの詳細は、それぞれのフォルダのREADME.mdを参照してください。

## フォルダ構成

```
guardian_robot_system/
├── docs/                   ドキュメント
│   ├── マニュアル/          運用マニュアル
│   ├── 手順書/              マシンごとの構築手順書
│   └── 仕様書/              ソフトウェア仕様書、ハードウェア仕様書、amr_ros_driver仕様書
├── ros2_ws/                ROS 2ワークスペース(colcon buildでビルド)
│   └── indy/               Indyの各ROS 2パッケージ
├── modules/                ROS 2以外のモジュール
│   ├── module_launch/      起動スクリプト(tmuxセッションで一括起動・停止)
│   ├── scenario_manager/   シナリオ管理(rism)
│   ├── pyindy/             各モジュールが共通で使用するPythonライブラリ
│   └── indy_modules/       会話ログ配信(chat_monitor)、mic2sock、tmux設定などのツール
├── setup/                  環境構築用の設定
│   ├── mongo_docker/       MongoDB(Docker)の構成と標準データ
│   ├── container_image/    サーバマシン用Apptainerコンテナの定義
│   └── ros2/zenoh/         マシン間通信(zenoh-bridge-ros2dds)の設定
├── tools/
│   └── bin/                運用ツール(状態確認、ナビゲーション操作など)
├── indy.env.sample         環境変数設定のサンプル(~/indy.envにコピーして使用)
└── LICENSE
```
