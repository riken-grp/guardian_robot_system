# audio_play

Plays audio received on a topic through the robot speaker as is: no TTS, no normalization, no effects.
indyxe_viewer uses it for its "ロボットのスピーカーで再生" mode.

## Node: `rosAudioPlay` (node name `audio_play`, namespace `$ROBOT_NAME`)

| Direction | Topic | Type | Notes |
|---|---|---|---|
| Subscribe | `robot/play_audio` (e.g. `/indy3e/robot/play_audio`) | `ssl_msgs/SpeechSegment` | Only `sample_rate` and `audio_data` (float32 mono, -1..1) are used |

The node publishes nothing.

- The node converts float32 to int16 (clipping out-of-range values) and plays the result with `simpleaudio.play_buffer(pcm, 1, 2, sample_rate)`.
- It plays audio in arrival order, one clip at a time, so clips never overlap.
  Clips waiting to play are queued; when the queue is full, the oldest are dropped.
- It discards invalid audio with a warning: empty, `sample_rate <= 0`, NaN/Inf, or longer than `max_duration`.
- Volume follows the PulseAudio sink, so `robot/set_volume` (rosVolume) applies.
- There is no coordination with TTS, so the two can play at the same time.
- The robot microphones pick up the played audio, so ssl_bringup may recognize it as speech.

### Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `max_duration` | double | 30.0 | Longer audio is not played (warning) |
| `max_queue` | int | 3 | Maximum number of clips waiting to play |
| `output_sample_rate` | int | 0 | Resample (linear) to this rate before playing. 0 = play at the received rate. Use 44100/48000 only if the device cannot play 16 kHz |

## Launch

```bash
ros2 launch audio_play audio_play_launch.py          # needs ROBOT_NAME
settings/module_launch/available/20_grs_action_audio_play.sh   # tmux session
```

Run it in the user session that owns PulseAudio/PipeWire (`XDG_RUNTIME_DIR`); launching from tmux satisfies this.
It requires `ssl_msgs` (`colcon build --packages-select ssl_msgs audio_play`) and `simpleaudio`/`numpy`.

## Test

```bash
python3 -m pytest mdr/audio_play/test
```

To play a test sound on the robot: two 1 s 440 Hz tones should play back to back without overlapping.

```bash
python3 - <<'EOF'
import time, numpy as np, rclpy
from ssl_msgs.msg import SpeechSegment
rclpy.init(); n = rclpy.create_node('play_test')
pub = n.create_publisher(SpeechSegment, '/<robot>/robot/play_audio', 10)
t = np.arange(16000) / 16000
m = SpeechSegment(); m.sample_rate = 16000; m.duration = 1.0
m.audio_data = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).tolist()
time.sleep(1); pub.publish(m); pub.publish(m); time.sleep(1)
EOF
```

When the viewer runs on the server (connected through zenoh-bridge-ros2dds), the robot-side bridge config must let `.*/robot/play_audio` through if it has an allow/deny list.
