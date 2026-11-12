# Module Launch

## 概要
機能ごとにtmuxセッションを開いて、機能を起動するためのスクリプトのセットです。
- 以下のコマンドによってenableフォルダ内に格納された機能（スクリプト）が一括起動されます。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/module_launch.sh
  ```
  - enableフォルダ内のスクリプトがファイル名順でソートされて起動します。
- 各tmuxセッションごとに1つのlaunchファイルが実行されるようになっています。
  - セッション内で起動しているノードが1つでも停止したら、tmuxセッションが終了するようになっています。
  - デバッグの際は、セッションが落ちてエラーメッセージを確認できないため、個別のターミナルでlaunchを実行ことを推奨します。
- 起動している機能(tmuxセッション)の一覧は以下のスクリプトによって確認できます。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/check_sessions.sh
  ```

## マシンごとのセッティング方法
1. module_launchディレクトリはリポジトリ内（`$GUARDIAN_ROBOT_PATH/modules/module_launch`）のものをそのまま使用します。
2. デフォルトではavailableフォルダ内に基本的な起動スクリプトが配置されています。  
   その中からマシンごとに一括起動したいスクリプトをenableフォルダにコピー（またはシンボリックリンクを作成）してください。  
   ※ availableフォルダ内のスクリプトはリポジトリ管理対象のため、移動はしないでください。enableフォルダ内のスクリプトはgit管理対象外です。
   ```
   cd $GUARDIAN_ROBOT_PATH/modules/module_launch
   ln -s ../available/02_indyXe_map.sh enable/
   ```
3. module_launch.sh / scenario_launch.sh 等は guardian_robot_system のパス、ロボット名、MongoDBの接続先を環境変数から取得します。  
   リポジトリ直下の`indy.env.sample`を`indy.env`にコピーして編集し、`~/.bashrc`等で読み込んでください（未設定の場合、スクリプトはエラー終了します）。
   ```
   export GUARDIAN_ROBOT_PATH=<guardian_robot_systemディレクトリのPATH>
   export ROBOT_NAME=<ロボット名>     # scenario_launch.sh で使用
   export MONGO_URI=<MongoDBのホスト名 or IPアドレス>
   export MONGO_PORT=<MongoDBのポート番号>
   ```

## 使用方法
### 機能の一括起動方法
- 各マシンにて、以下のシェルスクリプトを実行してください。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/module_launch.sh
  ```
### シナリオの起動方法
- シナリオ起動マシンにて、以下のシェルスクリプトを実行してください。
  ```
  $GUARDIAN_ROBOT_PATH/modules/module_launch/scenario_launch.sh
  ```
### 機能の個別の起動方法
- 以下のコマンドにて対象機能起動用のシェルスクリプトを実行してください。  
  MongoDBの接続先は以下のいずれかの方法で指定できます。
  ```
  # 環境変数を使用する場合、引数不要
  $GUARDIAN_ROBOT_PATH/modules/module_launch/enable(or available)/--.sh

  # 引数で設定する場合
  $GUARDIAN_ROBOT_PATH/modules/module_launch/enable(or available)/--.sh <MONGO_URI> <MONGO_PORT>
  ```

## 機能ごとの起動スクリプトの設定
以下の形式で起動用シェルスクリプトが用意されています。  
例）available/02_indyXe_rover_base.sh
```
#!/bin/bash

SLEEP_SEC=1

filename=$(basename "$0" .sh)
tmux_sessions=$(tmux ls 2>/dev/null | cut -d':' -f1)

if [ $# -ne 2 ]; then
  echo "$filename" failed
  echo "Arguments are needed ($(basename "$0") MONGO_URI MONGO_PORT)"
  exit 1
fi

if echo "$tmux_sessions" | grep -q "^$filename$"; then
  echo "$filename" already exists
else
  echo "$filename" is launching...
  tmux new -d -s $filename bash -c "source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash;
                                    ros2 launch rover_tools rover_base.launch.py mongo_uri:=$MONGO_URI mongo_port:=$MONGO_PORT"
  echo "sleep: $SLEEP_SEC [s]"
  sleep $SLEEP_SEC
  echo "$filename" started
fi
```
- ROSパッケージは `$GUARDIAN_ROBOT_PATH/ros2_ws` のビルド結果（install/setup.bash）を読み込んで起動します。
- tmuxのセッション名はファイル名（.shを除いた部分まで）になっています。
- tmux new -d -sから始まる行の""内で起動するlaunchファイルを指定しています。
- 機能によっては起動後安定するまでsleepを入れています。