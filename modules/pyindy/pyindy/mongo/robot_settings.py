import os
from logging import getLogger

from pymongo import MongoClient

CONFIG_DB_HOST = os.getenv("RISM_CONFIG_HOST", "example.local")
CONFIG_DB_PORT = int(os.getenv("RISM_CONFIG_PORT", "9100"))

# robot_list から読む項目（ロボットごと）と、common から読む項目（全ロボット共通）
PER_ROBOT_KEYS = ("google_asr", "asr_target_angle", "ignore_non_looking", "recognition_available_regions")
COMMON_KEYS = ("city", "language", "openweathermap_token")

SERVER_SELECTION_TIMEOUT_MS = 3000


def load_robot_settings(robot_id=None, fallback_host=None, fallback_port=None):
    """
    ロボット側のプログラムの設定を、設定 DB（9100）の rism_configs.robot_list と common から読む

    返す辞書は、これまでの各ロボットの DB の rism_configs.rism_config と同じ形
    （google_asr、asr_target_angle、ignore_non_looking、recognition_available_regions、
      city、language、openweathermap_token、db_config.internal_state_db）。

    robot_id: robot_list の robot_id。省略すると環境変数 ROBOT_NAME
    fallback_host / fallback_port: 9100 に設定がないときに読む、今のロボットの DB（移し終えるまでの間）
    """
    logger = getLogger(__name__)
    robot_id = robot_id or os.getenv("ROBOT_NAME")
    settings = {}
    try:
        with MongoClient(CONFIG_DB_HOST, CONFIG_DB_PORT,
                         serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS) as client:
            db = client["rism_configs"]
            robot = db.robot_list.find_one({"robot_id": robot_id}) or {}
            common = db.common.find_one() or {}
    except Exception as e:
        logger.warning(f"cannot read the config DB {CONFIG_DB_HOST}:{CONFIG_DB_PORT}: {e}")
        robot, common = {}, {}

    if robot:
        settings.update({k: robot[k] for k in PER_ROBOT_KEYS if k in robot})
        settings.update({k: common[k] for k in COMMON_KEYS if k in common})
        if robot.get("internalstate_db"):
            settings["db_config"] = {"internal_state_db": {"col_name": "internal_state", **robot["internalstate_db"]}}
        return settings

    # 移し終えるまで: 今のロボットの DB の rism_config を読む
    logger.warning(f"robot '{robot_id}' not found in {CONFIG_DB_HOST}:{CONFIG_DB_PORT} rism_configs.robot_list, "
                   f"reading rism_configs.rism_config on {fallback_host}:{fallback_port}")
    if fallback_host is None:
        return settings
    try:
        with MongoClient(fallback_host, int(fallback_port) if fallback_port is not None else None,
                         serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS) as client:
            fallback = client["rism_configs"].rism_config.find_one() or {}
    except Exception as e:
        logger.warning(f"cannot read the fallback DB {fallback_host}:{fallback_port}: {e}")
        return settings
    if not fallback:
        logger.warning(f"rism_configs.rism_config not found on {fallback_host}:{fallback_port}, using empty settings")
    return fallback
