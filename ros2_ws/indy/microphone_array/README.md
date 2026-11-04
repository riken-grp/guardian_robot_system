# microphone_array

16チャンネルマイクロフォンアレイからALSAで音声データをキャプチャし、ROS 2トピックとしてpublishするパッケージ。
チャンネルごとの音声レベルモニタリング、スピーカー再生、WAVファイル録音のノードも含む。

## ノード

### microphone_array_node

ALSAデバイスから16ch音声をキャプチャし、`audio/multichannel` トピックにpublishする。
起動時にマイクアレイのジオメトリ情報を `audio/array_info` トピックに transient_local でpublishする。

#### パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `device` | string | `"default"` | ALSAデバイス名 (例: `"hw:0,0"`) |
| `sample_rate` | int | `16000` | サンプルレート (Hz) |
| `channels` | int | `16` | チャンネル数 |
| `frames_per_block` | int | `512` | 1ブロックあたりのフレーム数 |
| `array_geometry_file` | string | `""` | マイク配置YAMLファイルのパス。未指定時は `audio/array_info` をpublishしない |
| `array_frame_id` | string | `"microphone_array_base"` | `audio/array_info` の `header.frame_id`。通常は `{robot_name}_microphone_array_base` を指定 |

#### Publishトピック

| トピック | 型 | QoS | 説明 |
|---|---|---|---|
| `audio/multichannel` | `microphone_array/AudioDataMultiChannel` | SensorData | 音声データ（毎ブロック） |
| `audio/array_info` | `microphone_array/MicrophoneArrayInfo` | TransientLocal (depth=1) | マイク配置情報（起動時1回） |

### channel_monitor_node

`audio/multichannel` トピックをsubscribeし、指定チャンネルまたは全チャンネルのミックス音声のRMS/ピークレベルをdBFSでターミナルに表示する。

```
Ch  3: [████████████                            ] -28.5 dBFS (peak: -12.3 dBFS)
Mix  : [████████████                            ] -28.5 dBFS (peak: -12.3 dBFS)
```

#### パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | int | `-1` | モニタリングするチャンネル番号 (0-indexed)。`-1` で全チャンネルミックス |
| `display_interval_ms` | int | `500` | 表示更新間隔 (ms) |

#### Subscribeトピック

| トピック | 型 | QoS |
|---|---|---|
| `audio/multichannel` | `microphone_array/AudioDataMultiChannel` | SensorData |

### audio_playback_node

`audio/multichannel` トピックをsubscribeし、指定チャンネルまたは全チャンネルのミックス音声をALSAスピーカーから再生する。出力はモノラル。

#### パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | int | `-1` | 再生するチャンネル番号 (0-indexed)。`-1` で全チャンネルミックス |
| `device` | string | `"default"` | ALSA再生デバイス名 (例: `"plughw:1,0"`) |

#### Subscribeトピック

| トピック | 型 | QoS |
|---|---|---|
| `audio/multichannel` | `microphone_array/AudioDataMultiChannel` | SensorData |

### audio_recorder_node

`audio/multichannel` トピックをsubscribeし、指定チャンネルまたは全チャンネルのミックス音声をモノラルWAVファイル（16-bit PCM）として保存する。ノード終了時にWAVヘッダを書き戻す。

#### パラメータ

| パラメータ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | int | `-1` | 録音するチャンネル番号 (0-indexed)。`-1` で全チャンネルミックス |
| `output_file` | string | `"output.wav"` | 出力WAVファイルのパス |

#### Subscribeトピック

| トピック | 型 | QoS |
|---|---|---|
| `audio/multichannel` | `microphone_array/AudioDataMultiChannel` | SensorData |

## メッセージ

### AudioDataMultiChannel.msg

```
builtin_interfaces/Time stamp       # 先頭サンプルのタイムスタンプ
uint32 sample_rate                  # サンプルレート (Hz)
uint16 channels                     # チャンネル数
uint16 frames_per_block             # ブロック内フレーム数
int16[] data                        # インターリーブPCMデータ (S16_LE)
```

データレイアウト (インターリーブ):
```
[frame0_ch0, frame0_ch1, ..., frame0_chN, frame1_ch0, frame1_ch1, ..., frame1_chN, ...]
```

### MicrophoneArrayInfo.msg

```
std_msgs/Header header              # タイムスタンプ・frame_id ("{robot_name}_microphone_array_base")
uint32 num_channels                 # チャンネル数
float64 sample_rate                 # サンプルレート (Hz)
float64[] positions                 # マイク座標 [x0,y0,z0, x1,y1,z1, ...] (チャンネル順、単位: m)
```

座標系はROSデフォルト (x-forward, y-left, z-up)。
`sound_source_localization` パッケージはこのトピックを購読してマイク配置を取得する。

## ビルド

```bash
colcon build --packages-select microphone_array
source install/setup.bash
```

### 依存パッケージ (システム)

```bash
sudo apt install libasound2-dev libyaml-cpp-dev
```

## 使い方

```bash
# launchファイルで起動（マイク配置情報もpublish）
ros2 launch microphone_array microphone_array.launch.py device:="hw:0,0"

# 単体で起動
ros2 run microphone_array microphone_array_node --ros-args \
  -p device:="hw:0,0" -p channels:=16 \
  -p array_geometry_file:="/path/to/array_geometry.yaml"

# 全チャンネルミックスをモニタリング（デフォルト）
ros2 run microphone_array channel_monitor_node

# チャンネル3をモニタリング
ros2 run microphone_array channel_monitor_node --ros-args -p channel:=3

# 全チャンネルミックスをスピーカーで再生
ros2 run microphone_array audio_playback_node

# チャンネル2のみ再生
ros2 run microphone_array audio_playback_node --ros-args -p channel:=2

# 再生デバイスを指定
ros2 run microphone_array audio_playback_node --ros-args -p channel:=0 -p device:=plughw:1,0

# WAVファイルに録音（全チャンネルミックス）
ros2 run microphone_array audio_recorder_node --ros-args -p output_file:=recording.wav

# チャンネル0のみ録音
ros2 run microphone_array audio_recorder_node --ros-args -p channel:=0 -p output_file:=ch0.wav
```
