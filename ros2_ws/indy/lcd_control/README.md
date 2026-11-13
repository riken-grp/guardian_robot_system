# lcd_control（眼球モニタ制御）
ROS2から円形液晶WAVESHARE-19192 (GC9A01) を制御するノード

## セットアップ
FT232H経由でSPI通信を行うため、FTDIの D2XX ドライバと LibMPSSE ライブラリを使用する。
**x86_64環境では `library/LibMPSSE/` に必要なライブラリを同梱しているため、別途インストールは不要。**

1. udev ruleを配置します (sudo cp ./99-ftdi_ft232h_mpsse.rules /etc/udev/rules.d)
1. udevのリロード、または再起動を行います。 (sudo udevadm control --reload)
1. FT232Hを接続します、既に接続されている場合には再接続を行います。
1. ノードをビルドします。 (colcon build --cmake-clean-cache)

以上でノードとして実行可能な状態となります。

使用するFT232Hは事前に「FT_Prog」を使用してMPSSEモードに変更してください。

## 同梱ライブラリについて
`library/LibMPSSE/` には以下を同梱している。CMakeLists.txt はこのディレクトリ内の
`libftd2xx.so` と `libmpsse.so` を直接リンクする。

|パス|内容|
|---|---|
|`libftd2xx/ftd2xx.h`, `WinTypes.h`|D2XX APIのヘッダ|
|`libftd2xx/libftd2xx.so`, `.a`|D2XXドライバ本体（**バイナリのみ。FTDIはソースを公開していない**）|
|`build_lib/libmpsse.so`, `.a`|LibMPSSEのビルド済みライブラリ|
|`build_lib/libmpsse_spi.h`, `libmpsse_i2c.h`|LibMPSSE APIのヘッダ|
|`source/`|LibMPSSEのソースコード（FTDIが公開）|
|`Makefile`, `defs.mak`, `targets.mak`|LibMPSSEをソースからビルドする場合に使用|
|`ReadMe.txt`, `release-notes.txt`|FTDI公式のドキュメント|

> 同梱している `.so` / `.a` は **x86_64向け**。ARM等の他アーキテクチャで動作させる場合は、
> FTDIの配布物から対応するバイナリを取得して差し替えること（入手先は末尾の「library」を参照）。

## 仕様
  - 画像について  
    240x240の画像のみに対応しています。  

  - config  
    lcd_control.yamlから下記を設定します。  
    - image_lcd1: LCD1番で、ノード起動直後に表示する画像のファイル名を指定。
    - image_lcd2: LCD2番で、ノード起動直後に表示する画像のファイル名を指定。
    - pub_period_sec: /$ROBOT_NAME/eye_display/(lcd1の値)/displayed_file及び/$ROBOT_NAME/eye_display/(lcd2の値)/displayed_fileトピックの配信周期を秒単位で指定。
    - lcd1(2)：lcd1(2)が左右どちらのディスプレイか指定します（`left`/`right`）。この値がトピック名に使われます。

  ノード`eye_control_node`は`/$ROBOT_NAME`名前空間で起動するため、以下のトピックの実際の名前は`/$ROBOT_NAME/eye_display/...`となる。

  - subscriber
    - eye_display/right(left)/target_file : 「std_msgs::msg::String」型で入力したファイルの画像を右(左)眼に表示します。
  
  - publisher
    - eye_display/right(left)/displayed_file : 右(左)眼で表示している画像ファイル名を配信します。

## 実行方法
```
ros2 launch lcd_control eye_control.launch.py
```

## library
> [LibMPSSE](https://ftdichip.com/software-examples/mpsse-projects/libmpsse-spi-examples/)  
> FT232H SPI library  
> Copyright (c) Future Technology Devices International Limited  
> FTDI独自ライセンス（下記参照）

> [D2XX](https://ftdichip.com/drivers/d2xx-drivers/)  
> FT232H Driver  
> Copyright (c) 2001-2021 Future Technology Devices International Limited  
> FTDI独自ライセンス（下記参照）

> [stb](https://github.com/nothings/stb)  
> Image library  
> Public Domain / MIT License

### FTDIライセンスについて
LibMPSSE および D2XX は OSI承認のオープンソースライセンスではなく、FTDI独自のライセンス条件が適用される。
条文は `library/LibMPSSE/libftd2xx/ftd2xx.h` の冒頭に記載されており、要点は以下の2点。

- `FTDI DRIVERS MAY BE USED ONLY IN CONJUNCTION WITH PRODUCTS BASED ON FTDI PARTS.`
  → FTDI製チップを使用する製品との組み合わせでのみ使用できる。本ノードはFT232H（FTDI製）を
    使用するため、この条件を満たす。
- `FTDI DRIVERS MAY BE DISTRIBUTED IN ANY FORM AS LONG AS LICENSE INFORMATION IS NOT MODIFIED.`
  → ライセンス表記を改変しない限り、形式を問わず再配布できる。同梱しているバイナリ・ヘッダは
    いずれもFTDI配布物のままで、ライセンス表記に改変を加えていない。

同梱ファイルのライセンスヘッダは**変更しないこと**。
