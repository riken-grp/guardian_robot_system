"""observation_watcher.py - 観測データのメモリキャッシュ＋Change Streams監視"""
import threading
import time
from typing import Dict, List, Any, Optional, Protocol
from logging import getLogger
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from readerwriterlock import rwlock

from rism2.constants import RECEIVED_AT_KEY
from rism2.indexed_observation_cache import IndexedObservationCache
from rism2.observation_validator import ObservationValidator


class ObservationCallback(Protocol):
    """
    観測データ到着時のコールバックインターフェース

    このProtocolを実装するクラスは、on_observationメソッドを持つ必要がある。
    コールバックは同期的に呼び出される。

    使用例:
        class MyHandler:
            def on_observation(self, observation: Dict[str, Any]) -> None:
                print(f"New observation: {observation['event']}")

        watcher = ObservationWatcher(...)
        watcher.register_callback(MyHandler())
    """

    def on_observation(self, observation: Dict[str, Any]) -> None:
        """
        新しい観測データ到着時に呼ばれる

        Args:
            observation: 観測データ辞書（event, _id, contents等を含む）
        """
        ...


class ObservationWatcher:
    """
    MongoDB Change Streamsで観測データをリアルタイム監視し、
    メモリキャッシュに保存するプロキシクラス

    このクラスはMongoDBへの直接的なポーリングアクセスを削減し、
    メモリキャッシュから高速にデータを取得できるようにします。
    """

    # ポーリング間隔のデフォルト値と範囲制限（ミリ秒）
    DEFAULT_POLL_INTERVAL_MS = 500
    MIN_POLL_INTERVAL_MS = 100
    MAX_POLL_INTERVAL_MS = 2000

    def __init__(
        self,
        host: str,
        port: int,
        max_cache_size: int = 10000,
        use_change_streams: bool = True,
        poll_interval_ms: int = None,
        cyber_host: str = None,
        cyber_port: int = None
    ):
        """
        Args:
            host: MongoDBホスト
            port: MongoDBポート
            max_cache_size: メモリキャッシュの最大サイズ（デフォルト: 10000）
            use_change_streams: Change Streamsを使用するか（デフォルト: True）
            poll_interval_ms: ポーリング間隔（ミリ秒、デフォルト: 500、範囲: 100-2000）
        """
        self._logger = getLogger(__name__)
        self.max_cache_size = max_cache_size
        self.use_change_streams = use_change_streams

        self.poll_interval = self._poll_interval_seconds(poll_interval_ms)

        # MongoDB接続情報を保存（ログ用）
        self.db_host = host
        self.db_port = port

        physical_client = self._connect(host, port, "physical_topic")
        self.physical_topic_db = physical_client["tBlackBoard"]["physical_topic"]
        # cyber_topic が別のサーバーなら別のクライアントを使う
        cyber_host, cyber_port = cyber_host or host, cyber_port or port
        if (cyber_host, cyber_port) != (host, port):
            cyber_client = self._connect(cyber_host, cyber_port, "cyber_topic")
        else:
            cyber_client = physical_client
            self._logger.info(f"cyber_topic uses same MongoDB as physical_topic ({host}:{port})")
        self.cyber_topic_db = cyber_client["tBlackBoard"]["cyber_topic"]

        # メモリキャッシュ（IndexedObservationCacheで高速検索）
        self.physical_cache = IndexedObservationCache(max_size=max_cache_size)
        self.cyber_cache = IndexedObservationCache(max_size=max_cache_size)

        # ReadWriteLockでスレッドセーフを確保（読み込み並列化）
        # RWLockFairD: 公平なロック（スターベーション防止）
        self._rwlock = rwlock.RWLockFairD()
        self._read_lock = self._rwlock.gen_rlock()
        self._write_lock = self._rwlock.gen_wlock()

        # Change Streams監視スレッド
        self.watch_threads = []
        self.running = False
        self._polling_fallback_started = False  # ポーリングフォールバック済みフラグ

        # 統計情報
        self.stats = {
            "physical_inserts": 0,
            "cyber_inserts": 0,
            "cache_hits": 0,
            "last_update": None,
            "callback_invocations": 0,
            "callback_errors": 0
        }

        # 届いた観測の形の検査（合わなければ警告だけ）
        self._observation_validator = ObservationValidator()

        # コールバック管理
        self._callbacks: List[ObservationCallback] = []
        self._callback_lock = threading.Lock()

        # 初期データをロード
        self._load_initial_data()

    def _poll_interval_seconds(self, poll_interval_ms: Optional[int]) -> float:
        """ポーリング間隔（秒）。ミリ秒で受け取り、MIN〜MAX に収める"""
        if poll_interval_ms is None:
            poll_interval_ms = self.DEFAULT_POLL_INTERVAL_MS
        if poll_interval_ms < self.MIN_POLL_INTERVAL_MS:
            self._logger.warning(f"poll_interval_ms={poll_interval_ms} is below minimum "
                                 f"({self.MIN_POLL_INTERVAL_MS}ms), using minimum value")
            poll_interval_ms = self.MIN_POLL_INTERVAL_MS
        elif poll_interval_ms > self.MAX_POLL_INTERVAL_MS:
            self._logger.warning(f"poll_interval_ms={poll_interval_ms} exceeds maximum "
                                 f"({self.MAX_POLL_INTERVAL_MS}ms), using maximum value")
            poll_interval_ms = self.MAX_POLL_INTERVAL_MS
        self._logger.info(f"Poll interval set to {poll_interval_ms}ms ({poll_interval_ms / 1000.0}s)")
        return poll_interval_ms / 1000.0

    def _connect(self, host: str, port: int, label: str) -> MongoClient:
        """MongoDB に接続して ping する（つながらなければ例外）"""
        try:
            client = MongoClient(f"mongodb://{host}:{port}/", serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
        except Exception as e:
            self._logger.error(f"Failed to connect to {label} MongoDB: {e}")
            raise
        self._logger.info(f"Connected to {label} MongoDB at {host}:{port}")
        return client

    def _fetch_unmentioned(self, collection) -> List[Dict[str, Any]]:
        """まだ使われていない（mentioned が true でない）観測を新しい順に最大 max_cache_size 件"""
        return list(collection.find({"mentioned": {"$ne": True}}, sort=[("inserted", -1)], limit=self.max_cache_size))

    def _add_to_cache(self, cache: IndexedObservationCache, doc: Dict[str, Any], cache_name: str = "") -> bool:
        """キャッシュに1件足す（書き込みロックの中で呼ぶ）。event のない観測は飛ばして False"""
        try:
            cache.add(doc)
            return True
        except KeyError:
            where = f" in {cache_name}" if cache_name else ""
            self._logger.warning(f"Skipping observation without 'event' field{where}: _id={doc.get('_id')}")
            return False

    def _start_polling(self, thread_name: str) -> None:
        """ポーリングのスレッドを起動する（Change Streams が使えないときや、止まったときの代わり）"""
        thread = threading.Thread(target=self._polling_mode, name=thread_name, daemon=True)
        thread.start()
        self.watch_threads.append(thread)

    def _load_initial_data(self) -> None:
        """起動時に既存の観測データをメモリにロード"""
        try:
            physical_data = self._fetch_unmentioned(self.physical_topic_db)
            cyber_data = self._fetch_unmentioned(self.cyber_topic_db)
            with self._write_lock:
                # 古い順に追加する
                for obs in reversed(physical_data):
                    self._add_to_cache(self.physical_cache, obs)
                for obs in reversed(cyber_data):
                    self._add_to_cache(self.cyber_cache, obs)

            self._logger.info(
                f"Loaded initial data: {len(physical_data)} physical + "
                f"{len(cyber_data)} cyber observations "
                f"(cache size: {self.max_cache_size})"
            )

        except Exception as e:
            self._logger.error(f"Failed to load initial data: {e}", exc_info=True)
            raise

    def start_watching(self) -> None:
        """Change Streamsまたはポーリングでの監視を開始"""
        if not self.use_change_streams:
            self._logger.info("Change Streams disabled, starting polling mode")
            self.running = True
            self._start_polling("ObservationPolling")
            return

        self.running = True

        # physical_topic監視スレッド
        physical_thread = threading.Thread(
            target=self._watch_collection,
            args=(self.physical_topic_db, self.physical_cache, "physical"),
            name="PhysicalTopicWatcher",
            daemon=True
        )

        # cyber_topic監視スレッド
        cyber_thread = threading.Thread(
            target=self._watch_collection,
            args=(self.cyber_topic_db, self.cyber_cache, "cyber"),
            name="CyberTopicWatcher",
            daemon=True
        )

        physical_thread.start()
        cyber_thread.start()

        self.watch_threads = [physical_thread, cyber_thread]
        self._logger.info("ObservationWatcher started with Change Streams")

    # Change Streams のエラーで再接続する回数
    MAX_WATCH_RETRIES = 5

    # 受け取る変更: 新しい観測、消された観測、使用済みになった観測
    WATCH_PIPELINE = [{"$match": {"$or": [
        {"operationType": "insert"},
        {"operationType": "delete"},
        {"operationType": "update", "updateDescription.updatedFields.mentioned": True},
    ]}}]

    def _watch_collection(
        self,
        collection,
        cache: IndexedObservationCache,
        cache_name: str
    ) -> None:
        """
        Change Streamsでコレクションを監視する。使えなくなったらポーリングに切り替える

        届いた観測（insert）はキャッシュに足す。消された観測（ロボット側は見失った人の観測を消す）と、
        ほかが使用済みにした観測（mentioned: true への update）は、キャッシュでも使用済みにする。
        残しておくと、条件の照合がもう使えない古い観測を選び続ける。

        Args:
            collection: 監視するMongoDBコレクション
            cache: キャッシュ
            cache_name: キャッシュ名（physical / cyber）
        """
        retry_count = 0
        while self.running:
            try:
                with collection.watch(self.WATCH_PIPELINE) as stream:
                    self._logger.info(f"Started watching {cache_name}_topic")
                    retry_count = 0  # つながったらリトライの回数を戻す
                    for change in stream:
                        if not self.running:
                            break
                        self._on_change(change, cache, cache_name)
            except PyMongoError as e:
                retry_count += 1
                if not self._wait_to_rewatch(e, cache_name, retry_count):
                    break
            except Exception as e:
                self._logger.error(f"Unexpected error in {cache_name} watcher: {e}", exc_info=True)
                time.sleep(5)
        self._on_watcher_exit(cache_name)

    def _wait_to_rewatch(self, error: PyMongoError, cache_name: str, retry_count: int) -> bool:
        """
        Change Streams のエラーのあと、少し待ってからつなぎ直すか

        replica set でない（コード 40573）ときと、MAX_WATCH_RETRIES 回続けて失敗したときは False。
        それ以外は 5 秒から倍々（最大 60 秒）で待って True。
        """
        if getattr(error, 'code', None) == 40573:
            self._logger.warning(
                f"Change Streams not available for {cache_name} (requires replica set configuration). "
                f"Thread exiting - will use polling mode if available."
            )
            return False
        self._logger.error(f"Change Stream error for {cache_name} (retry {retry_count}/{self.MAX_WATCH_RETRIES}): {error}")
        if retry_count >= self.MAX_WATCH_RETRIES:
            self._logger.error(f"Max retries reached for {cache_name} watcher, thread exiting")
            return False
        wait_time = min(5 * (2 ** (retry_count - 1)), 60)
        self._logger.info(f"Waiting {wait_time}s before retry...")
        time.sleep(wait_time)
        return True

    def _on_watcher_exit(self, cache_name: str) -> None:
        """
        監視スレッドが終わるとき: まだ動いているなら、すぐにポーリングに切り替える

        （_check_and_recover_threads() のように、全スレッドが止まるのを待たない）
        """
        self._logger.warning(f"[ObservationWatcher] {cache_name}_topic watcher thread exiting")
        if self.running and not self._polling_fallback_started:
            self._polling_fallback_started = True
            self._logger.warning(
                f"[ObservationWatcher] Starting polling fallback immediately "
                f"(triggered by {cache_name}_topic thread exit)"
            )
            self._start_polling("ObservationPollingFallback")

    def _on_change(self, change: Dict[str, Any], cache: IndexedObservationCache, cache_name: str) -> None:
        """Change Streams の変更1件"""
        if change.get("operationType") == "insert":
            new_doc = change.get("fullDocument")
            if new_doc is not None:
                self._on_inserted(new_doc, cache, cache_name)
            return
        obs_id = (change.get("documentKey") or {}).get("_id")
        if obs_id is not None:
            with self._write_lock:
                if cache.update_mentioned([obs_id]):
                    self._logger.debug(
                        f"[ObservationWatcher] {change.get('operationType')} in {cache_name}: _id={obs_id} is no longer usable")

    def _on_inserted(self, doc: Dict[str, Any], cache: IndexedObservationCache, cache_name: str) -> None:
        """Change Streams で届いた観測1件: キャッシュに足し、統計を更新し、コールバックに知らせる"""
        with self._write_lock:
            if not self._add_to_cache(cache, doc, cache_name):
                return
            self.stats[f"{cache_name}_inserts"] += 1
            self.stats["last_update"] = time.time()
        self._logger.info(
            f"[ObservationWatcher] New observation in {cache_name}: "
            f"_id={doc.get('_id')}, event={doc.get('event')}, mentioned={doc.get('mentioned', False)}"
        )
        self._observation_validator.check(doc)
        # コールバックは書き込みロックの外で呼ぶ
        self._notify_callbacks(doc, "change_streams")

    def _check_and_recover_threads(self) -> None:
        """
        監視スレッドの状態をチェックし、必要に応じてポーリングに切り替え
        """
        if not self.running or self._polling_fallback_started:
            return

        # Change Streamsモードの場合のみチェック
        if not self.use_change_streams:
            return

        # 全スレッドが終了しているかチェック
        all_dead = all(not t.is_alive() for t in self.watch_threads) if self.watch_threads else True

        if all_dead:
            self._logger.warning(
                "[ObservationWatcher] All Change Streams threads have died. "
                "Switching to polling mode as fallback."
            )
            self._polling_fallback_started = True
            self._start_polling("ObservationPollingFallback")
            self._logger.info("[ObservationWatcher] Polling fallback thread started")

    def get_recent_observations(
        self,
        limit: Optional[int] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        メモリキャッシュから最新の観測データを取得（mentioned: falseのみ）

        Args:
            limit: 取得する最大件数（Noneの場合は全て）

        Returns:
            観測データの辞書 {"tBlackBoard": [観測データリスト]}
        """
        # スレッド状態をチェックし、必要に応じてポーリングに切り替え
        self._check_and_recover_threads()

        # 読み込みロックを使用（並列読み込み可能）
        with self._read_lock:
            # mentioned: falseのデータのみフィルタ（IndexedObservationCacheのAPIを使用）
            physical_data = self.physical_cache.get_all_unmentioned()
            cyber_data = self.cyber_cache.get_all_unmentioned()

            # limitが指定されている場合は最新N件のみ
            if limit:
                physical_data = physical_data[-limit:]
                cyber_data = cyber_data[-limit:]

            # データを結合
            combined_data = physical_data + cyber_data

            # 統計情報を更新
            self.stats["cache_hits"] += 1

            self._logger.debug(
                f"Retrieved from cache: {len(physical_data)} physical + "
                f"{len(cyber_data)} cyber (total: {len(combined_data)}, "
                f"limit: {limit})"
            )

            return {"tBlackBoard": combined_data}

    def _polling_mode(self) -> None:
        """
        ポーリングモードで定期的に新しい観測データを取得
        （Change Streamsが使えない場合のフォールバック）
        """
        self._logger.info(f"Polling mode started (interval: {self.poll_interval}s)")

        # 前回のIDを追跡（新規データ検出用）
        previous_physical_ids: set = set()
        previous_cyber_ids: set = set()

        while self.running:
            try:
                new_physical = self._fetch_unmentioned(self.physical_topic_db)
                new_cyber = self._fetch_unmentioned(self.cyber_topic_db)
                current_physical_ids = {obs.get("_id") for obs in new_physical if obs.get("_id")}
                current_cyber_ids = {obs.get("_id") for obs in new_cyber if obs.get("_id")}

                # キャッシュを今の未使用の観測で置き換える（mentioned の更新も反映される）
                with self._write_lock:
                    for cache, docs in ((self.physical_cache, new_physical), (self.cyber_cache, new_cyber)):
                        # 前の回から残っている観測は、最初に受け取った時刻を引き継ぐ
                        received = {o.get("_id"): o[RECEIVED_AT_KEY] for o in cache.get_all_unmentioned()
                                    if o.get("_id") is not None and RECEIVED_AT_KEY in o}
                        for obs in docs:
                            if obs.get("_id") in received:
                                obs[RECEIVED_AT_KEY] = received[obs["_id"]]
                        cache.clear()
                        for obs in reversed(docs):
                            self._add_to_cache(cache, obs)

                # 前回はなかった観測をコールバックに知らせる（書き込みロックの外で）
                for docs, previous in ((new_physical, previous_physical_ids), (new_cyber, previous_cyber_ids)):
                    for obs in docs:
                        if obs.get("_id") and obs.get("_id") not in previous:
                            self._observation_validator.check(obs)
                            self._notify_callbacks(obs, "polling")
                previous_physical_ids, previous_cyber_ids = current_physical_ids, current_cyber_ids

                if new_physical or new_cyber:
                    self._logger.debug(
                        f"Polling update: {len(new_physical)} physical + {len(new_cyber)} cyber observations in cache"
                    )

            except Exception as e:
                self._logger.error(f"Error in polling mode: {e}", exc_info=True)

            # 次のポーリングまで待機
            time.sleep(self.poll_interval)

        self._logger.info("Polling mode stopped")

    def update_mentioned_in_cache(
        self,
        observations: List[Dict[str, Any]]
    ) -> None:
        """
        メモリキャッシュ内の観測データのmentionedフラグを更新

        Args:
            observations: 更新する観測データのリスト
        """
        if not observations:
            return

        # 更新対象のIDリストを作成
        obs_ids = [obs["_id"] for obs in observations if "_id" in obs]

        updated_count = 0
        with self._write_lock:
            # IndexedObservationCacheのAPIを使用してmentionedフラグを更新
            updated_count += self.physical_cache.update_mentioned(obs_ids)
            updated_count += self.cyber_cache.update_mentioned(obs_ids)

        self._logger.debug(
            f"Updated mentioned flag in cache for {updated_count}/{len(obs_ids)} observations"
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            統計情報の辞書
        """
        with self._read_lock:
            return {
                "physical_cache_size": len(self.physical_cache),
                "cyber_cache_size": len(self.cyber_cache),
                "physical_inserts": self.stats["physical_inserts"],
                "cyber_inserts": self.stats["cyber_inserts"],
                "cache_hits": self.stats["cache_hits"],
                "last_update": self.stats["last_update"],
                "change_streams_enabled": self.use_change_streams,
                "running": self.running,
                "rwlock_enabled": True,
                "physical_cache_stats": self.physical_cache.get_stats(),
                "cyber_cache_stats": self.cyber_cache.get_stats(),
                "callback_count": self.get_callback_count(),
                "callback_invocations": self.stats["callback_invocations"],
                "callback_errors": self.stats["callback_errors"]
            }

    def stop(self) -> None:
        """監視を停止"""
        self.running = False

        # スレッドの終了を少しだけ待つ（daemon スレッドなので、終わらなくてもプロセスと一緒に終わる）
        for thread in self.watch_threads:
            thread.join(timeout=1)

        self._logger.info("ObservationWatcher stopped")

        # 最終統計を出力
        stats = self.get_stats()
        self._logger.info(
            f"Final stats: physical_cache={stats['physical_cache_size']}, "
            f"cyber_cache={stats['cyber_cache_size']}, "
            f"total_inserts={stats['physical_inserts'] + stats['cyber_inserts']}, "
            f"cache_hits={stats['cache_hits']}"
        )

    # ═══════════════════════════════════════════════════════════════
    # コールバック管理
    # ═══════════════════════════════════════════════════════════════

    def register_callback(self, callback: ObservationCallback) -> None:
        """
        観測データ到着時のコールバックを登録

        Args:
            callback: ObservationCallbackプロトコルを実装したオブジェクト

        Note:
            - 同一コールバックを複数回登録すると、複数回呼び出される
            - コールバックは登録順に呼び出される
            - コールバックは同期的に呼び出される（非同期ではない）
        """
        with self._callback_lock:
            self._callbacks.append(callback)
            self._logger.info(
                f"Callback registered: {type(callback).__name__} "
                f"(total: {len(self._callbacks)})"
            )

    def unregister_callback(self, callback: ObservationCallback) -> bool:
        """
        コールバックを解除

        Args:
            callback: 解除するコールバック

        Returns:
            解除に成功した場合True、見つからなかった場合False
        """
        with self._callback_lock:
            try:
                self._callbacks.remove(callback)
                self._logger.info(
                    f"Callback unregistered: {type(callback).__name__} "
                    f"(remaining: {len(self._callbacks)})"
                )
                return True
            except ValueError:
                self._logger.warning(
                    f"Callback not found for unregistration: {type(callback).__name__}"
                )
                return False

    def _notify_callbacks(self, observation: Dict[str, Any], source: str) -> None:
        """
        全コールバックに新しい観測データを通知

        Args:
            observation: 観測データ辞書
            source: 通知元（"change_streams" または "polling"）

        Note:
            - コールバックでエラーが発生しても、他のコールバックは継続して呼び出される
            - エラーはログに記録され、統計情報に反映される
        """
        with self._callback_lock:
            callbacks_copy = list(self._callbacks)

        if not callbacks_copy:
            return

        for cb in callbacks_copy:
            try:
                cb.on_observation(observation)
                self.stats["callback_invocations"] += 1
            except Exception as e:
                self.stats["callback_errors"] += 1
                self._logger.error(
                    f"Callback error in {type(cb).__name__}: {e}",
                    exc_info=True
                )

        self._logger.debug(
            f"Notified {len(callbacks_copy)} callback(s) from {source}: "
            f"event={observation.get('event')}"
        )

    def get_callback_count(self) -> int:
        """
        登録されているコールバックの数を取得

        Returns:
            コールバック数
        """
        with self._callback_lock:
            return len(self._callbacks)
