# Sound Source Localization & Separation System

16chマイクロフォンアレイとYDLiDARを統合した音源定位・音源分離システム。
音源定位 → 人物追跡との対応付け → DASビームフォーミングによる音源分離 → VADによる発話区間検出 → 視覚人物IDとの統合 → 音声認識（Whisper）を行い、
人物ごとの発話テキストをROSメッセージとして出力する。

## データフロー

```
[YDLiDAR]                         [microphone_array]
    | LaserScan                        | AudioDataMultiChannel
    v                                  |  + MicrophoneArrayInfo (audio/array_info)
[tracker_node]                  [localizer_node]
    | recog/ssl/tracked_persons        | recog/ssl/doa_estimates
    |                                  |
    +---------------+    +-------------+
                    v    v
             [separator_node]  <-- AudioDataMultiChannel (raw 16ch)
                    |               + MicrophoneArrayInfo (audio/array_info)
                    v
              recog/ssl/speech_segments (SpeechSegment)
                    |
  recog/persons     |
  (※現状、発行元なし)
        |           |
        v           v
        [speaker_id_node]
              |
              v
        recog/ssl/identified_speech_segments (SpeechSegment)
              |
              v
        [asr_node]  (Whisper, server-side GPU)
              |
              v
        recog/ssl/asr/raw_text (StringStamped JSON)
```

## パッケージ構成

| パッケージ | ビルド種別 | 用途 |
|---|---|---|
| `ssl_msgs` | ament_cmake | メッセージ定義 |
| `lidar_person_tracker` | ament_python | LiDAR人物検出・追跡（背景差分付き） |
| `sound_source_localizer` | ament_python | SRP-PHATによる音源方向推定 |
| `audio_source_separator` | ament_python | DAS分離 + VAD + 発話セグメント出力 + 話者ID統合 + モニタ |
| `ssl_asr` | ament_python | Whisper音声認識（サーバ側GPU） |
| `ssl_bringup` | ament_cmake | Launch / Config / シミュレーション |

## トピック名規約

各ノードはトピック名に `in_`/`out_` プレフィックス付きの汎用名を使用する（例: `out_tracked_persons`, `in_doa_estimates`）。
Launchファイルの `remappings` で `recog/ssl/...` プレフィックス付きの実トピック名にマッピングする。

```python
# 例: ssl_system.launch.py でのリマッピング
remappings=[
    ('in_scan',             'scan'),
    ('out_tracked_persons', 'recog/ssl/tracked_persons'),
    ('in_doa_estimates',    'recog/ssl/doa_estimates'),
]
```

## メッセージ定義 (ssl_msgs)

| メッセージ | 用途 |
|---|---|
| `DOAEstimate` | 単一音源のDOA推定結果 (azimuth [rad], elevation [rad], power) |
| `DOAEstimateArray` | DOA推定結果の配列 |
| `TrackedPerson` | 追跡された人物 (ID, 位置, 速度, 方位角, 距離) |
| `TrackedPersonArray` | 追跡人物の配列 |
| `SpeechSegment` | 分離済み発話セグメント (人物ID, 音声データ, 時刻情報) |

## ノード詳細

### lidar_person_tracker / tracker_node

LaserScanから人物を検出・追跡する。背景差分により静的物体を除去し、人物のみを検出する。

- **Subscribe**: `in_scan` → `scan` (`sensor_msgs/LaserScan`, QoS: `qos_profile_sensor_data`)
- **Publish**:
  - `out_tracked_persons` → `recog/ssl/tracked_persons` (`ssl_msgs/TrackedPersonArray`)
  - `out_viz_markers` → `recog/ssl/viz/tracker_markers` (`visualization_msgs/MarkerArray`) — lazy publishing
  - `out_viz_clusters` → `recog/ssl/viz/tracker_clusters` (`sensor_msgs/PointCloud2`) — lazy publishing
