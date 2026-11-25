# IndyXe Viewer

This project integrates FastAPI with ROS2 to provide a web interface for interacting with a robot. It includes features such as camera streaming, button-based commands, and MongoDB integration for storing and managing data.

## Features

- **Camera Streaming**: Streams the latest frames from the robot's camera.
- **Battery Monitoring**: Displays the robot's current battery percentage (auto-updated).
- **Scenario**: Shows the running scenario, interruption and processing state (`current_state`) and recent scenario history (`scenario_history`).
- **Map**: Shows the map (`maps`: `map` + `keepout`), registered places (`locations`), the current navigation goal and the robot position (`/<robot_name>/rover/pose`).
- **Heard Speech**: Shows texts recognized by the robot (`/<robot_name>/recog/ssl/asr/analyzed`, requires `common_msgs` from the Indy workspace), with their morphemes colored by part of speech and readings as ruby (from ssl_asr `morph_node`; hover a morpheme for its reading, base form and part of speech).
- **Robot Actions**: Shows the latest robot actions in `<db_name>.Actions` (speak, navigation, gesture, eye, ros_command) per kind with their status, auto-updated.
- **Speech Playback**: Plays speech segments heard by the robot (`/<robot_name>/recog/ssl/identified_speech_segments`) in the browser as they arrive.
- **Heard Speech**: Shows recognized text and its morphemes (`/<robot_name>/recog/ssl/asr/analyzed`). Click an item to replay the audio it was recognized from (the latest 30 segments are kept in memory).
- **Robot Voice (ロボットの声)**: With the 「ロボットの発話を再生」 switch ON, the browser plays what the robot says. The robot's `rosTTS` only plays its synthesized voice from the robot's speaker and does not publish it, so this server synthesizes the same text again with the same voice settings (`persona.Voice`, key `voice_params`, on the blackboard host/port): `gtts` (with the same `params.rate` speed/pitch change), `hoya` (POST to `server`) or an MP3 `url`. The server watches `<db_name>.Actions` (`command: speak`), starts synthesizing while an utterance is `waiting`, and tells the browsers when it becomes `is_playing` (and when it is `stopped`). It synthesizes only while a browser has the switch ON. With `gtts`, the server needs internet access (Google). The switch state is remembered in the browser. Disable the feature with `--no-robot-voice`.
- **Talk to the Robot (ロボットに話しかける)**: While the 「押しながら話す」 button (or Space/Enter on it) is held, the browser records the microphone and publishes the voice as a separated speech segment (`ssl_msgs/SpeechSegment`, 16 kHz) to `/<robot_name>/recog/ssl/identified_speech_segments`, the output of `speaker_id_node` of `ssl_bringup`, so ASR and the speaker-face node handle it like real speech. (`speaker_id_node` runs on the robot, and the zenoh bridge does not carry `recog/ssl/speech_segments` from the server to the robot; with `--voice-input-topic speech_segments` the voice goes there instead, through `speaker_id_node`, once the robot's bridge routes it.) The speaker is placed 1 m in front of the robot (`azimuth` 0, `distance` 1.0 in `<robot_name>_base_link`), facing it; `person_id` is 0 and the level is normalized like `separator_node`. With the 「ロボットのスピーカーで再生」 switch ON, the voice is instead published to `/<robot_name>/robot/play_audio` (same message type) and played as is from the robot's speaker by the `rosAudioPlay` node on the robot (the request fails if that node is not found). The switch state is remembered in the browser. Requires `ssl_msgs` and HTTPS (see Usage).
- **Room Check (部屋を見に行く)**: Buttons that ask the robot to check a room. The destinations are read from MongoDB (`demo_configs.room_checker_destinations`, next to the scenario definitions; see below); the panel is hidden when there are none, and changes appear without reloading the page.
- **Speaker Face**: Shows the speaker's face next to each heard utterance; click it to enlarge.
- **MongoDB Integration**: Stores user inputs and commands in a MongoDB database.
- **ROS2 Node**: Subscribes to ROS2 topics for image and battery data.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- ROS 2 Humble (system Python 3.10)
- MongoDB (the robot DB used by RISM; see `setup/mongo_docker` of this repository)
- pyindy (`modules/pyindy` of this repository, installed by uv as an editable path dependency)
- Python dependencies are managed in `pyproject.toml` / `uv.lock`

## Installation

1. Move to this directory:
   ```bash
   cd $GUARDIAN_ROBOT_PATH/modules/indy_modules/indyxe_viewer
   ```

2. Install dependencies (creates `.venv` with the system Python 3.10):
   ```bash
   uv sync
   ```

3. Decide the robot-specific settings. They are given as command-line options of `main.py` (`uv run main.py --help` lists all of them),
   or in a JSON file passed with `--config`. Options given on the command line override the file.
   To make a config file for a new robot, copy `config.example.json` (every key with its default value; `null` means "not set") and edit it:
   ```bash
   cp config.example.json config_<robot>.json
   ```

   | Option | Config key | Description |
   |---|---|---|
   | `-r`, `--robot` | `robot_name` | robot name, used for ROS topic names (**required**) |
   | `--actor` | `actor` | actor of the robot's actions in `<db_name>.Actions` (`robot_id` in RISM's `robot_list`; default: `robot_name`) |
   | `-p`, `--web-port` | `web_port` | port of the web UI (**required**) |
   | `--web-host` | `web_host` | address the web UI listens on (default `0.0.0.0` = all interfaces) |
   | `--db-host` | `server_name` | MongoDB (RISM) host (default `localhost`) |
   | `--db-port` | `server_port` | MongoDB (RISM) port (**required**) |
   | `--db-name` | `db_name` | blackboard DB name (default `tBlackBoard`) |
   | `-d`, `--ros-domain-id` | `ros_domain_id` | ROS 2 domain ID (default: the `ROS_DOMAIN_ID` environment variable) |
   | `--battery-qos` | `battery_qos` | QoS of the battery topic, `system_default` (default) or `sensor_data` |
   | `--map-region=X_MIN,X_MAX,Y_MIN,Y_MAX` | `map_region` | area of the robot-position map to show, in map coordinates (m). Defaults to the drivable area plus registered places; small areas are enlarged so markers keep their size. Use `=` because the value may start with `-` |
   | `--scenario-db-host`, `--scenario-db-port` | `scenario_db` (`host`, `port`, `db_name`) | where RISM reads scenario definitions (same as `scenario_db` of the demo in `rism_configs.demo_list`). Defaults to the blackboard host/port and `demo_configs` |
   | `--destinations-collection` | `destinations_collection` | collection of room-check destinations in the scenario DB (`scenario_db`, i.e. `demo_configs`; default `room_checker_destinations`) |
   | `--voice-input-frame` | `voice_input_frame` | frame of the position of the voice sent from the browser (1 m ahead; default `<robot_name>_base_link`) |
   | `--voice-input-topic` | `voice_input_topic` | where the voice sent from the browser is published under `/<robot_name>/recog/ssl/`: `identified_speech_segments` (default, straight to ASR) or `speech_segments` (through `speaker_id_node`; needs the robot's zenoh bridge to route it) |
   | `--robot-voice` / `--no-robot-voice` | `robot_voice` | synthesize the robot's utterances on this server so the browser can play them (default on) |
   | `--ssl-certfile`, `--ssl-keyfile` | `ssl_certfile`, `ssl_keyfile` | serve the web UI over HTTPS with this certificate and key (needed to use the microphone from other PCs) |
   | `--template` | `template` | HTML template in `templates/` (default `index.html`) |
   | `--action-count` | `action_count` | number of robot actions shown per kind (default `5`) |
   | `--log-level` | `log_level` | `debug` / `info` / `warning` (default) / `error`; with `info` or `debug`, uvicorn access logs are also printed |

   Ensure MongoDB is running and accessible at `server_name:server_port`.

4. Register the destinations of 「部屋を見に行く」 (optional; without them the panel is hidden).
   They are kept in the scenario DB (`scenario_db`: `demo_configs` on the blackboard host/port by default), collection `room_checker_destinations`.
   Each document is
   `{"label": "Alice", "text": "Aliceの部屋を見てきて", "order": 1, "enabled": true}`
   (`text` defaults to `<label>の部屋を見てきて`; `order` and `enabled` are optional).
   Pressing a button stops the robot and puts `text` into `physical_topic` as ASR input, so RISM handles it like a spoken request.
   A list can be written as a JSON array of these documents (see `destinations.example.json`, which shows each optional key) and registered with `import`.
   Manage them with `destinations.py`:
   ```bash
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 import destinations.json   # register the list in the file (order = file order)
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 list
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 add 会議室 --text "会議室の様子を見てきて"
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 add 実験室 --disabled             # hide without deleting
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 remove Bob
   uv run destinations.py --db-host <MongoDB host> --db-port 9110 export > destinations.json
   ```

5. Set up ROS2 environment:
   ```bash
   source /opt/ros/humble/setup.bash
   ```

## Usage

1. Start the FastAPI server (after `source /opt/ros/humble/setup.bash`).
   For speech playback, also source the Indy workspace so that `ssl_msgs` can be imported
   (otherwise speech playback is disabled):
   ```bash
   source $GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash
   ```
   ```bash
   uv run main.py --config config_<robot>.json
   # or give everything on the command line (options override the config file)
   uv run main.py --robot $ROBOT_NAME --web-port 8001 --db-host $MONGO_URI --db-port $MONGO_PORT
   ```

2. Access the web interface at `https://<this PC's IP>:<web_port>` (e.g. `https://192.168.1.10:8003`) when the server is started with a certificate, or at `http://...` without one.
   The web UI is served over HTTPS so that 「ロボットに話しかける」 works: browsers allow the microphone only on HTTPS pages or on `localhost`.
   Over plain HTTP, every other feature works, but the push-to-talk button is disabled.

   Make a self-signed certificate once (`*.pem` is git-ignored):
   ```bash
   openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=indyxe_viewer" -keyout key.pem -out cert.pem
   ```
   Then give it on the command line or in the config file:
   ```bash
   uv run main.py --config config_<robot>.json --ssl-certfile cert.pem --ssl-keyfile key.pem
   ```
   ```json
   "ssl_certfile": "cert.pem",
   "ssl_keyfile": "key.pem"
   ```
   The certificate is self-signed, so each browser shows a warning on its first visit; accept it once (「詳細設定」→「<IP> にアクセスする（安全ではありません）」 in Chrome).
   Without HTTPS, the microphone can still be used by opening the page as `localhost`, e.g. through an SSH port forward (`ssh -L 8003:localhost:8003 <user>@<server>`, then `http://localhost:8003`).
   To hear what the robot says, turn on 「ロボットの発話を再生」 (same autoplay rule as below).
   To hear the speech the robot heard, turn on the 「音声再生」 switch. The ON/OFF state is remembered in the browser; when the page is reopened with ON, playback starts after the first click on the page (browsers block autoplay until the user interacts with the page).

## Launch with module_launch

On a machine set up with `~/indy.env`, the viewer can be started without options by
`$GUARDIAN_ROBOT_PATH/modules/module_launch/available/30_indyxe_viewer.sh` (or by linking it into `module_launch/enable`).
It runs `uv run main.py --robot $ROBOT_NAME --web-port $INDYXE_VIEWER_PORT --db-host $MONGO_URI --db-port $MONGO_PORT $INDYXE_VIEWER_OPTS`
in the tmux session `30_indyxe_viewer`, after sourcing `$GUARDIAN_ROBOT_PATH/ros2_ws/install/setup.bash`.
`INDYXE_VIEWER_PORT` defaults to `8000`; `INDYXE_VIEWER_OPTS` passes extra options (e.g. `--battery-qos sensor_data`).
The ROS domain is taken from `ROS_DOMAIN_ID`.

## File Structure

- `main.py`: Web app (FastAPI): pages, operations and JSON APIs. Entry point for every robot.
- `robot.py`: ROS 2 side: subscriptions (camera, battery, pose, heard speech, speech audio), `cmd_vel`, and fan-out of camera frames / speech audio to clients.
- `robot_voice.py`: Watches the robot's `speak` actions and synthesizes them with the robot's voice settings for playback in the browser.
- `blackboard.py`: Reads actions, scenario, scenario history/timeline, places and map from MongoDB (tBlackBoard), with short-lived caching shared by all viewers.
- `config.py`: Builds the settings from command-line options and an optional JSON file.
- `config.example.json`: Template of a config file listing every key (copy it to make a config for a new robot).
- `destinations.py`: Reads the 「部屋を見に行く」 destinations from MongoDB, and a CLI to manage them. `destinations.example.json` is a template of such a list.
- `pyproject.toml` / `uv.lock`: Python dependencies (uv).
- `templates/`: HTML templates (`base.html` layout, `_parts.html` panels, `index.html` page).
- `static/`: `app.css` (DADS-based styles), `app.js` (polling, map, timeline, speech playback, robot voice, push-to-talk) and `voice-worklet.js` (microphone capture). Polling pauses while the tab is hidden.

## HTTP API

| Path | Description |
|---|---|
| `GET /status` | Battery, robot pose and heard speech (from ROS) |
| `GET /blackboard` | Robot actions, navigation goal, running scenario, wait state and history (from MongoDB) |
| `GET /timeline?minutes=N` | Scenario transitions for the last N minutes, with interrupt nesting |
| `GET /scenario_definition/{scenario_id}?interruption=bool` | Summary of a scenario definition (priority, trigger condition, events) shown when hovering the timeline |
| `GET /map.json`, `GET /map.png` | Map image and coordinates, registered places |
| `GET /camera` | MJPEG camera stream |
| `GET /speech_face/{clip_id}` | Face image (JPEG) of the speaker of a heard-speech item |
| `GET /speech_clip/{clip_id}` | Audio (WAV) of a heard-speech item; `clip_id` is `<person_id>-<speech_start_ns>` |
| `WS /robot_voice` | Robot utterances as JSON: `{"type": "speak", "id", "text", "rate", "url"}` when the robot starts speaking, `{"type": "stop", "id"}` when stopped, `{"type": "error", ...}` when synthesis failed |
| `GET /robot_voice/{action_id}` | Synthesized audio (MP3 or WAV) of a robot utterance; play it at `rate` (pitch changes with speed, like the robot) |
| `WS /speech` | Speech segments (binary: uint32 sample rate, int32 person id, float32 samples) |
| `POST /voice_input?sample_rate=16000&speaker=false` | Publish a voice (body: float32 little-endian mono samples, 0.3–30 s) as a speech segment 1 m in front of the robot (to `voice_input_topic`), or with `speaker=true` to `robot/play_audio` to play it from the robot's speaker |
| `POST /control/{front,back,left,right,stop}` | Move the robot |
| `GET /destinations` | Destinations of 「部屋を見に行く」 (from MongoDB) |
| `POST /destinations/{id}/visit` | Ask the robot to check a room |
| `POST /submit` | Make the robot speak |

## Notes

- Ensure the ROS2 topics of the robot (`<robot>` is `robot_name`) are active:
  `/<robot>/local_recog/color/image_raw/compressed`, `/<robot>/rover/battery` and `/<robot>/rover/pose`
  (and `/<robot>/recog/ssl/...` for heard speech, speech audio and speaker faces).
- MongoDB and ROS2 settings are given as command-line options or a config file (see Installation step 3), not by editing `main.py`.
- The web UI has no authentication and can move the robot and make it speak. Use it only in a trusted network, or set `--web-host 127.0.0.1`.

## License

This project is licensed under the MIT License (see `LICENSE`).
The design tokens in `static/app.css` are taken from the Digital Agency Design System (MIT License); see `THIRD_PARTY_NOTICES.md`.

