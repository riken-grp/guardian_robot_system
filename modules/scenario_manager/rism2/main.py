#!/usr/bin/env python3
"""
ロボットコマンドインタプリタ - メインエントリーポイント
"""
import logging
import signal
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

# src/rism2をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rism2.database import load_config
from rism2.interpreter import ScenarioInterpreter


class ShutdownRequested(BaseException):
    """SIGTERM / SIGINT で止めるよう頼まれた（except Exception で握りつぶされないよう BaseException にする）"""


# 止めるよう頼まれたシグナル名。後片付けの途中で別の例外に置き換わっても、起動し直さずに終わるために覚えておく
shutdown_signal = None


def _request_shutdown(signum, frame):
    global shutdown_signal
    shutdown_signal = signal.Signals(signum).name
    raise ShutdownRequested(shutdown_signal)


def install_signal_handlers() -> None:
    """
    SIGTERM と SIGINT で後片付けをしてから終わるようにする

    バックグラウンドで起動すると SIGINT が無視される設定で始まるため、明示的に受け取る。
    """
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)


def parse_arguments():
    """コマンドライン引数の解析"""
    LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    parser = ArgumentParser(description="Robot Command Interpreter (RISM2)")
    parser.add_argument(
        "--loglevel",
        choices=LOG_LEVELS,
        help="ログレベル",
        default="INFO"
    )
    parser.add_argument(
        "--robots",
        nargs="+",
        help="ロボットIDリスト",
        required=True
    )
    parser.add_argument(
        "--demo",
        help="デモID",
        required=True
    )
    parser.add_argument(
        "--host",
        help="設定DBホスト",
        default="localhost"
    )
    parser.add_argument(
        "--port",
        help="設定DBポート",
        default=9100,
        type=int
    )
    parser.add_argument(
        "--entry_point",
        help="開始シナリオID",
        default=None,
        type=str
    )
    return parser.parse_args()


def setup_logging(loglevel):
    """ロギング設定"""
    logging.basicConfig(
        level=getattr(logging, loglevel),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def run_interpreter(args):
    """インタプリタの実行"""
    max_restarts = 10
    restart_count = 0
    while True:
        interpreter = None
        try:
            # 設定DBから設定をロード
            logging.info("Loading configuration from database...")
            config = load_config(args.host, args.port)

            # ロボット情報をマッピング（ロボット名を追加）
            # NOTE: name_aliasはrobot_listの値をそのまま使用
            # NOTE: 各ロボットに独自のActionsコレクション名を設定
            config["robots"] = {}
            for i, robot in enumerate(args.robots):
                robot_config = config["robot_list"][robot].copy()
                robot_config["name"] = robot  # 実際のロボット名を追加（表示名）
                # name_aliasはrobot_listの値をそのまま使用（上書きしない）

                # 各ロボットに独自のActionsコレクション名を設定
                if "action_db" not in robot_config:
                    robot_config["action_db"] = {}
                if "col_name" not in robot_config["action_db"]:
                    # デフォルトは "Actions"、複数ロボットの場合は "Actions_robot1" など
                    if len(args.robots) == 1:
                        robot_config["action_db"]["col_name"] = "Actions"
                    else:
                        robot_config["action_db"]["col_name"] = f"Actions_robot{i+1}"

                config["robots"][f"robot{i+1}"] = robot_config

            # デモ設定を取得（demo_listにない場合はデフォルト設定を使用）
            if args.demo in config["demo_list"]:
                config["demo"] = config["demo_list"][args.demo]
                logging.info(f"Using demo configuration from demo_list: {args.demo}")
            else:
                # デフォルト設定（既存の動作と互換性を保つ）
                logging.info(f"Demo '{args.demo}' not found in demo_list, using default v2.0 configuration")
                config["demo"] = {
                    "demo_id": args.demo,
                    "version": "2.0",
                    "host": args.host,
                    "port": args.port,
                    "scenario_db": {
                        "host": args.host,
                        "port": args.port,
                        "db_name": args.demo
                    }
                }

            logging.info(f"Configuration loaded: {len(config['robots'])} robot(s), demo: {args.demo}")

            # タイムゾーン設定を適用（DBから読み込んだ設定を使用）
            if "timezone" in config:
                from rism2.time_utils import configure_timezone
                tz_config = config["timezone"]
                configure_timezone(
                    mode=tz_config.get("mode", "system"),
                    explicit=tz_config.get("explicit")
                )
                logging.info(f"Timezone configured: mode={tz_config.get('mode', 'system')}")

            # インタプリタを初期化
            interpreter = ScenarioInterpreter(config, args.entry_point)

            # エントリーポイントがある場合、またはアクティブシナリオが見つかった場合
            entry_scenario_id = args.entry_point
            if not entry_scenario_id:
                # エントリーポイントがない場合は条件に合致するシナリオを探す
                logging.info("No entry point specified, searching for matching scenario...")
                entry_scenario_id = interpreter.scenario_manager.selector.find_matching_scenario()
                if entry_scenario_id:
                    logging.info(f"Found matching scenario: {entry_scenario_id}")
                else:
                    logging.info("No matching scenario found, starting in idle mode")
                    # entry_scenario_idをNoneのままにして待機モードで開始
            
            if entry_scenario_id:
                # シナリオIDが見つかった場合、シナリオチェーンを実行
                logging.info(f"Starting scenario chain from: {entry_scenario_id}")
                interpreter.run_scenario_chain(entry_scenario_id)
            else:
                # 待機モードで開始（Noneを渡してrun_scenario_chainを呼び出す）
                logging.info("Starting in idle mode, waiting for interruption...")
                interpreter.run_scenario_chain(None)

            # 正常終了
            logging.info("Interpreter completed successfully")
            break

        except (KeyboardInterrupt, ShutdownRequested) as e:
            logging.info(f"Shutdown requested ({type(e).__name__} {e}). Exiting gracefully.")
            break
        except Exception as e:
            logging.error("An error occurred: %s", e, exc_info=True)
            if shutdown_signal is not None:
                # 止める途中で起きた例外（ShutdownRequested が別の例外に置き換わった）。起動し直さない
                logging.info(f"Shutdown requested ({shutdown_signal}). Exiting instead of restarting.")
                break
            restart_count += 1
            if restart_count >= max_restarts:
                logging.error(f"Reached maximum restart limit ({max_restarts}). Exiting.")
                break
            logging.info(f"Restarting interpreter after error... (attempt {restart_count}/{max_restarts})")
            time.sleep(5)
        finally:
            if interpreter is not None:
                try:
                    interpreter.cleanup()
                    logging.info("Interpreter resources cleaned up successfully.")
                except Exception as cleanup_error:
                    logging.error("Error during cleanup: %s", cleanup_error)


def main():
    args = parse_arguments()
    setup_logging(args.loglevel)

    logging.info("="*60)
    logging.info("RISM2 - Robot Interactive Scenario Manager")
    logging.info("="*60)

    install_signal_handlers()
    run_interpreter(args)

    logging.info("="*60)
    logging.info("RISM2 terminated")
    logging.info("="*60)


if __name__ == "__main__":
    main()
