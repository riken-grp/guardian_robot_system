"""MongoDB (RISM の tBlackBoard) から画面表示用の情報を読み出す"""
import ast
import functools
import json
import logging
import math
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient

logger = logging.getLogger(__name__)

ACTION_SCAN_LIMIT = 500  # 行動の表示のために読む最新ドキュメント数 (DB負荷の上限)
LOCATION_MATCH_DISTANCE = 0.5  # 移動先がこの距離 (m) 以内なら場所名を表示する
MAP_MARGIN = 40  # 地図を切り出すときの余白 (px)
MAP_MIN_WIDTH = 800  # 切り出した地図がこれより狭いときは拡大する (px). 印の大きさを保つため

# 表示する行動の種類 (Actions コレクションの command) と表示名. この順に並べる
ACTION_KINDS = {
    "speak": "発話",
    "navigation": "移動",
    "gesture": "ジェスチャ",
    "eye": "目",
    "ros_command": "ROSコマンド",
}

GESTURE_NAMES = {
    "look_down": "下を見る",
    "look_up": "上を見る",
    "look_left": "左を見る",
    "look_right": "右を見る",
    "look_front": "正面を見る",
    "Look_around": "見回す",
    "raise_hand": "手を挙げる",
    "speaking_a": "話す動作A",
    "speaking_b": "話す動作B",
    "thinking": "考える",
    "default_posture": "基本姿勢",
    "bowing": "お辞儀",
    "bowing_max": "深いお辞儀",
    "nodding": "うなずく",
    "pointing_left": "左を指す",
    "lets_go_pose": "「行こう」のポーズ",
    "sighing": "ため息",
    "tilting_head": "首をかしげる",
    "shrugging": "肩をすくめる",
    "facepalm": "頭を抱える",
}

EYE_NAMES = {
    "default": "通常",
    "neutral1": "ふつう",
    "smile": "笑顔",
    "sad": "悲しい",
    "thinking": "考え中",
    "thinking2": "考え中2",
}

# current_state.processing のフラグと表示名
PROCESSING_FLAGS = {
    "is_navigating": "移動中",
    "is_tts_processing": "発話中",
    "is_llm_generating": "応答生成中",
    "is_asr_waiting": "観測待ち",
    "is_prefetching": "先読み中",
}


# RISM の待ちの種類 (current_state.waiting[].kind) と表示名
WAIT_KINDS = {
    "wait_for": "観測待ち（wait_for）",
    "if": "条件分岐の観測待ち（if）",
    "until": "ループの終了条件待ち（until）",
    "pre_wait_action": "待つ前の動作の完了待ち",
    "action": "動作の完了待ち",
    "command_event": "コマンドの完了待ち",
}
WAIT_RESULTS = {
    "matched": "条件成立",
    "unmatched": "条件不成立",
    "timeout": "時間切れ",
    "exit": "打ち切り",
    "done": "完了",
    "failed": "失敗",
}
TIMELINE_MAX_DOCS = 2000
TIME_FORMAT = "%H:%M:%S"

# 同じ情報を閲覧者の数だけ DB に問い合わせないよう, 結果を短時間使い回す (秒)
STATE_TTL = 1.0
ACTIONS_TTL = 1.0
HISTORY_TTL = 1.0
TIMELINE_TTL = 2.0
DEFINITION_TTL = 60.0  # シナリオの定義はめったに変わらない
DEFINITION_EVENT_COUNT = 10  # 詳細に並べるイベントの数


def ttl_cache(seconds):
    """メソッドの結果を引数ごとに seconds 秒だけ使い回す (スレッドプールから同時に呼ばれてもよい)"""
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args):
            key = (method.__name__, args)
            now = time.monotonic()
            with self._cache_lock:
                hit = self._cache.get(key)
            if hit is not None and now - hit[0] < seconds:
                return hit[1]
            value = method(self, *args)
            with self._cache_lock:
                self._cache[key] = (time.monotonic(), value)
            return value
        return wrapper
    return decorator


def parse_utc(value):
    """タイムゾーンなしのUTC時刻 (datetime または文字列) を aware な datetime にする"""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def utc_to_local_text(value):
    """タイムゾーンなしのUTC時刻 (datetime または文字列) をローカル時刻の文字列にする"""
    value = parse_utc(value)
    return value.astimezone().strftime(TIME_FORMAT) if value else ""


