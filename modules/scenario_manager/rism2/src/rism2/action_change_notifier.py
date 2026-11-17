"""action_change_notifier.py - Actions の動作の状態が変わったことを、変更通知（Change Streams）で知らせる

動作の完了を待つ処理は、状態を読んでから少し待つ、をくり返す。待つ間に状態が変わったら、すぐ起こす。

    with notifier_for(collection).watching(action_id) as changed:
        while ...:
            status = get_action_status(manager, action_id)
            ...
            notifier.pause(changed)   # 状態が変わればすぐ戻る（変わらなければ 0.5 秒）

変更通知が使えないコレクション（mongomock など）や、通知が止まったときは、0.1 秒ずつ待つ（これまでどおり）。
"""
import threading
from contextlib import contextmanager
from logging import getLogger
from typing import Any, Dict, Iterator

from pymongo.collection import Collection

# 変更通知を使えないときに待つ時間（秒）
POLL_SECONDS = 0.1
# 変更通知を使えるときに、変化がなくても状態を読み直す間隔（秒）
RECHECK_SECONDS = 0.5


class _Polling:
    """変更通知を使わないとき: wait は長くても POLL_SECONDS で戻る"""

    def __init__(self):
        self._event = threading.Event()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(min(timeout, POLL_SECONDS))

    def clear(self) -> None:
        self._event.clear()


class ActionChangeNotifier:
    """1つの Actions コレクションの更新を見張り、待っている動作に知らせる"""

    def __init__(self, collection: Any):
        self._logger = getLogger(__name__)
        self._collection = collection
        self._waiting: Dict[Any, threading.Event] = {}
        self._lock = threading.Lock()
        self.active = isinstance(collection, Collection)
        if self.active:
            threading.Thread(target=self._watch, name="ActionChangeNotifier", daemon=True).start()

    @contextmanager
    def watching(self, action_id: Any) -> Iterator[Any]:
        """
        この動作の状態が変わったら set される Event（の代わり）

        状態を読む前に準備するので、読んだ直後に変わっても取りこぼさない。
        """
        if not self.active:
            yield _Polling()
            return
        event = threading.Event()
        with self._lock:
            self._waiting[action_id] = event
        try:
            yield event
        finally:
            # follow() で別の ID に替わっていることもあるので、この待ちのものはすべて外す
            with self._lock:
                for key in [k for k, v in self._waiting.items() if v is event]:
                    del self._waiting[key]

    def pause(self, changed: Any) -> None:
        """次に状態を読むまで待つ。変わればすぐ戻る（通知が止まっていれば POLL_SECONDS）"""
        changed.wait(RECHECK_SECONDS if self.active else POLL_SECONDS)
        changed.clear()

    def follow(self, old_id: Any, new_id: Any) -> None:
        """待っている動作が別の ID に替わった（送り直し、割り込みのあとの再開）"""
        with self._lock:
            event = self._waiting.pop(old_id, None)
            if event is not None:
                self._waiting[new_id] = event
                event.set()  # 替わったらすぐ読み直す

    def _watch(self) -> None:
        try:
            pipeline = [{"$match": {"operationType": {"$in": ["update", "replace"]}}}]
            with self._collection.watch(pipeline) as stream:
                self._logger.info(f"Watching action status changes in {self._collection.full_name}")
                for change in stream:
                    action_id = (change.get("documentKey") or {}).get("_id")
                    with self._lock:
                        event = self._waiting.get(action_id)
                    if event is not None:
                        event.set()
        except Exception as e:
            self._logger.warning(f"Action change stream stopped, polling every {POLL_SECONDS}s: {e}")
        finally:
            self.active = False
            with self._lock:
                for event in self._waiting.values():
                    event.set()  # 待っているものを起こし、以後はポーリングにする


_notifiers: Dict[str, ActionChangeNotifier] = {}
_notifiers_lock = threading.Lock()


def notifier_for(collection: Any) -> ActionChangeNotifier:
    """コレクションごとに1つの通知役（変更通知が止まったら作り直す）"""
    if not isinstance(collection, Collection):
        return ActionChangeNotifier(collection)
    key = f"{id(collection.database.client)}/{collection.full_name}"
    with _notifiers_lock:
        notifier = _notifiers.get(key)
        if notifier is None or not notifier.active:
            notifier = _notifiers[key] = ActionChangeNotifier(collection)
        return notifier
