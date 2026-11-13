# internet_speed_monitor
各スクリプトは`script/`ディレクトリにあります。以下のコマンドは、このディレクトリに移動してから実行してください。
```
cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/internet_speed_monitor/script
```
## 通信速度監視ツール
### 概要
- 設定した間隔で指定したIPアドレスに対してpingを送信して、通信速度を測定します。
- 測定した通信速度はテキストファイルに保存されます。
- リアルタイムで指定時間内の情報がプロットされます。

### 操作手順
1. 測定するための設定値を入力します。
   - internet_speed_monitor.py内の以下の値を設定してください。
     - INTERVAL：pingを送信する間隔[秒]。（デフォルト値：1.0）
     - ANALYZE_DATA_CNT：プロットするために集計するデータ数。設定した数のデータを収集してから、最大値・最小値・中央値をプロットします。（デフォルト値：10）
     - PLOT_PERIOD：リアルタイムでプロットする期間[分]。現在時刻からこの時間まで遡って、情報をプロットします。（デフォルト値：180.0）
     - TEXT_DIRECTORY_PATH：テキストファイルを格納するフォルダ。（デフォルト値："~/.log/internet_speed_monitor"）

2. 以下のコマンドによって起動します。
   ```
   python3 internet_speed_monitor.py ※IPアドレス※
   ```
   - IPアドレス：ping接続先のIPアドレス（ホスト名でも可）

## 選択した期間のプロット表示ツール
### 概要
- IPアドレスと期間を指定して、通信速度監視ツールでテキストに保存した情報を基に通信速度のプロットを作成します。

### 操作手順
1. プロットするための設定値を入力します。
   - plot_internet_speed.py内の以下の値を設定してください。
     - TEXT_DIRECTORY_PATH：テキストファイルが格納されているフォルダ。（デフォルト値："~/.log/internet_speed_monitor"）

2.  以下のコマンドによって起動します。
   ```
   python3 plot_internet_speed.py ※IPアドレス※ ※開始時間※ ※終了時間※
   ```
   - IPアドレス：プロットとして表示したいIPアドレス。（テキストファイルに保存されている形式）
   - 開始時間：プロットしたいデータの開始時間。形式：yyyy/mm/dd/hh:mm
   - 終了時間：プロットしたいデータの終了時間。形式：yyyy/mm/dd/hh:mm