- **アルゴリズム**:
  - **背景差分**: 起動後最初のN回スキャンで静的背景モデルを学習（中央値ベース）。学習完了後は背景と一致する点をinf化して除外。`BackgroundModel`クラス（`background_model.py`）で実装。
  - 距離ベースクラスタリング（360度スキャン時はラップアラウンド対応）
  - **人物サイズフィルタ**: 幅だけでなく奥行き（`max_cluster_depth`）も検証。胸の高さでは人物の胴体は弧状（幅広く奥行き浅い）であり、壁や家具は奥行きが大きいため区別可能。
  - カルマンフィルタ追跡（ハンガリアン法による最適対応付け、Joseph形式共分散更新）
  - ROS時刻を使用（rosbag再生・シミュレーション対応）
- **rviz可視化**: サブスクライバが存在する場合のみ publish する（lazy publishing）。人物位置のシリンダ、ID テキスト、速度矢印、検出範囲円、クラスタ色分けPointCloud2を表示。

主要パラメータ（`tracker_params.yaml`の値。`bg_enabled` はyamlに無くコード既定値。launchを使わず単体起動した場合の値は「パラメータファイルについての注意」を参照）:
- `cluster_distance_threshold` (0.15): クラスタリング距離閾値 (m)
- `min_cluster_size` (5) / `max_cluster_size` (50): クラスタ点数範囲
- `min_cluster_width` / `max_cluster_width` (0.20 / 0.55): 人物サイズ範囲 (m)
- `max_cluster_depth` (0.40): 最大クラスタ奥行き (m) — 壁・家具除外用
- `min_detection_range` / `max_detection_range` (0.3 / 2.0): 検出距離範囲 (m)
- `tracking_distance_threshold` (0.5): 追跡対応付け距離閾値 (m)
- `person_timeout` (2.0): 追跡ロスト判定時間 (秒)
- `process_noise` (0.5): カルマンフィルタプロセスノイズ
- `measurement_noise` (0.1): カルマンフィルタ観測ノイズ
- `bg_enabled` (true): 背景差分の有効/無効
- `bg_learning_scans` (50): 背景学習スキャン数
- `bg_threshold` (0.10): 前景判定距離閾値 (m)

### sound_source_localizer / localizer_node

マイクアレイ情報（`audio/array_info`）と16ch音声からSRP-PHATで音源方向を推定する。

- **Subscribe**:
  - `audio/array_info` (`microphone_array/MicrophoneArrayInfo`, QoS: transient_local) — マイク位置の取得
  - `audio/multichannel` (`microphone_array/AudioDataMultiChannel`, QoS: `qos_profile_sensor_data`)
- **Publish**:
  - `out_doa_estimates` → `recog/ssl/doa_estimates` (`ssl_msgs/DOAEstimateArray`)
  - `out_viz_doa_markers` → `recog/ssl/viz/doa_markers` (`visualization_msgs/MarkerArray`) — lazy publishing
- **アルゴリズム**: GCC-PHAT相互相関（全チャネルバッチFFT、逆FFTを`interp_factor`倍にオーバーサンプリングして小数遅延分解能を確保）→ SRP パワーマップ（numpy完全ベクトル化）→ ピーク検出（方位角は0/360度で循環する近傍抑圧）
- **パワー正規化**: `power` は正規化SRP（1.0 = 全マイクペアが完全にコヒーレント）。`power_threshold` 未満のピークは出力しない（無音時は空の `estimates` をpublish）
- **方位角正規化**: SRP-PHATの出力azimuth [0, 2pi] を [-pi, pi] に変換してトラッカーの座標系と一致させる
- **出力単位**: azimuth/elevation はラジアン

主要パラメータ（`localizer_params.yaml`の値。値がコード既定値と異なるものは併記）:
- `num_sources` (yaml: 5 / コード既定値: 3): 検出する最大音源数
- `search_resolution_deg` (5.0): 探索角度分解能 (度)
- `frequency_range` ([300, 3500]): 処理周波数帯域 (Hz)
- `power_threshold` (0.05): DOAピークとして出力する正規化SRPパワーの下限 (0〜1)
- `interp_factor` (4): GCC逆FFTのオーバーサンプリング倍率（1で無効）

