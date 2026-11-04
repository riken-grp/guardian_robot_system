# chat_monitor
MongoDBからそれぞれのロボットの発言内容を取得し、チャット形式で表示します。  
必要に応じて、DeepLで英訳した文を表示します。

## 構成
- chet_monitor  
  日本語文を取得し、チャット形式で表示します。  
  自動翻訳をONにすると、DeepL翻訳した英文のみを表示します（[自動翻訳の設定](#自動翻訳の設定)を参照）。


## 利用前の初期設定
1. Node.jsのインストール  
   ```
   $ sudo apt install nodejs npm    ← Node.jsとnpmのインストール  
   $ sudo npm install -g n          ← nモジュールのインストール  
   $ sudo n lts                     ← LTS版のNode.jsにアップデート  
   $ sudo apt purge -y nodejs npm   ← 古いバージョンの削除  
   $ exec $SHELL -l
   $ node --version                 ← バージョン確認  
   ```

2. MongoDBのインストール
   ```
   $ sudo npm install mongodb       ※ ルートディレクトリ（/chat_monitor）で実行
   ```

3. expressのインストール
   ```
   $ sudo npm install express       ※ ルートディレクトリ（/chat_monitor）で実行
   ```

4. deepl-nodeのインストール
   ```
   $ sudo npm install deepl-node    ※ ルートディレクトリ（/chat_monitor）で実行
   ```

## 起動方法
1. ターミナルで下記に移動します。  
   パス：chat_monitor/chet_monitor/chat-bubble

2. 下記コマンドで表示システムを起動します。
   ```
   $ node getData.js
   ```

   起動時引数で、MongoDBの接続先と表示用のポート番号を指定できます。  
   省略した引数は config_server.js の値（下表のデフォルト値）が使われます。
   ```
   $ node getData.js --mongo_uri machine.local --mongo_port 9100 --display_port 3000
   ```

   | 引数 | 内容 | デフォルト値 |
   |---|---|---|
   | `--mongo_uri` | MongoDBのホスト名（`mongodb://` は付けない） | `example.local` |
   | `--mongo_port` | MongoDBのポート番号 | `9000` |
   | `--display_port` | 表示用（ブラウザでアクセスする）ポート番号 | `3000` |

   ※ `--mongo_port=9100` のように `=` 区切りでも指定できます。

3. ブラウザで開きます（ポート番号は `--display_port` で指定したもの。省略時は config_server.js で設定したもの）。


## 終了方法
1. ブラウザのタブを閉じます。

2. Ctrl + c で、システムを終了します。


## 設定方法
chet_monitor ディレクトリの下記ファイルから、動作やデザインを設定できます。

- デザイン：settings.css
- クライアント（フロントエンドの動作）：config_client.js
- サーバー（バックエンドの動作）：config_server.js

設定を反映するには、システムを再起動してください。

### 自動翻訳の設定
config_server.js の `enableTranslation` で、DeepLによる自動翻訳のON/OFFを切り替えます。

| 値 | 動作 |
|---|---|
| `true` | 日本語文をDeepLで英訳し、英文のみを表示します。 |
| `false`（デフォルト） | 日本語文をそのまま表示します。DeepL APIは呼び出しません。 |

自動翻訳をONにする場合は、DeepLのAPIキーを環境変数 `DEEPL_API_KEY` に設定してから起動してください。
```
$ export DEEPL_API_KEY=<DeepLのAPIキー>
$ node getData.js
```
翻訳に失敗した場合は、config_server.js の `translation_failed_text` に設定した文が表示されます。

## 注意事項
- スクロールし遡って表示できる発言数を、メモリ解放のため一定数（ config_client.js から変更可能です）に制限しています。古い発言は表示から自動で消えます。
- ブラウザのタブを複製すると、別個に独立したシステムが起動します。ひとつのシステムですべてのタブにチャットを表示しているわけではありません。
- ブラウザの画面幅を変更すると、一時的にデザインが乱れることがあります。
- 右側の吹出しをマウスでホバーやクリックすると、表示が乱れます。
