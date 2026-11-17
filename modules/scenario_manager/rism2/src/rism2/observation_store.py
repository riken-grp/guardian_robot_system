"""observation_store.py - 観測（physical_topic / cyber_topic）を読み、使った印を付ける"""
from datetime import datetime
from logging import getLogger
from typing import Any, Dict, List, Optional

from .observation_watcher import ObservationWatcher


class ObservationStore:
    """
    観測の読み出しと mentioned（使った印）の管理

    読み出しは ObservationWatcher のメモリキャッシュから行い、失敗したときだけ DB を直接読む。
    """

    def __init__(self, physical_collection, cyber_collection, latest_n: int = 100,
                 watcher: Optional[ObservationWatcher] = None):
        self._logger = getLogger(__name__)
        self.physical_topic_db = physical_collection
        self.cyber_topic_db = cyber_collection
        self.latest_n = latest_n
        self.watcher = watcher

    def mark_pending_as_mentioned(self) -> None:
        """
        起動前に蓄積した未処理観測（mentioned=False）を処理済みにする

        停止中にたまった観測（full_batteryなど）で起動直後に割り込みが走るのを防ぐ。
        データは削除せず mentioned=True に更新するだけ。
        """
        now = datetime.now()
        for name, collection in (("physical_topic", self.physical_topic_db),
                                 ("cyber_topic", self.cyber_topic_db)):
            try:
                result = collection.update_many(
                    {"mentioned": {"$ne": True}},
                    {"$set": {"mentioned": True, "last_mentioned": now}}
                )
                self._logger.info(
                    f"[CLEANUP] Marked {result.modified_count} pending observation(s) "
                    f"as mentioned in {name}"
                )
            except Exception as e:
                self._logger.error(f"[CLEANUP] Failed to clean up {name}: {e}")

    def get_recent_observations(self, limit: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        最新の観測データを取得（mentioned: falseのみ）

        Args:
            limit: 取得する観測データの件数（デフォルト: config の latest_N）

        Returns:
            観測データの辞書 {"tBlackBoard": [観測データリスト]}
        """
        if limit is None:
            limit = self.latest_n
        try:
            return self.watcher.get_recent_observations(limit)
        except Exception as e:
            self._logger.error(f"Error getting recent observations from cache: {e}", exc_info=True)
            self._logger.warning("Falling back to direct database access")
            return self._get_observations_from_db(limit)

    def _get_observations_from_db(self, limit: int) -> Dict[str, List[Dict[str, Any]]]:
        """DBから直接観測データを取得（フォールバック用）"""
        try:
            query = {"mentioned": {"$ne": True}}
            physical = list(self.physical_topic_db.find(query, sort=[("inserted", -1)], limit=limit))
            cyber = list(self.cyber_topic_db.find(query, sort=[("inserted", -1)], limit=limit))
            self._logger.debug(f"Retrieved from DB: {len(physical)} physical + {len(cyber)} cyber observations")
            return {"tBlackBoard": physical + cyber}
        except Exception as e:
            self._logger.error(f"Error getting observations from DB: {e}")
            return {"tBlackBoard": []}

    def claim_observations(self, observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        まだ使われていない（mentioned が true でない）観測だけを mentioned=true にして返す

        wait_for と割り込み検知が同じ観測を同時に受け取っても、
        先に書き換えた側だけがその観測を使えるようにする。
        _id の無い観測は重複を判定できないため、そのまま返す。
        """
        claimed = []
        for obs in observations or []:
            if not obs:
                continue
            if "_id" not in obs:
                claimed.append(obs)
                continue
            query = {"_id": obs["_id"], "mentioned": {"$ne": True}}
            update = {"$set": {"mentioned": True, "last_mentioned": datetime.now()}}
            try:
                result = self.physical_topic_db.update_one(query, update)
                if result.modified_count == 0:
                    result = self.cyber_topic_db.update_one(query, update)
                if result.modified_count > 0:
                    claimed.append(obs)
            except Exception as e:
                self._logger.error(f"Failed to claim observation {obs.get('_id')}: {e}")

        # 使えなかった観測（ほかの処理が先に使った、ロボット側が消した）もキャッシュでは使用済みにする。
        # 残しておくと、条件の照合が同じ古い観測を選び続け、あとから来た観測で発動しなくなる
        with_id = [o for o in observations or [] if o and "_id" in o]
        if with_id:
            self._update_cache(with_id)
        return claimed

    def update_mentioned_observations(self, matched_observations: List[Dict[str, Any]]) -> None:
        """マッチした観測データの mentioned を true にする（DB とメモリキャッシュの両方）"""
        if not matched_observations:
            return

        for obs in matched_observations:
            if not (obs and "_id" in obs):
                continue
            try:
                update = {"$set": {"mentioned": True, "last_mentioned": datetime.now()}}
                if self.physical_topic_db.update_one({"_id": obs["_id"]}, update).matched_count:
                    self._logger.debug(f"Updated mentioned=True in DB for physical_topic observation: {obs['_id']}")
                elif self.cyber_topic_db.update_one({"_id": obs["_id"]}, update).matched_count:
                    self._logger.debug(f"Updated mentioned=True in DB for cyber_topic observation: {obs['_id']}")
                else:
                    self._logger.warning(f"Observation not found in physical_topic or cyber_topic: {obs['_id']}")
            except Exception as e:
                self._logger.error(f"Failed to update mentioned in DB for observation {obs.get('_id')}: {e}")

        self._update_cache(matched_observations)

    def _update_cache(self, observations: List[Dict[str, Any]]) -> None:
        try:
            self.watcher.update_mentioned_in_cache(observations)
        except Exception as e:
            self._logger.error(f"Failed to update mentioned in cache: {e}", exc_info=True)
