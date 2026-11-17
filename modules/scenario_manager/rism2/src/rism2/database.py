"""設定データベースからの設定読み込みと、MongoDB への接続"""
from functools import lru_cache
from typing import Any, Dict
import pymongo
from pymongo import MongoClient


@lru_cache(maxsize=None)
def shared_client(host: str, port: int) -> MongoClient:
    """
    同じサーバーには同じ MongoClient を使い回す

    MongoClient はスレッドセーフで、中に接続プールを持つ。サーバーごとに1つあればよい。
    """
    return MongoClient(f"mongodb://{host}:{port}/")


def use_shared_client(manager: Any, host: str, port: int, dbname: str, collection: str) -> Any:
    """
    pyindy のマネージャー（ActionManager / DialogueHistoryManager など）を、共有の MongoClient に切り替える

    pyindy のマネージャーは作るたびに自分の MongoClient（監視スレッドと接続プール）を持つ。
    ロボット1台で6つ作るので、自分のものを閉じて shared_client に替える。
    """
    client = shared_client(host, port)
    own = getattr(manager, "client", None)
    if isinstance(own, pymongo.MongoClient) and own is not client:
        own.close()
    manager.client = client
    manager.db = client[dbname]
    manager.col = manager.db[collection]
    return manager


def load_config(host: str, port: int) -> Dict[str, Any]:
    """
    設定データベースから設定をロード

    Args:
        host: 設定DBのホスト（デフォルト: localhost）
        port: 設定DBのポート（デフォルト: 9100）

    Returns:
        設定辞書（rism_config, robot_list, demo_list を含む）
    """
    client = MongoClient(host, port)
    db = client["rism_configs"]

    # システム設定
    config = db.rism_config.find_one()
    if not config:
        raise ValueError("rism_config not found in database")

    # ロボット一覧
    config["robot_list"] = {}
    for robot in db.robot_list.find():
        config["robot_list"][robot["robot_id"]] = robot

    # デモ一覧
    config["demo_list"] = {}
    for demo in db.demo_list.find():
        config["demo_list"][demo["demo_id"]] = demo

    client.close()
    return config


def get_scenario_db_info(demo_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    デモ設定に基づいてシナリオDBの情報を取得

    Args:
        demo_config: デモ設定辞書

    Returns:
        Dict[str, Any]: {
            "host": str,
            "port": int,
            "db_name": str
        }
    """
    scenario_db = demo_config.get("scenario_db", {})

    # DB名の優先順位: demo_config.db_name > scenario_db.db_name > デフォルト
    db_name = demo_config.get("db_name") or scenario_db.get("db_name", demo_config.get("demo_id", "demo_configs"))
    return {
        "host": scenario_db.get("host", demo_config.get("host", "localhost")),
        "port": scenario_db.get("port", demo_config.get("port", 9310)),
        "db_name": db_name,
    }