### audio_source_separator / separator_node

DOA推定と人物追跡を統合し、DASビームフォーミングで音源分離、VADで発話区間を検出する。

- **Subscribe**:
  - `audio/array_info` (`microphone_array/MicrophoneArrayInfo`, QoS: transient_local) — マイク位置の取得
  - `audio/multichannel` (`microphone_array/AudioDataMultiChannel`, QoS: `qos_profile_sensor_data`)
  - `in_doa_estimates` → `recog/ssl/doa_estimates` (`ssl_msgs/DOAEstimateArray`)
  - `in_tracked_persons` → `recog/ssl/tracked_persons` (`ssl_msgs/TrackedPersonArray`)
- **Publish**: `out_speech_segments` → `recog/ssl/speech_segments` (`ssl_msgs/SpeechSegment`)。`header.frame_id` はマイクアレイ座標系（azimuth/distance はこの座標系での値）
- **アルゴリズム**:
  - **座標変換**: LiDAR人物位置（`TrackedPersonArray`、スキャン座標系）を tf2 でマイクアレイ座標系に変換してから DOA と比較する（`use_tf`）。変換先は `array_frame`、未指定時は DOA メッセージ／`audio/array_info` の `frame_id`。変換元は `persons_frame`、未指定時は `TrackedPersonArray` の `header.frame_id`。TFが取得できない場合は警告を出し、変換せずにLiDARの方位角をそのまま使う。
  - **鮮度チェック**: DOA/人物データの受信からのROSクロック経過時間で判定（`_doa_recv_time`, `_persons_recv_time`）。タイムスタンプ比較ではなく、`get_clock().now()`による最終受信からの経過時間を使用。`max_sync_age` を超えた場合は（再）対応付けを行わないが、音声ブロックは破棄せず、発話中の人物は直前の方向で処理を継続する（発話音声を途切れさせないため）。
  - ハンガリアン法による人物-DOA最適1対1対応付け
  - **DASビームフォーミング**: `apply_das_multi()` による周波数領域の小数遅延Delay-and-Sum。前ブロック末尾の履歴を付けて処理するためブロック境界が連続し、出力には一定の遅延（~0.1mのアレイで約1.2ms）が乗る。ブロックのFFTは1回で、方向ごとに1本のビームを作り複数人物で共有する。既に別の人物が使っている方向で発話を継続する人物には無音を入力する（同じ音声の二重出力防止）。MVDRは自己相殺問題があったため置き換え済み（`beamformer.py`にMVDRコードは残存）。
  - エネルギーベースVAD（ハングオーバー機構付き）→ セグメント化。発話開始前の `vad_preroll_frames` ブロックをセグメント先頭に付加する。`max_speech_duration` に達した場合はセグメントを分割して出力し、発話状態は継続する。
  - ROS時刻を使用（staleタイムアウト）

