"""scenario_manager.py - シナリオまわりの部品を組み立てる"""
from logging import getLogger
from typing import Any, Dict

from .database import get_scenario_db_info, shared_client
from .observation_store import ObservationStore
from .observation_watcher import ObservationWatcher
from .robot_directory import RobotDirectory
from .scenario_history import ScenarioHistory
from .scenario_repository import ScenarioRepository
from .scenario_selector import ScenarioSelector


class ScenarioManager:
    """
    シナリオDBと観測DB（tBlackBoard）につなぎ、次の部品を持つ

    scenarios:    ScenarioRepository（シナリオ／サブシナリオの読み込みとスキーマ検査）
    observations: ObservationStore（観測の読み出しと mentioned の管理）
    history:      ScenarioHistory（シナリオの実行履歴と会話履歴）
    robots:       RobotDirectory（actor とロボットの対応、ロボットの状態）
    selector:     ScenarioSelector（次のシナリオと割り込むサブシナリオの選択）
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 設定辞書（demo情報を含む）
        """
        self._logger = getLogger(__name__)
        self.config = config

        scenario_db_info = get_scenario_db_info(config["demo"])
        host, port, db_name = scenario_db_info["host"], scenario_db_info["port"], scenario_db_info["db_name"]
        self._logger.info(f"Connecting to scenario DB: {host}:{port}/{db_name}")
        scenario_database = shared_client(host, port)[db_name]
        self.scenarios = ScenarioRepository(scenario_database.scenarios, scenario_database.interruption_subscenarios)
        self.scenarios.watch_subscenarios()

        # physical_topic / cyber_topic: robot_list の topic サブ設定を優先
        phys_host, phys_port = self._get_topic_db_host_port(config, "physical_topic")
        cyber_host, cyber_port = self._get_topic_db_host_port(config, "cyber_topic")
        self._logger.info(f"[DB] physical_topic connection: {phys_host}:{phys_port}")
        self._logger.info(f"[DB] cyber_topic connection: {cyber_host}:{cyber_port}")
        blackboard = shared_client(phys_host, phys_port)["tBlackBoard"]
        cyber_blackboard = shared_client(cyber_host, cyber_port)["tBlackBoard"]
        self.observations = ObservationStore(
            blackboard.physical_topic, cyber_blackboard.cyber_topic, latest_n=config.get("latest_N", 100))

        # 履歴は physical_topic と同じサーバーに置く
        self.robots = RobotDirectory(config)
        self.history = ScenarioHistory(
            blackboard.scenario_history, finished_queue_length=config.get("finished_queue_length", 100))

        # 起動前に蓄積した未処理観測を処理済みにする（ObservationWatcher の初期ロード前に行う）
        # rism_config の cleanup_topics_on_start で無効化できる（デフォルト: True）
        if config.get("cleanup_topics_on_start", True):
            self.observations.mark_pending_as_mentioned()
        else:
            self._logger.info("Topic cleanup on start is disabled (cleanup_topics_on_start=False)")

        self.observations.watcher = self._start_observation_watcher(
            config, (phys_host, phys_port), (cyber_host, cyber_port))

        self.selector = ScenarioSelector(self.scenarios, self.observations)

    def close(self) -> None:
        """観測の監視を止め、まだ始まっていないアクションを取り消す"""
        self.robots.cancel_waiting_actions()
        if self.observations.watcher is not None:
            self.observations.watcher.stop()

    def _get_topic_db_host_port(self, config: Dict[str, Any], topic_key: str):
        """
        robot_list の topic サブ設定から接続先ホスト/ポートを取得

        Args:
            config: 設定辞書
            topic_key: "physical_topic" または "cyber_topic"

        優先順位:
        1. config["robots"][first_robot][topic_key]["host/port"]
        2. config["demo"]["host/port"]
        """
        robots = config.get("robots", {})
        if robots:
            first_robot = next(iter(robots.values()))
            topic_config = first_robot.get(topic_key, {})
            host = topic_config.get("host")
            port = topic_config.get("port")
            if host and port:
                robot_name = first_robot.get("name", first_robot.get("robot_id", "?"))
                self._logger.info(
                    f"[DB] Using robot config for {topic_key}: robot={robot_name}, {host}:{port}"
                )
                return host, int(port)
        # フォールバック: demo設定
        self._logger.warning(
            f"[DB] No {topic_key} host/port in robot config, "
            f"falling back to config['demo']"
        )
        return config["demo"]["host"], config["demo"]["port"]

    def _start_observation_watcher(self, config: Dict[str, Any], physical, cyber) -> ObservationWatcher:
        """ObservationWatcherを作り、Change Streams監視を開始"""
        max_cache_size = config.get("observation_cache_size", 10000)
        use_change_streams = config.get("use_change_streams", True)
        separate_cyber = cyber != physical
        try:
            watcher = ObservationWatcher(
                host=physical[0],
                port=physical[1],
                max_cache_size=max_cache_size,
                use_change_streams=use_change_streams,
                cyber_host=cyber[0] if separate_cyber else None,
                cyber_port=cyber[1] if separate_cyber else None,
            )
            watcher.start_watching()
            self._logger.info(
                f"ObservationWatcher initialized "
                f"(cache_size: {max_cache_size}, "
                f"change_streams: {use_change_streams})"
            )
            return watcher
        except Exception as e:
            self._logger.error(f"Failed to initialize ObservationWatcher: {e}", exc_info=True)
            raise
