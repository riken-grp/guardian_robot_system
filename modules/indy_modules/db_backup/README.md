# db_backup
スクリプトは`$GUARDIAN_ROBOT_PATH/modules/indy_modules/db_backup/scripts/`にある。  
MongoDBの接続先は、環境変数`MONGO_URI`（ホスト名）、`MONGO_PORT`（ポート番号）から取得する（`~/indy.env`で設定）。  
`mongodump` / `mongorestore`（MongoDB Database Tools）と、Pythonの`pymongo`が必要。

## バックアップの実行
### 概要
毎日0時に、データベース（デフォルト値：log）の当日分のデータをファイルにバックアップする。  
バックアップに成功した場合は、元のデータベースから7日前の日付のデータを削除する（`log_text`コレクションは削除対象外）。  
これにより、データベースには直近7日分程度のデータが残り、それ以前のデータはバックアップファイルにのみ残る。

- バックアップの保存先：`~/mongo_backup/<yyyymmdd>/<データベース名>/`
- 削除したデータのうち`status`が`OK`以外のものは、`~/mongo_backup/fail_log/<yyyymmdd>_status.txt`に記録される。

### 操作手順
`crontab -e`で、以下の行を追記してバックアップの定期実行を登録する。  
cronは`~/.bashrc`を読まないため、行の先頭で`~/indy.env`を読み込む。
```
0 0 * * * . $HOME/indy.env; bash $GUARDIAN_ROBOT_PATH/modules/indy_modules/db_backup/scripts/execute_backup.sh
```
※ `crontab <ファイル>`は、既存のcrontabの内容をすべて置き換えるため使用しないこと。  
※ `scripts/cron_mongo_backup`は登録内容の例だが、`~/db_backup`に配置する前提で環境変数の読み込みもないため、そのままでは使用できない。

バックアップ対象のデータベース名は`execute_backup.sh`の`DB_NAME`で設定する（デフォルト値：log）。

## データの復元  
### 概要
指定した日付のデータをバックアップファイルからデータベースに復元する。

### 操作手順
以下のコマンドを実行する。
```
bash $GUARDIAN_ROBOT_PATH/modules/indy_modules/db_backup/scripts/restore_db.sh ※日付※
```
- 日付：データを復元する日付（yyyymmdd）。（例：20260101）

復元先のMongoDBの接続先は、環境変数`MONGO_URI`、`MONGO_PORT`から取得する。  
復元先のデータベース名は`restore_db.sh`の`DB_NAME`で設定する（デフォルト値：ReadOnlyLog）。  
復元元は`~/mongo_backup/<日付>/log/`（logデータベースのバックアップ）。