主要パラメータ（`separator_params.yaml`の値。値がコード既定値と異なるものは併記）:
- `fft_size` (512): FFTサイズ（MVDRビームフォーマ用、DASでは未使用）
- `speed_of_sound` (343.0): 音速 (m/s)
- `diagonal_loading` (yaml: 1e-1 / コード既定値: 1e-4): 共分散行列の対角ローディング（MVDR用）
- `forget_factor` (yaml: 0.3 / コード既定値: 0.9): EMA共分散更新の忘却係数（MVDR用）
- `max_sync_age` (yaml: 1.0 / コード既定値: 0.5): DOA/人物データの最大許容経過時間 (秒)
- `association_angle_threshold` (0.35): 人物-DOA対応付け角度閾値 (rad, 約20度)
- `vad_threshold_db` (yaml: -48.0 / コード既定値: -40.0): VADエネルギー閾値 (dB)
- `vad_hangover_frames` (10): VADハングオーバーフレーム数
- `vad_min_speech_frames` (3): VAD発話開始判定の最小連続フレーム数
- `vad_preroll_frames` (5): 発話開始前に保持してセグメント先頭に付加するブロック数
- `min_speech_duration` (0.3): 最小発話長 (秒)
- `max_speech_duration` (10.0): 最大発話長 (秒)
- `stale_association_timeout` (3.0): stale人物判定タイムアウト (秒)
- `array_frame` (''): DOA方位角の座標系。空の場合は DOA／`audio/array_info` の `frame_id`
- `persons_frame` (''): 人物位置の座標系。空の場合は `TrackedPersonArray` の `header.frame_id`
- `use_tf` (true): tf2 による人物位置の座標変換の有効/無効

### audio_source_separator / speaker_id_node

SpeechSegmentの方位角・距離を、`recog/persons`で受信したPersonの`body_location_sensor`座標と照合し、
視覚追跡由来の`person_id`（`instance_id`）で上書きする。マッチしない場合は元のperson_idを維持する。

> **注意**: 現状、本リポジトリ内に`recog/persons`を発行するノードは無い（scene_understandingの`association_node`の出力は`recog/person/pose/associated`）。そのため、そのままではperson_idの上書きは行われず、元のperson_idのまま`recog/ssl/identified_speech_segments`に出力される。

- **Subscribe**:
  - `in_persons` → `recog/persons` (`recognition_msgs/Persons`) — 現状、発行元なし（上記注意参照）
  - `in_speech_segments` → `recog/ssl/speech_segments` (`ssl_msgs/SpeechSegment`)
- **Publish**: `out_speech_segments` → `recog/ssl/identified_speech_segments` (`ssl_msgs/SpeechSegment`)
- **アルゴリズム**: SpeechSegmentの極座標(azimuth, distance; マイクアレイ座標系)と各Personの`body_location_sensor`（カメラ座標系）を、tf2 で共通座標系 `base_frame` に変換し、そのXY平面（床面）上のユークリッド距離で最近傍マッチング。座標系は各メッセージの `header.frame_id` を使い、空の場合は `speech_frame` / `persons_frame` を使う。Personsの座標系が決まらない場合やTFが取得できない場合は、照合せず元のperson_idのまま出力する。

主要パラメータ（`speaker_id_params.yaml`の値）:
- `match_distance_threshold` (1.0): 人物マッチング距離閾値 (m)
- `base_frame` (yamlでは未指定。コード既定値は `ROBOT_NAME` 設定時 `${ROBOT_NAME}_base_link`、未設定時 `base_link`): 照合に使う共通座標系
- `speech_frame` ('microphone_array_base'): SpeechSegment の `frame_id` が空の場合に使う座標系
- `persons_frame` (''): Persons の `frame_id` が空の場合に使う座標系

### ssl_asr / asr_node

Whisper（faster-whisper）による音声認識ノード。サーバ側GPUで実行する。

- **Subscribe**: `in_speech_segments` → `recog/ssl/identified_speech_segments` (`ssl_msgs/SpeechSegment`)
- **Publish**: `out_raw_text` → `recog/ssl/asr/raw_text` (`common_msgs/StringStamped`)
- **出力形式**: StringStamped.data にJSON文字列を格納（person_id, text, language, language_probability, duration, azimuth, distance, speech_start_ns, speech_end_ns）
- **リサンプリング**: SpeechSegmentのサンプルレートが16kHz以外の場合は `scipy.signal.resample_poly` で16kHzに変換する。変換できない場合（scipyが無い、不正なレート）はそのセグメントを破棄する。

