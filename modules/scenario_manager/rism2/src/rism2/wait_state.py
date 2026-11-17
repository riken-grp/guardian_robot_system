"""wait_state.py - 待ち状態を current_state.waiting / last_wait に出す（外部のビューア pd_room_checker 用）

waiting: 待っている間の待ちのスタック（外側から順。入れ子: until の中の wait_for、待ちの最中の割り込みの中の待ちなど）。
last_wait: 直近に終わった待ち（1件）。

待ちの種類（kind）: wait_for / if / until / pre_wait_action / action / command_event
結果（result）: matched / unmatched / timeout / exit / done / failed
時刻は UTC で、current_state.last_updated と同じ書式。
条件は JSON 文字列にして書く（dict のままだと $regex などが MongoDB のパスに入ってしまう）。
"""
import datetime
import json
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # StateManager の last_updated と同じ


def _utc(t: datetime.datetime) -> str:
    return t.astimezone(datetime.timezone.utc).strftime(TIME_FORMAT)


class WaitHandle:
    """with ブロックの中で結果を設定する（設定しなければ、例外なら failed、それ以外は done）"""

    def __init__(self) -> None:
        self.result: Optional[str] = None


class WaitStateTracker:
    """待ち状態のスタックを持ち、変わるたびに current_state に書く"""

    def __init__(self, interpreter: Any) -> None:
        self._interpreter = interpreter
        self._stack: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    @contextmanager
    def waiting(self, kind: str, event: Any = None, condition: Any = None, timeout: Optional[float] = None,
                actions: Optional[List[Dict[str, str]]] = None) -> Iterator[WaitHandle]:
        """ブロックの間、待ちとして waiting に積む。抜けたら外して last_wait に書く"""
        ctx = self._interpreter.ctx
        scenario = ctx.top_frame.scenario  # 割り込み中ならサブシナリオ
        started = datetime.datetime.now(datetime.timezone.utc)
        entry = {
            "kind": kind,
            "actor": getattr(event, "actor", None),
            "scenario_name": scenario.name if scenario is not None else None,
            "is_interruption": ctx.interrupt_depth > 0,
            "condition": json.dumps(condition, ensure_ascii=False, default=str) if condition is not None else None,
            "timeout": float(timeout) if timeout is not None else None,
            "started_at": _utc(started),
            "deadline_at": _utc(started + datetime.timedelta(seconds=float(timeout))) if timeout is not None else None,
            "interruptable": getattr(event, "interruptable", None),
            "actions": actions,
        }
        handle = WaitHandle()
        with self._lock:
            self._stack.append(entry)
            self._publish()
        try:
            yield handle
        except Exception:
            handle.result = handle.result or "failed"
            raise
        except BaseException:
            # EventInterrupted（割り込みの resume_after: next_event / restart で待ちを抜ける）や停止の要求
            handle.result = handle.result or "exit"
            raise
        finally:
            last = {k: entry[k] for k in ("kind", "scenario_name", "condition", "timeout", "started_at")}
            last["ended_at"] = _utc(datetime.datetime.now(datetime.timezone.utc))
            last["result"] = handle.result or "done"
            with self._lock:
                for i, item in enumerate(self._stack):
                    if item is entry:
                        del self._stack[i]
                        break
                self._publish(last_wait=last)

    def reset(self) -> None:
        """メインシナリオを読み込むときに、残っている待ちを消す（last_wait は残す）"""
        with self._lock:
            self._stack.clear()
            self._publish()

    def _publish(self, last_wait: Optional[Dict[str, Any]] = None) -> None:
        updates: Dict[str, Any] = {"waiting": [dict(item) for item in self._stack]}  # list は展開されず、そのまま置き換わる
        if last_wait is not None:
            updates["last_wait"] = last_wait
        try:
            self._interpreter.update_current_state(updates)
        except Exception:
            pass  # 表示用なので、DB に書けなくてもシナリオの実行は止めない
