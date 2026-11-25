"""起動設定: コマンドライン引数と (任意の) JSON 設定ファイルから作る

優先順位は コマンドライン引数 > 設定ファイル (--config) > 既定値.
"""
import argparse
import json
from pathlib import Path

REQUIRED_KEYS = ("web_host", "web_port", "robot_name", "server_name", "server_port", "db_name")

DEFAULTS = {
    "web_host": "0.0.0.0",
    "server_name": "localhost",  # RISM の MongoDB (ロボットDB)
    "db_name": "tBlackBoard",
    "template": "index.html",
    "battery_qos": "system_default",
}


def _map_region(text):
    """x_min,x_max,y_min,y_max (m) を map_region の辞書にする"""
    try:
        x_min, x_max, y_min, y_max = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("x_min,x_max,y_min,y_max の形式で指定してください (例: -1,8.2,-3.3,4.8)")
    if x_min >= x_max or y_min >= y_max:
        raise argparse.ArgumentTypeError("x_min < x_max, y_min < y_max になるよう指定してください")
    return {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max}


def build_parser():
    parser = argparse.ArgumentParser(
        description="ロボットの状態を表示し, 操作を受け付ける Web ページを起動する",
        epilog="例: uv run main.py --robot <ロボット名> --web-port 8001 --db-host <MongoDBのホスト> --db-port 9110",
    )
    # dest は設定ファイルのキーと同じにする (引数で指定したものだけが設定ファイルの値を上書きする)
    parser.add_argument("-c", "--config", help="JSON 設定ファイル (指定した引数はこれより優先される)")
    parser.add_argument("-r", "--robot", dest="robot_name", metavar="NAME", help="ロボット名 (ROS のトピック名に使う)")
    parser.add_argument("--actor", dest="actor", metavar="NAME",
                        help="黒板 (Actions) の actor. RISM の robot_list の robot_id (既定: --robot と同じ)")
    parser.add_argument("-p", "--web-port", dest="web_port", metavar="PORT", type=int, help="Web ページのポート番号 (例: 8003)")
    parser.add_argument("--web-host", dest="web_host", metavar="HOST", help=f"Web ページを公開するアドレス (既定: {DEFAULTS['web_host']})")
    parser.add_argument("--db-host", dest="server_name", metavar="HOST", help=f"MongoDB (RISM) のホスト (既定: {DEFAULTS['server_name']})")
    parser.add_argument("--db-port", dest="server_port", metavar="PORT", type=int, help="MongoDB (RISM) のポート番号 (例: 9130)")
    parser.add_argument("--db-name", dest="db_name", metavar="NAME", help=f"黒板の DB 名 (既定: {DEFAULTS['db_name']})")
    parser.add_argument("-d", "--ros-domain-id", dest="ros_domain_id", metavar="ID", type=int,
                        help="ROS 2 のドメイン ID (既定: 環境変数 ROS_DOMAIN_ID)")
    parser.add_argument("--battery-qos", dest="battery_qos", choices=("system_default", "sensor_data"),
                        help=f"バッテリーのトピックの QoS (既定: {DEFAULTS['battery_qos']})")
    parser.add_argument("--map-region", dest="map_region", type=_map_region, metavar="X_MIN,X_MAX,Y_MIN,Y_MAX",
                        help="地図で表示する範囲 (地図座標, m). 負の値から始まるときは --map-region=-1,8.2,-3.3,4.8 のように = でつなぐ."
                             " 既定は走行可能な範囲と登録された場所が入る範囲")
    parser.add_argument("--scenario-db-host", dest="scenario_db_host", metavar="HOST", help="シナリオ定義の DB のホスト (既定: --db-host)")
    parser.add_argument("--scenario-db-port", dest="scenario_db_port", metavar="PORT", type=int,
                        help="シナリオ定義の DB のポート番号 (既定: --db-port)")
    parser.add_argument("--destinations-collection", dest="destinations_collection", metavar="NAME",
                        help="「部屋を見に行く」の行き先のコレクション (シナリオ定義の DB (demo_configs) 内. 既定: room_checker_destinations)")
    parser.add_argument("--voice-input-frame", dest="voice_input_frame", metavar="FRAME",
                        help="ブラウザから話しかけた音声の位置 (前方 1 m) の座標系 (既定: <ロボット名>_base_link)")
    parser.add_argument("--voice-input-topic", dest="voice_input_topic",
                        choices=("identified_speech_segments", "speech_segments"),
                        help="ブラウザから話しかけた音声の送り先 (recog/ssl/ 以下). 既定の identified_speech_segments は"
                             " 話者 ID 付与後で ASR に直接届く. speech_segments は speaker_id_node を通るが,"
                             " ロボット側の zenoh bridge がサーバからの購読を通している必要がある")
    parser.add_argument("--robot-voice", dest="robot_voice", action=argparse.BooleanOptionalAction, default=None,
                        help="ロボットの発話をこのサーバで音声合成し, ブラウザで再生できるようにする (既定: 有効)."
                             " 声はロボットと同じ設定 (persona.Voice). gtts なら Google へ, hoya ならその合成サーバへ接続する")
    parser.add_argument("--ssl-certfile", dest="ssl_certfile", metavar="FILE",
                        help="HTTPS の証明書 (ブラウザのマイクを localhost 以外から使うのに必要)")
    parser.add_argument("--ssl-keyfile", dest="ssl_keyfile", metavar="FILE", help="HTTPS の秘密鍵")
    parser.add_argument("--template", dest="template", metavar="FILE", help=f"templates/ 内の HTML テンプレート (既定: {DEFAULTS['template']})")
    parser.add_argument("--action-count", dest="action_count", metavar="N", type=int, help="種類ごとに表示するロボットの行動の数")
    parser.add_argument("--log-level", dest="log_level", choices=("debug", "info", "warning", "error"),
                        help="ログの出力レベル (既定: warning)")
    return parser


def _read_json(path_text):
    path = Path(path_text)
    if not path.is_absolute() and not path.exists():
        path = Path(__file__).resolve().parent / path
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config(argv=None) -> dict:
    """コマンドライン引数 (と --config の設定ファイル) から設定を作る"""
    parser = build_parser()
    args = vars(parser.parse_args(argv))

    config = dict(DEFAULTS)
    config_path = args.pop("config")
    if config_path:
        config.update(_read_json(config_path))

    scenario_db = dict(config.get("scenario_db", {}))
    for key, arg in (("host", "scenario_db_host"), ("port", "scenario_db_port")):
        if args.get(arg) is not None:
            scenario_db[key] = args[arg]
        args.pop(arg)
    if scenario_db:
        config["scenario_db"] = scenario_db

    config.update({k: v for k, v in args.items() if v is not None})

    missing = [k for k in REQUIRED_KEYS if config.get(k) is None]
    if missing:
        options = {"robot_name": "--robot", "web_port": "--web-port", "server_port": "--db-port"}
        parser.error("次の設定が必要です: " + ", ".join(options.get(k, k) for k in missing))
    if bool(config.get("ssl_certfile")) != bool(config.get("ssl_keyfile")):
        parser.error("--ssl-certfile と --ssl-keyfile は両方指定してください")
    return config