主要パラメータ:
- `model_size` ('large-v3'): Whisperモデルサイズ
- `language` ('ja'): 認識言語
- `device` ('cuda'): 推論デバイス
- `compute_type` ('float16'): 推論精度
- `beam_size` (1): ビームサーチ幅
- `condition_on_previous_text` (false): 直前の認識結果を条件に使うか
- `without_timestamps` (true): タイムスタンプなしでデコードするか

### audio_source_separator / monitor_node

発話セグメントのモニタリングノード。レベルメータ表示、スピーカー再生、WAVファイル保存を行う。

- **Subscribe**: `in_speech_segments` (`ssl_msgs/SpeechSegment`)
- **機能**:
  - ターミナルにRMS/ピークレベルバーを表示
  - pyaudioによるスピーカー再生（オプション）
  - WAVファイル保存（オプション）

主要パラメータ:
- `play` (true): スピーカー再生の有効/無効
- `save_dir` (''): WAV保存先ディレクトリ（空の場合は保存しない）

### ssl_bringup / sim_speaker_node

シミュレーション用ノード。実際のLiDARスキャンと音声データを受信し、仮想の人物（LiDARクラスタ + 方向性音声）を注入して再パブリッシュする。

- **Subscribe**:
  - `audio/array_info` (`microphone_array/MicrophoneArrayInfo`, QoS: transient_local) — マイク位置の取得（ハードコードなし）
  - `in_scan` → `scan` (`sensor_msgs/LaserScan`, QoS: `qos_profile_sensor_data`)
  - `in_audio` → `audio/multichannel` (`microphone_array/AudioDataMultiChannel`, QoS: `qos_profile_sensor_data`)
- **Publish**:
  - `out_scan` → `scan_sim` (`sensor_msgs/LaserScan`)
  - `out_audio` → `audio/multichannel_sim` (`microphone_array/AudioDataMultiChannel`)
- **動作**:
  - ターミナルでEnterキーを押すと発話をトリガー（インタラクティブ）
  - **発話中**: 指定位置に人物クラスタ（ノイズ付き距離値）を注入し、方向性音声をミキシング
  - **無音時**: 人物位置の角度領域をinf化（背景学習が正しく行われるように）
  - gTTSによる日本語TTS（pydubでリサンプリング）、失敗時は合成音声（変調高調波）にフォールバック

主要パラメータ:
- `speaker_x` (1.0): 話者X位置 (前方, m)
- `speaker_y` (-0.5): 話者Y位置 (左正, m)
- `text` ('こんにちは'): TTS用発話テキスト
- `sample_rate` (16000): 音声サンプルレート (Hz)
- `speech_duration` (1.5): 合成フォールバック音声長 (秒)

## マイクアレイジオメトリ

マイク位置は `audio/array_info` トピック（`MicrophoneArrayInfo`メッセージ）から動的に取得する。
localizer_node, separator_node, sim_speaker_node いずれもこのトピックを購読し、ハードコードされた座標を持たない。

参考（2リング円形配列 16ch）:
- **上リング** (ch0-7): 半径0.05m, z=+0.02m, 0度開始, 45度間隔
- **下リング** (ch8-15): 半径0.05m, z=-0.02m, 22.5度開始, 45度間隔

座標変換ユーティリティは `sound_source_localizer/sound_source_localizer/array_geometry.py` で実装。

## ビルド

```bash
cd $GUARDIAN_ROBOT_PATH/ros2_ws
colcon build --packages-select ssl_msgs lidar_person_tracker sound_source_localizer audio_source_separator ssl_asr ssl_bringup
source install/setup.bash
```

ビルド順序: `ssl_msgs` → 他パッケージ (ssl_msgsに依存するため)

## 起動

### ロボット側（ssl_system.launch.py）

tracker_node, localizer_node, separator_node, speaker_id_node を起動する。

```bash
ros2 launch ssl_bringup ssl_system.launch.py
```

### シミュレーション付き起動

`sim:=true` 引数を指定すると、各ノードがシミュレーション用トピック（`scan_sim`, `audio/multichannel_sim`）を購読する。
別途 `ssl_sim.launch.py` で sim_speaker_node を起動し、実データに仮想人物を注入する。

