"""scenario_repository.py - シナリオとサブシナリオを DB から読む"""
import threading
from logging import getLogger
from typing import Any, List, Optional

from bson import ObjectId
from pymongo.collection import Collection

from .scenario_model import Scenario
from .schema_validator import ScenarioSchemaValidator


class ScenarioRepository:
    """scenarios / interruption_subscenarios コレクションを読み、読んだものをスキーマで検査する（合わなければ警告だけ）"""

    def __init__(self, scenario_collection, subscenario_collection):
        self._logger = getLogger(__name__)
        self.scenario_db = scenario_collection
        self.subscenario_db = subscenario_collection
        self._schema_validator: Optional[ScenarioSchemaValidator] = None
        # アクティブなサブシナリオの一覧（watch_subscenarios() で変更通知を受けている間だけ使う）
        self._active_subscenarios: Optional[List[Scenario]] = None
        self._subscenarios_changed = True
        self._watching_subscenarios = False

    def watch_subscenarios(self) -> None:
        """
        サブシナリオの変更通知を受け始める。受けている間は get_active_subscenarios() が読んだ一覧を使い回し、
        変更があったら次に読み直す（割り込みの判定は 0.5 秒ごとに一覧を使うため）

        変更通知が使えなければ（止まったときも）、これまでどおり毎回読み直す。
        """
        if self._watching_subscenarios or not isinstance(self.subscenario_db, Collection):
            return
        self._watching_subscenarios = True
        threading.Thread(target=self._watch_subscenario_changes, name="SubscenarioWatcher", daemon=True).start()

    def _watch_subscenario_changes(self) -> None:
        try:
            with self.subscenario_db.watch() as stream:
                self._subscenarios_changed = True  # 監視を始める前の変更も取り込む
                for _ in stream:
                    self._subscenarios_changed = True
        except Exception as e:
            self._logger.warning(f"Subscenario change stream stopped, reloading subscenarios every time: {e}")
        finally:
            self._watching_subscenarios = False
            self._subscenarios_changed = True

    @property
    def schema_validator(self) -> ScenarioSchemaValidator:
        """シナリオをスキーマで検査するもの（最初に使うときに作る）"""
        if self._schema_validator is None:
            self._schema_validator = ScenarioSchemaValidator()
        return self._schema_validator

    def load_scenario(self, scenario_id: Any, include_inactive: bool = False) -> Optional[Scenario]:
        """
        シナリオIDからシナリオをロード

        Args:
            scenario_id: シナリオID（文字列またはObjectId）
            include_inactive: Trueの場合はstatus: inactiveのシナリオもロードする
                （next_scenarios等で明示的に指定されたシナリオ用）

        Returns:
            シナリオ、見つからない場合はNone
        """
        try:
            if isinstance(scenario_id, str):
                scenario_id = ObjectId(scenario_id)

            query = {"_id": scenario_id}
            if not include_inactive:
                query["status"] = "active"
            scenario = self.scenario_db.find_one(query)

            if not scenario:
                self._logger.warning(f"Scenario not found or inactive: {scenario_id}")
                return None
            self._logger.info(f"Loaded scenario: {scenario.get('name')} (ID: {scenario_id})")
            self.schema_validator.check(scenario, "scenario")
            return Scenario.from_doc(scenario)
        except Exception as e:
            self._logger.error(f"Error loading scenario {scenario_id}: {e}")
            return None

    def find_subscenario(self, subscenario_id: Any) -> Optional[Scenario]:
        """IDでサブシナリオを読む（status は問わない）"""
        if isinstance(subscenario_id, str):
            subscenario_id = ObjectId(subscenario_id)
        doc = self.subscenario_db.find_one({"_id": subscenario_id})
        return Scenario.from_doc(doc) if doc else None

    def get_active_scenarios(self) -> List[Scenario]:
        """すべてのアクティブシナリオを取得"""
        try:
            docs = list(self.scenario_db.find({"status": "active"}))
            for doc in docs:
                self.schema_validator.check(doc, "scenario")
            self._logger.debug(f"Found {len(docs)} active scenarios")
            return [Scenario.from_doc(doc) for doc in docs]
        except Exception as e:
            self._logger.error(f"Error getting active scenarios: {e}")
            return []

    def get_active_subscenarios(self) -> List[Scenario]:
        """すべてのアクティブサブシナリオを取得（優先度の高い順）"""
        if self._watching_subscenarios and not self._subscenarios_changed and self._active_subscenarios is not None:
            return list(self._active_subscenarios)
        # 読んでいる間に変更があれば、また True になって次に読み直す
        self._subscenarios_changed = False
        subscenarios = self._load_active_subscenarios()
        if subscenarios is None:
            # 読めなかったときは使い回さず、次にまた読む
            self._subscenarios_changed = True
            return []
        self._active_subscenarios = subscenarios
        return list(subscenarios)

    def _load_active_subscenarios(self) -> Optional[List[Scenario]]:
        """アクティブなサブシナリオを DB から読み、スキーマで検査する（優先度の高い順）。読めなければ None"""
        try:
            docs = list(self.subscenario_db.find({"status": "active"}))
            for doc in docs:
                self.schema_validator.check(doc, "subscenario")

            subscenarios = sorted((Scenario.from_doc(doc) for doc in docs), key=lambda s: -s.priority)

            if not subscenarios:
                self._logger.info(
                    "[InterruptDetector] No active subscenarios found "
                    "(check status='active' in interruption_subscenarios collection)"
                )
            else:
                self._logger.debug(f"Found {len(subscenarios)} active subscenarios total")
            return subscenarios
        except Exception as e:
            self._logger.error(f"Error getting active subscenarios: {e}", exc_info=True)
            return None
