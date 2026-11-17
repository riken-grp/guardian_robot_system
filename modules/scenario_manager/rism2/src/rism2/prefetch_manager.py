"""prefetch_manager.py - LLMプリフェッチ管理モジュール"""
import threading
import time
from logging import getLogger
from typing import Dict, Any, List, Optional

from . import event_generators
from .event_model import Event, EventLike, IfEvent, RandomEvent, RepeatEvent, ShuffleEvent, UntilEvent, WaitForEvent
from .protocols import PrefetchRuntime


class PrefetchManager:
    """
    LLMプリフェッチ管理クラス

    generateイベントの実行中に次のイベントを先読みし、
    キャッシュすることでレスポンス速度を向上させる。
    キャッシュ・スレッド・ロックはすべてこのクラスが持つ。

    キャッシュキーは key_for(event): イベントの元のデータ（raw の辞書）と、repeat の何回目か。
    repeat の回ごとのコピーも、Event Generator が作ったイベント（辞書）も、元のデータは同じ辞書なので、
    先読みする側と実行する側で同じキーになる。
    """

    # 聞いた発話や今の状況で答えが決まるので、先に作らない Generator
    NO_PREFETCH_GENERATORS = {"KeywordResponseEventGenerator", "KnowledgeEventGenerator", "EchoBackEventGenerator"}

    def __init__(
        self,
        interpreter: PrefetchRuntime,
        enabled: bool = True,
        wait_timeout: float = 30.0
    ):
        """
        初期化

        Args:
            interpreter: ScenarioInterpreter インスタンス
            enabled: プリフェッチ機能の有効/無効
            wait_timeout: キャッシュ待機のタイムアウト（秒）
        """
        self._interpreter = interpreter
        self._logger = getLogger(__name__)

        # 設定
        self.prefetch_enabled = enabled
        self.prefetch_wait_timeout = wait_timeout

        # キャッシュ管理
        self.prefetch_cache: Dict[Any, Dict[str, Any]] = {}
        self.prefetch_lock = threading.Lock()
        self.prefetch_threads: Dict[Any, threading.Thread] = {}

    # 作っている途中の先読みを、少なくともこの秒数は待つ（LLM が普通に応答する時間より十分長く）
    MIN_WAIT_WHILE_GENERATING = 20.0

    def clear_cache(self) -> None:
        """プリフェッチキャッシュをクリア"""
        with self.prefetch_lock:
            self.prefetch_cache.clear()
            self.prefetch_threads.clear()

        # current_stateをリセット
        self._interpreter.update_current_state({
            "processing": {
                "is_prefetching": False,
                "prefetch_event_index": -1
            }
        })

        self._logger.debug("Prefetch cache cleared")

    def contains(self, cache_key: Any) -> bool:
        """そのキーの先読みがあるか（生成中も含む）"""
        with self.prefetch_lock:
            return cache_key in self.prefetch_cache

    @classmethod
    def can_prefetch(cls, event: EventLike) -> bool:
        """
        先に作ってよい generate イベントか

        実行の時点の状況が要るもの（会話を覚える save、最近の観測、聞いた発話で答えを決める Generator）は先に作らない
        """
        speak = getattr(Event.coerce(event), "speak", None)
        if not isinstance(speak, dict) or speak.get("type") != "generate":
            return False
        option = speak.get("option", {})
        return not (option.get("save") or option.get("use_observations")
                    or option.get("generator") in cls.NO_PREFETCH_GENERATORS)

    def _context_snapshot(self) -> tuple:
        """
        先読みの結果を使ってよいかを判断するための、生成に効く状況

        相手の発話、wait_for の結果、割り込みのきっかけの観測が先読みのあとで変わっていたら、その結果は使わない。
        """
        ctx = self._interpreter.ctx
        heard = tuple(e.get("text") for e in ctx.conversation_history if e.get("actor") == "user")
        triggered = ctx.triggered_observation.get("_id") if isinstance(ctx.triggered_observation, dict) else None
        return heard, repr(ctx.wait_for_result), repr(triggered)

    def _target_event(self, event: Event) -> Optional[Event]:
        """
        先読みする対象。コンテナイベントは最初の subevent（repeat は最初、until は loop、wait_for / if は failure 側）

        random は、ここで実行する候補を決めておき（ctx.random_picks）、その候補の最初を先読みする。
        実行するときは同じ候補を実行するので、どの候補が選ばれても先読みが効く。
        shuffle も同じく、ここで順番を決めておき（ctx.shuffle_orders）、最初に実行する候補の最初を先読みする。

        wait_for / if は、返事が来ると wait_for の結果が変わるので、success / true 側を先に作っても使えない
        （take で stale になる）。時間切れの failure 側は結果が変わらないので、待っている間に作っておける。
        """
        if isinstance(event, RepeatEvent):
            branch = event.subevents
        elif isinstance(event, RandomEvent):
            index = self._pick_random(event)
            branch = event.choices[index] if index is not None else []
        elif isinstance(event, ShuffleEvent):
            branch = [subevent for index in self._pick_shuffle(event) for subevent in event.choices[index]]
        elif isinstance(event, IfEvent):
            branch = event.failure
        elif isinstance(event, UntilEvent):
            branch = event.loop
        elif isinstance(event, WaitForEvent):
            branch = event.failure
        else:
            return event
        return branch[0] if branch else None

    def _pick_random(self, event: RandomEvent) -> Optional[int]:
        """random の実行する候補（先に選んでいればそれ、なければ今選んで覚えておく）"""
        picks = self._interpreter.ctx.random_picks
        key = id(event.raw)
        if key not in picks:
            index = event.pick_index()
            if index is None:
                return None
            picks[key] = index
        return picks[key]

    def _pick_shuffle(self, event: ShuffleEvent) -> List[int]:
        """shuffle の実行する順番（先に決めていればそれ、なければ今決めて覚えておく）"""
        orders = self._interpreter.ctx.shuffle_orders
        key = id(event.raw)
        if key not in orders:
            orders[key] = event.pick_order()
        return orders[key]

    def start_repeat_prefetch(self, event: Event) -> None:
        """repeat の次の回の subevent（with_repeat で次の回の位置を付けたもの）のプリフェッチを開始"""
        self._start(self.key_for(event), event, f"repeat round {event.repeat.count if event.repeat else '?'}")

    @staticmethod
    def key_for(event: EventLike) -> tuple:
        """先読みのキー: イベントの元のデータ（raw の辞書）と、repeat の何回目か"""
        event = Event.coerce(event)
        return id(event.raw), event.repeat.count if event.repeat is not None else None

    def _key_for_scenario_event(self, event: Event) -> tuple:
        """シナリオのイベントを先読みするときのキー（repeat なら1回目の最初の subevent、ほかのコンテナは最初のイベント）"""
        target = self._target_event(event) or event
        return (id(target.raw), 1) if isinstance(event, RepeatEvent) and target is not event else self.key_for(target)

    def _start(self, cache_key: Any, event: EventLike, label: str) -> bool:
        """キャッシュエントリを作り、バックグラウンドで生成を始める。既にあるか、先に作れないイベントなら何もしない"""
        if not self.prefetch_enabled or not self.can_prefetch(event):
            return False
        event = Event.coerce(event).to_dict()  # Event Generator には dict を渡す
        context = self._context_snapshot()
        with self.prefetch_lock:
            if cache_key in self.prefetch_cache or cache_key in self.prefetch_threads:
                return False
            entry = {
                "events": None,
                "status": "generating",
                "error": None,
                "start_time": time.time(),
                "context": context
            }
            self.prefetch_cache[cache_key] = entry
            thread = threading.Thread(
                target=self._prefetch_generate,
                args=(cache_key, event, entry),
                name=f"PrefetchThread-{cache_key}",
                daemon=True
            )
            self.prefetch_threads[cache_key] = thread
        thread.start()

        generator_name = event.get("speak", {}).get("option", {}).get("generator", event_generators.DEFAULT_GENERATOR)
        self._logger.info(f"Started prefetch for {label}: actor={event.get('actor', 'unknown')}, generator={generator_name}")
        return True

    def start_first_utterance_prefetch(self, events: List[Event]) -> bool:
        """
        割り込みの最初の発話を、移動を止める（stop の処理を待つ）間に作り始める

        先頭から、話さない action（正面を向くなど）だけが続いたあとの generate を対象にする。
        """
        for event in events:
            if self.can_prefetch(event):
                return self._start(self.key_for(event), event, "first utterance of the interrupt")
            if event.type != "action" or getattr(event, "speak", None) is not None:
                return False
        return False

    def try_start_next_event_prefetch(self) -> bool:
        """
        いま実行中のイベントの、次のイベントの先読みを始める（各イベントの処理の始めに呼ぶ）

        次のイベントは、一番内側で実行中のイベントの並び（メインシナリオ、割り込みのサブシナリオ、
        wait_for / if / until の分岐、include の部品、random の中身）の次。生成したイベントの実行中は、その次。
        コンテナイベント（if / until / wait_for など）なら、その最初のイベント。

        Returns:
            先読みを始めたら True
        """
        if not self.prefetch_enabled:
            return False
        ctx = self._interpreter.ctx
        if ctx.current_generated_events is not None:
            next_gen_idx = ctx.current_generated_index + 1
            if next_gen_idx < len(ctx.current_generated_events):
                next_gen_event = ctx.current_generated_events[next_gen_idx]
                key = self.key_for(next_gen_event)
                return self._start(key, next_gen_event, f"generated event {key}")
            # 生成したイベントの最後なら、並びの次のイベントを先読みする

        next_event = ctx.next_event_to_prefetch()
        if next_event is None:
            return False
        event = Event.coerce(next_event)
        target = self._target_event(event)
        # コンテナの中がさらにコンテナなら先読みしない
        if target is None or (target is not event and target.type != "action"):
            return False
        container = f" (in {event.type})" if target is not event else ""
        if not self._start(self._key_for_scenario_event(event), target, f"next event{container}"):
            return False
        self._interpreter.update_current_state({"processing": {"is_prefetching": True}})
        return True

    def take(self, cache_key: Any) -> Optional[List[Dict[str, Any]]]:
        """
        先読みした結果を取り出す。生成中なら作り終わるまで待つ（止まったとみなすまで）。

        取り出したキーはキャッシュから消す。
        Returns:
            生成されたイベント。先読みが無い・失敗した・間に合わなかったときは None
        """
        with self.prefetch_lock:
            entry = self.prefetch_cache.get(cache_key)
        if entry is None:
            return None

        elapsed_since_start = time.time() - entry.get("start_time", time.time())
        self._logger.info(f"Found prefetch cache for key {cache_key}, status: {entry['status']} (elapsed: {elapsed_since_start:.2f}s)")
        # 作っている途中なら、終わるまで待つ（いま作り直しても、先に始めた先読みより先には終わらない）。
        # 待つのをやめるのは、先読みが止まったとみなせるとき（wait_timeout と MIN_WAIT_WHILE_GENERATING の長い方）だけ
        limit = max(self.prefetch_wait_timeout, self.MIN_WAIT_WHILE_GENERATING)
        if entry["status"] == "generating":
            self._logger.info(f"Prefetch still generating (already waited {elapsed_since_start:.2f}s), waiting up to {limit}s more for completion...")

        events = None
        start_wait = time.time()
        while True:
            with self.prefetch_lock:
                entry = self.prefetch_cache.get(cache_key)
            if entry is None:
                break
            if entry.get("context") != self._context_snapshot():
                # 状況が変わった（相手が話した、wait_for の結果が変わった）。作り終わるのを待っても使えない
                self._logger.info(f"Prefetched events for key {cache_key} are stale (the person spoke or wait_for changed), generating again")
                break
            if entry["status"] == "completed":
                events = entry["events"]
                count = len(events) if events else 0
                self._logger.info(f"Using prefetched events for key {cache_key} ({count} cached event(s), waited {time.time() - start_wait:.2f}s)")
                break
            if entry["status"] == "error":
                self._logger.warning(f"Prefetch failed: {entry.get('error')}, falling back to normal generation")
                break
            if time.time() - start_wait >= limit:
                self._logger.warning(f"Prefetch timeout after {time.time() - start_wait:.2f}s (limit: {limit}s), falling back to normal generation")
                break
            time.sleep(0.05)

        with self.prefetch_lock:
            self.prefetch_cache.pop(cache_key, None)
        return events

    def _prefetch_generate(self, cache_key, event: Dict[str, Any], entry: Dict[str, Any]) -> None:
        """
        バックグラウンドでgenerateイベントを実行

        Args:
            cache_key: キャッシュキー（int or str）
            event: イベント辞書
            entry: このスレッドの結果を書くキャッシュエントリ（クリアされたあとに同じキーで作り直されたものには書かない）
        """
        event_id = cache_key if isinstance(cache_key, str) else f"event {cache_key}"
        try:
            generated_events = self._run_generator(event, event_id)
            with self.prefetch_lock:
                if self.prefetch_cache.get(cache_key) is not entry:  # クリアされた
                    return
                entry.update(events=generated_events, status="completed")
            self._log_generated(event_id, generated_events)
        except Exception as e:
            self._logger.error(f"Prefetch error for cache_key {cache_key}: {e}", exc_info=True)
            with self.prefetch_lock:
                if self.prefetch_cache.get(cache_key) is entry:
                    entry.update(status="error", error=str(e))
        finally:
            self._interpreter.update_current_state({
                "processing": {"is_prefetching": False, "prefetch_event_index": -1}
            })
            # スレッドリストから削除（作り直された同じキーのスレッドは消さない）
            with self.prefetch_lock:
                if self.prefetch_cache.get(cache_key) is entry or cache_key not in self.prefetch_cache:
                    self.prefetch_threads.pop(cache_key, None)

    def _run_generator(self, event: Dict[str, Any], event_id: str) -> List[Dict[str, Any]]:
        """Event Generator で発話を作る（会話履歴と観測は、いまの時点のもの）"""
        actor = event.get("actor")
        option = event.get("speak", {}).get("option", {})
        generator_name = option.get("generator", event_generators.DEFAULT_GENERATOR)
        generators = self._interpreter.event_generators
        if generator_name not in generators:
            generators[generator_name] = event_generators.get_generator(generator_name, self._interpreter.config)

        history = self._interpreter.event_processor.build_llm_history(actor)
        ctx = self._interpreter.ctx
        observations = {"wait_for": ctx.wait_for_result} if ctx.wait_for_result else {}
        if ctx.triggered_observation:
            observations["triggered"] = ctx.triggered_observation

        self._logger.info(f"[PREFETCH] Calling {generator_name}.generate() for {event_id}, actor={actor}")
        return generators[generator_name].generate(actor=actor, event=event, history=history, observations=observations)

    def _log_generated(self, event_id: str, generated_events: List[Dict[str, Any]]) -> None:
        """生成されたイベントの概要をログに出す"""
        self._logger.info(f"Prefetch completed for {event_id}: {len(generated_events)} event(s) generated")
        for i, gen_event in enumerate(generated_events, 1):
            event_actor = gen_event.get("actor", "unknown")
            if "speak" in gen_event:
                speak_text = gen_event["speak"].get("text", "")
                if len(speak_text) > 100:
                    speak_text = speak_text[:100] + "..."
                self._logger.info(f"  [{i}] {event_actor}: speak=\"{speak_text}\"")
            elif "gesture" in gen_event:
                self._logger.info(f"  [{i}] {event_actor}: gesture={gen_event['gesture'].get('type', 'unknown')}")
            elif "navigation" in gen_event:
                nav_option = gen_event["navigation"].get("option", {})
                destination = nav_option.get("goal", nav_option.get("destination", "unknown"))
                self._logger.info(f"  [{i}] {event_actor}: navigation -> {destination}")
            else:
                self._logger.info(f"  [{i}] {event_actor}: {gen_event.get('type', 'action')}")