```bash
# ターミナル1: シミュレーションモードでシステム起動
ros2 launch ssl_bringup ssl_system.launch.py sim:=true

# ターミナル2: シミュレータノード起動
ros2 launch ssl_bringup ssl_sim.launch.py speaker_x:=1.0 speaker_y:=-0.5 text:='こんにちは'
```

sim_speaker_node のターミナルでEnterキーを押すと発話がトリガーされる。

### サーバ側（ssl_server.launch.py）

GPU搭載サーバで asr_node を起動する。`CUDA_VISIBLE_DEVICES` 環境変数でGPUを指定可能（デフォルト: 3）。

```bash
CUDA_VISIBLE_DEVICES=0 ros2 launch ssl_bringup ssl_server.launch.py
```

環境変数 `ROBOT_NAME` を設定すると ROS ネームスペースに使用される（未設定時はグローバル名前空間）。

### パラメータファイルについての注意

`ssl_bringup/config/*.yaml` は、yamlの最上位キー（ノード名）がノードの完全修飾名と一致した場合のみ適用される（`/**/` は任意の名前空間に一致するワイルドカード）。現状は以下のとおり。

| yaml | 最上位キー | launchでのノード名 | 適用 |
|---|---|---|---|
| `tracker_params.yaml` | `/**/tracker_node` | `tracker_node` | 常に適用（名前空間を問わない） |
| `localizer_params.yaml` | `/**/localizer_node` | `localizer_node` | 常に適用（名前空間を問わない） |
| `separator_params.yaml` | `/**/separator_node` | `separator_node` | 常に適用（名前空間を問わない） |
| `speaker_id_params.yaml` | `/**/speaker_id_node` | `speaker_id_node` | 常に適用（名前空間を問わない） |
| `asr_params.yaml` | `asr_node` | `asr_node` | `ROBOT_NAME` 未設定時のみ（値はコード既定値と同じ） |

`asr_params.yaml` は最上位キーが `asr_node` のままのため、`ROBOT_NAME` を設定して名前空間付きで起動した場合（例: `/$ROBOT_NAME/asr_node`）は `/asr_node` として扱われて一致せず、コード上の既定値が使われる（値は同じなので動作は変わらない）。

launchを使わず `ros2 run` で単体起動した場合はコード既定値が使われる。tracker_nodeのコード既定値でyamlと異なるものは、`min_cluster_size` 3、`min_cluster_width` 0.1、`max_cluster_width` 0.6、`tracking_distance_threshold` 1.0、`bg_learning_scans` 30、`bg_threshold` 0.15。localizer_node / separator_node はそれぞれのパラメータ欄の「コード既定値」を参照。

なお `audio_source_separator/config/separator_params.yaml` は `ssl_bringup` のlaunchでは使われない（launchが読むのは `ssl_bringup/config/separator_params.yaml`）。

## 依存ライブラリ

- `numpy` - 配列演算・ベクトル化処理
- `scipy` - FFT (`scipy.fft`)、ハンガリアン法 (`scipy.optimize.linear_sum_assignment`)、16kHzへのリサンプリング (`scipy.signal.resample_poly`, ssl_asr)
- `tf2_ros` - 座標変換 (separator_node, speaker_id_node)
- `PyYAML` - 設定ファイル読み込み
- `faster-whisper` - Whisper音声認識 (ssl_asr)
- `pyaudio` - スピーカー再生 (monitor_node, オプション)
- `gTTS` + `pydub` - 日本語TTS (sim_speaker_node, オプション)

## 将来拡張

`audio_source_separator/separator_node.py` の `_create_subscribers()` メソッドに
顔向き情報等の追加サブスクライバを拡張可能な設計としている。
`scene_understanding` パッケージの顔向き推定結果を統合することで、発話者特定の精度向上が見込める。