def local_text(value):
    """ローカル時刻で保存されている (タイムゾーンなしの) 時刻を文字列にする"""
    return value.strftime(TIME_FORMAT) if isinstance(value, datetime) else ""


def _as_dict(value):
    """dict か, dict を文字列化したもの (古いデータ) を dict にする"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError):
            return {}
    return {}


def _exit_code(doc):
    return _as_dict(doc.get("exit_status")).get("exit_code", "")


# MongoDB の比較演算子の表示
OPERATORS = {"$gte": "≥", "$gt": ">", "$lte": "≤", "$lt": "<", "$ne": "≠", "$eq": "="}


def _describe_rule(field, rule):
    """条件の1項目 ({"$regex": ...} や {"$gte": 3} など) を文字列にする"""
    if not isinstance(rule, dict):
        return f"{field} = {json.dumps(rule, ensure_ascii=False)}"
    parts = []
    for op, operand in rule.items():
        if op == "$regex":
            parts.append(f"{field} が /{operand}/ に一致")
        elif op in OPERATORS:
            parts.append(f"{field} {OPERATORS[op]} {json.dumps(operand, ensure_ascii=False)}")
        elif op in ("$in", "$nin") and isinstance(operand, list):
            values = "、".join(json.dumps(v, ensure_ascii=False) for v in operand)
            parts.append(f"{field} が {values} の{'いずれか' if op == '$in' else 'どれでもない'}")
        elif op == "$exists":
            parts.append(f"{field} が{'ある' if operand else 'ない'}")
        else:
            parts.append(f"{field} {op} {json.dumps(operand, ensure_ascii=False)}")
    return "、".join(parts)


def describe_condition(condition):
    """wait_for などの条件 (JSON文字列または dict) を読みやすい文字列にする"""
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except ValueError:
            return condition
    if not isinstance(condition, dict) or not condition:
        return ""
    parts = []
    for key, value in condition.items():
        if value is None:
            parts.append(f"{key}（内容は問わない）")
        elif isinstance(value, dict):
            fields = []
            for field, rule in value.items():
                fields.append(_describe_rule(field, rule))
            parts.append(f"{key}（{'、'.join(fields)}）")
        else:
            parts.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    return " または ".join(parts)


def describe_wait(entry, now):
    """current_state.waiting の1件を表示用にする"""
    entry = _as_dict(entry)
    deadline = parse_utc(entry.get("deadline_at"))
    actions = entry.get("actions") or []
    return {
        "kind": WAIT_KINDS.get(entry.get("kind"), entry.get("kind") or "待ち"),
        "condition": describe_condition(entry.get("condition")),
        "actions": "、".join(str(_as_dict(a).get("command", "")) for a in actions if a),
        "scenario_name": entry.get("scenario_name") or "",
        "interruption": bool(entry.get("is_interruption")),
        "timeout": entry.get("timeout"),
        "started": utc_to_local_text(entry.get("started_at")),
        "remaining": max((deadline - now).total_seconds(), 0) if deadline else None,
    }


def describe_last_wait(last_wait):
    last_wait = _as_dict(last_wait)
    if not last_wait:
        return None
    return {
        "kind": WAIT_KINDS.get(last_wait.get("kind"), last_wait.get("kind") or ""),
        "condition": describe_condition(last_wait.get("condition")),
        "result": WAIT_RESULTS.get(last_wait.get("result"), last_wait.get("result") or ""),
        "result_code": last_wait.get("result") or "",
        "ended": utc_to_local_text(last_wait.get("ended_at")),
    }


def _with_seconds(text, option):
    if "duration" in option:
        text += f"・{option['duration']}秒"
    return text


def describe_action(command, option, location_name):
    """Actions の option を画面表示用の文字列にする"""
    try:
        if command == "speak":
            return option.get("text", "")
        if command == "navigation":
            if "navigation" in option:
                x, y, yaw = option["navigation"][:3]
                text = f"座標 ({x:.2f}, {y:.2f})・向き {math.degrees(yaw):.0f}°"
                name = location_name(x, y)
                return f"{name}へ　{text}" if name else text
            if "move" in option:
                return f"前進 {option['move']} m"
            if "rotate" in option:
                return f"回転 {math.degrees(option['rotate']):.0f}°"
        if command == "gesture":
            name = option.get("gesture", "")
            label = GESTURE_NAMES.get(name)
            return _with_seconds(f"{label}（{name}）" if label else name, option)
        if command == "eye":
            image = option.get("image", "")
            label = EYE_NAMES.get(image.rsplit(".", 1)[0])
            return _with_seconds(f"{label}（{image}）" if label else image, option)
        if command == "ros_command":
            return f"{option.get('topic', '')} ← {option.get('data', '')}"
    except (TypeError, ValueError, KeyError, IndexError):
        pass
    return str(option)


class Blackboard:
    """tBlackBoard の読み出し. メソッドはスレッドプールから同時に呼ばれる"""

    def __init__(self, host, port, db_name, robot_name, action_count, map_region=None):
        self._db = MongoClient(host, port, serverSelectionTimeoutMS=3000)[db_name]
        self._robot_name = robot_name
        self._action_count = action_count
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._load_lock = threading.Lock()  # 場所と地図の初回読み込み用
        self._locations = None
        self._map = None
        self._map_region = map_region  # 地図を表示する範囲 (世界座標 x_min/x_max/y_min/y_max). None なら自動

    # ---- 場所 ----
    def locations(self):
        """登録されている場所 (名前と座標). 変わることはまれなので初回だけ読む"""
        if self._locations is None:
            with self._load_lock:
                if self._locations is None:
                    self._locations = [
                        {
                            "name": doc["name"],
                            "x": float(doc["pose"][0]),
                            "y": float(doc["pose"][1]),
                            "active": doc.get("status") == "active",
                        }
                        for doc in self._db["locations"].find({}, {"name": 1, "pose": 1, "status": 1})
                        if isinstance(doc.get("pose"), list) and len(doc["pose"]) >= 2
                    ]
        return self._locations

    def location_name(self, x, y):
        """(x, y) の近く (LOCATION_MATCH_DISTANCE 以内) に登録された場所があればその名前"""
        best = min(self.locations(), key=lambda loc: math.hypot(loc["x"] - x, loc["y"] - y), default=None)
        if best and math.hypot(best["x"] - x, best["y"] - y) <= LOCATION_MATCH_DISTANCE:
            return best["name"]
        return None

    # ---- 行動 ----
    @ttl_cache(ACTIONS_TTL)
    def actions(self):
        """ロボットの最新の行動 (種類ごと, 新しい順) と, 実行待ち/実行中の移動先"""
        docs = (
            self._db["Actions"]
            .find(
                {"actor": self._robot_name, "command": {"$in": list(ACTION_KINDS)}},
                {"command": 1, "option": 1, "status": 1, "inserted": 1},
            )
            .sort("_id", DESCENDING)
            .limit(ACTION_SCAN_LIMIT)
        )
        groups = {kind: [] for kind in ACTION_KINDS}
        goal = None
        for doc in docs:
            option = doc.get("option") or {}
            status = doc.get("status", "")
            if (goal is None and doc["command"] == "navigation" and status in ("waiting", "is_playing")
                    and isinstance(option.get("navigation"), list)):
                x, y = option["navigation"][:2]
                goal = {"x": x, "y": y, "name": self.location_name(x, y)}
            items = groups[doc["command"]]
            if len(items) < self._action_count:
                items.append({
                    "id": str(doc["_id"]),
                    "text": describe_action(doc["command"], option, self.location_name),
                    "status": status,
                    "time": utc_to_local_text(doc.get("inserted")),
                })
        kinds = [{"kind": kind, "label": label, "items": groups[kind]} for kind, label in ACTION_KINDS.items()]
        return kinds, goal

    # ---- シナリオ ----
    @ttl_cache(STATE_TTL)
    def _current_state(self):
        return self._db["current_state"].find_one() or {}

    def scenario(self, history_count):
        """実行中のシナリオ (current_state) と最近のシナリオ履歴"""
        state = self._current_state()
        scenario = _as_dict(state.get("scenario"))
        interrupt = _as_dict(state.get("interrupt"))
        processing = _as_dict(state.get("processing"))
        event = _as_dict(state.get("event"))
        waiting = state.get("waiting")
        wait_supported = isinstance(waiting, list)
        if wait_supported:
            now = datetime.now(timezone.utc)
            waits = [describe_wait(w, now) for w in waiting]
        elif processing.get("is_asr_waiting"):
            # RISM が待ち状態を出力していない (修正前). 分かる範囲だけ表示する
            waits = [describe_wait({"kind": "wait_for"}, None)]
        else:
            waits = []
        interrupted = bool(interrupt.get("is_interrupted"))
        current = {
            "name": scenario.get("name") or state.get("current_scenario_name", ""),
            "status": scenario.get("status", ""),
            "event_index": event.get("index", state.get("current_event_index")),
            "event_type": event.get("type", ""),
            "interrupted": interrupted,
            "subscenario": interrupt.get("subscenario_name", ""),
            "processing": [label for key, label in PROCESSING_FLAGS.items() if processing.get(key)],
            "updated": utc_to_local_text(state.get("last_updated")),
            "waiting": waits,
            "wait_supported": wait_supported,
            "last_wait": describe_last_wait(state.get("last_wait")),
        }
        return {"current": current, "history": self._history(history_count, interrupted)}

    @ttl_cache(HISTORY_TTL)
    def _history(self, count, interrupted):
        history = []
        main_running_found = False
        for doc in (
            self._db["scenario_history"]
            .find({}, {"scenario_name": 1, "is_interruption": 1, "start_timestamp": 1,
                       "end_timestamp": 1, "exit_status": 1})
            .sort("_id", DESCENDING)
            .limit(count)
        ):
            end = doc.get("end_timestamp")
            is_interruption = bool(doc.get("is_interruption"))
            # 終了記録のないシナリオのうち最新のものだけを実行中とみなす
            # (割り込みは, 今まさに割り込み中で, いちばん新しい記録のときだけ)
            if is_interruption:
                running = end is None and interrupted and not history
            else:
                running = end is None and not main_running_found
                main_running_found = main_running_found or end is None
            history.append({
                "id": str(doc["_id"]),
                "name": doc.get("scenario_name", ""),
                "interruption": is_interruption,
                # scenario_history の時刻はローカル時刻で保存されている
                "start": local_text(doc.get("start_timestamp")),
                "end": local_text(end),
                "running": running,
                "exit_code": _exit_code(doc),
            })
        return history

    # ---- シナリオのタイムライン ----
    @ttl_cache(TIMELINE_TTL)
    def timeline(self, minutes):
        """
        直近 minutes 分のシナリオの遷移. 割り込みは深さ (depth) で段を分ける.
        RISM が parent_history_id / depth を記録していればそれを使い, なければ時間の包含関係から推定する
        """
        now = datetime.now()  # scenario_history の時刻はローカル時刻で保存されている
        window_start = now - timedelta(minutes=minutes)
        docs = self._timeline_docs(window_start)
        interrupted_now = bool(_as_dict(self._current_state().get("interrupt")).get("is_interrupted"))

        # 終了の記録がないもの: メインは次のメインが始まるまで, 割り込みは次のシナリオが始まるまでとみなす.
        # 後に何もなければ現在も実行中 (割り込みは, 今まさに割り込み中のときだけ)
        next_main = next_any = None
        ends = [None] * len(docs)
        for i in range(len(docs) - 1, -1, -1):
            doc = docs[i]
            end, open_end = doc.get("end_timestamp"), False
            if not isinstance(end, datetime):
                following = next_any if doc.get("is_interruption") else next_main
                if following is not None:
                    end = following
                else:
                    end = now
                    open_end = not doc.get("is_interruption") or (interrupted_now and next_any is None)
            ends[i] = (max(end, doc["start_timestamp"]), open_end)
            next_any = doc["start_timestamp"]
            if not doc.get("is_interruption"):
                next_main = doc["start_timestamp"]

        items = [
            {
                "id": str(doc["_id"]),
                "scenario_id": str(doc.get("scenario_id") or ""),
                "name": doc.get("scenario_name", ""),
                "interruption": bool(doc.get("is_interruption")),
                "start": doc["start_timestamp"],
                "end": end,
                "open": open_end,
                "exit_code": _exit_code(doc),
                "parent": doc.get("parent_history_id"),
                "depth": doc.get("depth"),
            }
            for doc, (end, open_end) in zip(docs, ends)
        ]
        self._infer_nesting(items)

        def ms(t):
            return int(t.timestamp() * 1000)

        return {
            "now": ms(now),
            "start": ms(window_start),
            "items": [
                {**item, "start": ms(item["start"]), "end": ms(item["end"]),
                 "start_text": item["start"].strftime(TIME_FORMAT),
                 "end_text": "" if item["open"] else item["end"].strftime(TIME_FORMAT)}
                for item in items if item["end"] >= window_start
            ],
        }

    def _timeline_docs(self, window_start):
        """表示範囲の直前に始まったメインシナリオ以降の履歴 (開始時刻順)"""
        fields = {"scenario_id": 1, "scenario_name": 1, "is_interruption": 1, "start_timestamp": 1,
                  "end_timestamp": 1, "exit_status": 1, "parent_history_id": 1, "depth": 1}
        since = ObjectId.from_datetime(window_start.astimezone(timezone.utc))
        history = self._db["scenario_history"]
        previous_main = history.find_one(
            {"_id": {"$lt": since}, "is_interruption": {"$ne": True}}, {"_id": 1}, sort=[("_id", DESCENDING)])
        if previous_main is not None:
            since = previous_main["_id"]
        docs = list(history.find({"_id": {"$gte": since}}, fields).sort("_id", ASCENDING).limit(TIMELINE_MAX_DOCS))
        docs = [d for d in docs if isinstance(d.get("start_timestamp"), datetime)]
        docs.sort(key=lambda d: d["start_timestamp"])
        return docs

    @staticmethod
    def _infer_nesting(items):
        """割り込みの深さと親を, 記録がなければ時間の包含関係から決める (開始時刻順の items を書き換える)"""
        ids = {item["id"] for item in items}
        stack = []  # 今開いているシナリオ (外側から)
        for item in items:
            while stack and stack[-1]["end"] <= item["start"]:
                stack.pop()
            if item["depth"] is None:
                item["depth"] = (stack[-1]["depth"] + 1 if stack else 1) if item["interruption"] else 0
            if item["parent"] is None and item["interruption"] and stack:
                item["parent"] = stack[-1]["id"]
            if item["parent"] not in ids:
                item["parent"] = None
            stack = stack + [item] if item["interruption"] else [item]

    # ---- 地図 ----
    def map_image(self):
        """地図 (map + 進入禁止領域 keepout) を PNG にし, 表示用の座標情報と一緒に返す. 初回だけ作る"""
        if self._map is None:
            locations = self.locations()  # _load_lock の中で読まないよう先に読む
            with self._load_lock:
                if self._map is None:
                    self._map = self._render_map(locations)
        return self._map

    def _render_map(self, locations):
        maps = {doc["name"]: doc for doc in self._db["maps"].find({"name": {"$in": ["map", "keepout"]}})}
        base = maps.get("map")
        if base is None:
            return None
        info = base["info"]
        width, height, resolution = info["width"], info["height"], info["resolution"]
        origin_x = info["origin"]["position"]["x"]
        origin_y = info["origin"]["position"]["y"]
        # ROS の地図は下の行から並ぶので上下反転して画像にする
        grid = np.asarray(base["data"], dtype=np.int16).reshape(height, width)[::-1]
        keepout = maps.get("keepout")
        if keepout is not None and keepout["info"]["width"] == width and keepout["info"]["height"] == height:
            allowed = np.asarray(keepout["data"], dtype=np.int16).reshape(height, width)[::-1] <= 50
        else:
            allowed = grid == 0
        image = np.full((height, width, 3), 235, np.uint8)  # 通行できない領域: 薄い灰色
        image[allowed & (grid == 0)] = (255, 255, 255)  # 通行できる領域: 白
        image[grid > 50] = (90, 90, 90)  # 障害物: 濃い灰色

        if self._map_region is not None:  # 設定された範囲を切り出す
            region = self._map_region
            rows = [height - (region["y_max"] - origin_y) / resolution, height - (region["y_min"] - origin_y) / resolution]
            cols = [(region["x_min"] - origin_x) / resolution, (region["x_max"] - origin_x) / resolution]
            top, bottom = max(int(rows[0]), 0), min(int(np.ceil(rows[1])), height)
            left, right = max(int(cols[0]), 0), min(int(np.ceil(cols[1])), width)
        else:
            top, bottom, left, right = self._auto_crop(allowed, locations, height, width, origin_x, origin_y, resolution)
        image = image[top:bottom, left:right]
        scale = max(1, MAP_MIN_WIDTH // max(right - left, 1))
        if scale > 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        ok, png = cv2.imencode(".png", image)
        if not ok:
            return None
        png = png.tobytes()
        return {
            "png": png,
            "info": {
                # 地図の画像が変わったらブラウザのキャッシュを使わないよう, URL に付ける
                "version": format(zlib.crc32(png), "08x"),
                "width": (right - left) * scale,
                "height": (bottom - top) * scale,
                "resolution": resolution / scale,  # 画像の1画素あたりの長さ (m)
                # 画像左上の画素に対応する世界座標
                "left_x": origin_x + left * resolution,
                "top_y": origin_y + (height - top) * resolution,
            },
        }

    @staticmethod
    def _auto_crop(allowed, locations, height, width, origin_x, origin_y, resolution):
        """通行できる領域と登録された場所が収まる範囲 (top, bottom, left, right)"""
        rows = list(np.flatnonzero(allowed.any(axis=1))[[0, -1]]) if allowed.any() else []
        cols = list(np.flatnonzero(allowed.any(axis=0))[[0, -1]]) if allowed.any() else []
        for loc in locations:
            cols.append(int((loc["x"] - origin_x) / resolution))
            rows.append(int(height - (loc["y"] - origin_y) / resolution))
        if rows:
            top, bottom = max(int(min(rows)) - MAP_MARGIN, 0), min(int(max(rows)) + MAP_MARGIN + 1, height)
            left, right = max(int(min(cols)) - MAP_MARGIN, 0), min(int(max(cols)) + MAP_MARGIN + 1, width)
        else:
            top, bottom, left, right = 0, height, 0, width
        return top, bottom, left, right


def describe_event(event, location_name):
    """シナリオのイベント1件を短い文字列にする"""
    event_type = event.get("type", "action")
    if event_type == "action":
        parts = []
        speak = _as_dict(event.get("speak"))
        if speak:
            option = _as_dict(speak.get("option"))
            if speak.get("type") == "generate":
                prompt = option.get("prompt")
                parts.append(f"発話（LLMで生成{'：' + prompt if prompt else ''}）")
            else:
                parts.append(f"「{option.get('text', '')}」")
        for command in ("gesture", "eye", "navigation"):
            option = _as_dict(_as_dict(event.get(command)).get("option"))
            if not option:
                continue
            if command == "gesture" and "command" in option:
                option = {**option, "gesture": option["command"]}
            parts.append(describe_action(command, option, location_name))
        return "　".join(parts) or "動作"
    if event_type in ("wait_for", "if", "until"):
        timeout = event.get("loop_timeout" if event_type == "until" else "timeout")
        condition = describe_condition(event.get("condition"))
        return f"{event_type}：{condition}" + (f"（{timeout}秒まで）" if timeout is not None else "")
    if event_type == "repeat":
        return f"repeat：{event.get('times', 1)}回（{len(event.get('subevents') or [])}件のイベント）"
    return event_type


class ScenarioCatalog:
    """RISM のシナリオ定義 (demo_configs.scenarios / interruption_subscenarios) の読み出し"""

    def __init__(self, host, port, db_name, location_name):
        self._db = MongoClient(host, port, serverSelectionTimeoutMS=3000)[db_name]
        self._location_name = location_name
        self._cache = {}
        self._cache_lock = threading.Lock()

    @ttl_cache(DEFINITION_TTL)
    def definition(self, scenario_id, interruption):
        """シナリオの定義の要約. 見つからなければ None"""
        try:
            key = ObjectId(scenario_id)
        except Exception:
            return None
        collections = ["interruption_subscenarios", "scenarios"]
        if not interruption:
            collections.reverse()
        for name in collections:
            doc = self._db[name].find_one({"_id": key})
            if doc is not None:
                break
        else:
            return None
        events = doc.get("events") or []
        counts = {}
        for event in events:
            event_type = event.get("type", "action")
            counts[event_type] = counts.get(event_type, 0) + 1
        return {
            "name": doc.get("name", ""),
            "kind": "割り込み" if name == "interruption_subscenarios" else "メイン",
            "description": doc.get("description", ""),
            "priority": doc.get("priority"),
            "condition": describe_condition(_as_dict(doc.get("condition"))),
            "returns": doc.get("return"),
            "force_interrupt": doc.get("force_interrupt"),
            "important": doc.get("important"),
            "status": doc.get("status", ""),
            "event_count": len(events),
            "event_types": counts,
            "events": [describe_event(e, self._location_name) for e in events[:DEFINITION_EVENT_COUNT]],
        }
