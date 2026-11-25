# -*- coding: utf-8 -*-
"""tracking / physical_topic / cyber_topic への登録 (db_management の register_* ノードが使う).

tracking (1 物体 1 ドキュメント, register_db_recog_node が書く)
  - tracked: instance_id ごとに upsert．first_seen / last_seen / life / min_distance
  - pose / face / attributes / hand_state / hand_waving / looking_at / wheelchair / noticed:
    最新の値で上書きする (同じ状態が続いた回数を life に持つ)
  - last_seen から lost_timeout 経った物体は tracking_archive に移す
    (lost_grace 以内に同じ instance_id が戻れば，発行済みフラグ等を引き継ぐ)

physical_topic (イベント, priority が寿命 [s]: modify_priority_node が毎秒 1 減らす)
  人物ごとに状態が変わったときだけ登録する．発行済みかどうかは tracking の
  emitted.<event> で管理する (_emit_once / _withdraw)．
  - 追跡中 1 回: person_found, person_in_range, person_appear, face_detected, wheelchair
  - 状態の間 1 件 (終わったら削除): person_noticed, raising_hand, waving_hand,
    person_too_near
  - 立ち去った: person_disappear (_exit_reason)
      見失ったときの様子で立ち去ったと分かる (画像の左右の端で消えた / 離れていく途中 /
      遠い) なら exit_check_sec 後にすぐ出す．そうでなければ (画面の中で一瞬見失った
      だけかもしれない) lost_grace 経っても戻らないときに出す．戻ってきたら取り消す
  - 人数・注視 (check_events, 0.5 s ごと): many_people, no_people,
    looking, long_looking, many_looking
  - asr / asr_from_outside, qr_code / qr_code_detect_only (register_db_asr / qrcode)
cyber_topic: weather, environment
"""
import datetime
import json

import numpy as np
from pyindy.mongo import DBManager
from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.errors import ConnectionFailure

from .mongo_utils import load_config
from .recognition_available_region_checker import RecognitionAvailableRegionChecker

# 人物イベントの既定値 (register_db_recog_node のパラメータで変えられる)
DEFAULT_OPTIONS = {
    "lost_grace_sec": 15.0,  # 見失ってからこの時間以内に戻れば同じ人として扱う [s]
    "too_near_distance": 0.5,  # person_too_near [m]
    "too_near_release_distance": 0.7,  # これより離れたら person_too_near を取り消す [m]
    "many_people_threshold": 3,  # この人数を超えたら many_people
    "looking_sec": 0.2,  # looking: ロボット (target) を見続けている時間 [s]
    "long_looking_sec": 1.0,
    "many_looking_sec": 1.0,
    "many_looking_num_person": 5,
    "attribute_smoothing": 0.3,  # 属性 confidence の指数平滑の重み (新しい値)
    # person_disappear をすぐ出す判定 (見失ってから exit_check_sec 後)
    "exit_check_sec": 1.0,  # [s]
    "image_width": 1280,  # tracked の location (bbox) の画像の幅 [px]
    "edge_margin_px": 40,  # bbox がこの幅以内で画像の左右の端にかかっていたら「画面の外へ出た」
    "away_speed": 0.3,  # この速さ [m/s] 以上で離れていく途中なら「立ち去った」
    "far_distance": 6.0,  # これより遠くで見失ったら「認識できる範囲の外へ出た」 [m]
}

# 人物イベントの contents に入れない tracking のフィールド (内部用・大きいもの)
_EVENT_EXCLUDE = ("_id", "emitted", "pose", "pose_sensor", "pose_global")

# 人物ごとのイベント (見失ったら physical から削除する)
# 追跡中 1 回: lost_grace 以内に戻った人には出し直さない
ONCE_EVENTS = ("person_found", "person_in_range", "person_appear", "face_detected", "wheelchair")
# 状態の間 1 件: 状態が終わったら削除し，また始まったら出す
STATE_EVENTS = ("person_too_near", "person_noticed", "raising_hand", "waving_hand")
PERSON_EVENTS = ONCE_EVENTS + STATE_EVENTS

class TopicDBManager:
    def __init__(self, uri, port, dbname, options=None):
        self.client = MongoClient(uri, port)
        self.options = {**DEFAULT_OPTIONS, **(options or {})}
        self.prev_num_person = None  # check_events: 前回の人数

        self.physical_db = DBManager(uri, port, dbname, "physical_topic")
        self.cyber_db = DBManager(uri, port, dbname, "cyber_topic")

        self.tracking_db = self.client["tBlackBoard"].tracking
        self.tracking_archive_db = self.client["tBlackBoard"].tracking_archive
        self.rel_db = self.client["tBlackBoard"].relations
        # ロボットの設定 (設定 DB 9100)
        # 未登録の場合でも落ちないように空 dict にする
        self.config = load_config()
        self.region_checker = RecognitionAvailableRegionChecker(self.config)

        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """クエリで使うフィールドにインデックスを張る (冪等，失敗しても起動は継続する)．"""
        tracking_indexes = [
            # update_objects/update_* で instance_id をキーに検索・更新する
            [("instance_id", ASCENDING)],
            # check_events (人数) / robot_looking
            [("class_id", ASCENDING)],
            # prune_lost_objects
            [("last_seen", ASCENDING)],
            # check_events (注視)
            [("looking_at.target", ASCENDING), ("looking_at.since", ASCENDING)],
        ]
        archive_indexes = [
            # 戻ってきた人の引き継ぎ / person_disappear
            [("instance_id", ASCENDING), ("last_seen", ASCENDING)],
            [("last_seen", ASCENDING)],
        ]
        physical_indexes = [
            # 重複チェック・削除 ({"event", "contents.instance_id"}) と event 単体の検索
            [("event", ASCENDING), ("contents.instance_id", ASCENDING)],
        ]

        try:
            # tracking への insert は update_objects のみ (find_one -> insert_one，
            # 重複時は update にフォールバック) なので instance_id は一意にできる．
            # 既存データに重複がある等で失敗した場合は非 unique で張る．
            try:
                self.tracking_db.create_index(
                    [("instance_id", ASCENDING)], unique=True
                )
                tracking_indexes = tracking_indexes[1:]
            except ConnectionFailure:
                raise
            except Exception as e:
                print(
                    f"[TopicDBManager] unique index on tracking.instance_id "
                    f"was not created ({e}); falling back to non-unique index",
                    flush=True,
                )

            for keys in tracking_indexes:
                self._create_index(self.tracking_db, keys)
            for keys in archive_indexes:
                self._create_index(self.tracking_archive_db, keys)
            for keys in physical_indexes:
                self._create_index(self.physical_db.db, keys)
        except ConnectionFailure as e:
            print(f"[TopicDBManager] failed to create indexes: {e}", flush=True)

    @staticmethod
    def _create_index(collection, keys) -> None:
        try:
            collection.create_index(keys)
        except ConnectionFailure:
            raise
        except Exception as e:
            print(
                f"[TopicDBManager] failed to create index {keys} on "
                f"{getattr(collection, 'name', collection)}: {e}",
                flush=True,
            )

    # ------------------------------------------------------------------
    # tracking へのまとめ書き
    #
    # 認識結果のトピックは 1 メッセージに複数人分が入り，トピックごとに ~10 Hz で
    # 届く．1 人ごとに find_one / update_one を往復させず，メッセージごとに
    # 1 回の find ($in) と 1 回の bulk_write にまとめる．
    # ------------------------------------------------------------------
    def _fetch(self, ids, fields):
        """instance_id -> tracking ドキュメント (fields のみ)．無いものは含まない．"""
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        projection = dict.fromkeys(["instance_id", *fields], 1)
        return {
            d["instance_id"]: d
            for d in self.tracking_db.find({"instance_id": {"$in": ids}}, projection)
        }

    def _bulk(self, ops):
        if ops:
            self.tracking_db.bulk_write(ops, ordered=False)

    @staticmethod
    def _set(instance_id, fields, upsert=False):
        return UpdateOne({"instance_id": instance_id}, {"$set": fields}, upsert=upsert)

    @staticmethod
    def _emitted(doc, event):
        return bool(((doc or {}).get("emitted") or {}).get(event))

    # ------------------------------------------------------------------
    # 人物イベントの発行状態管理
    #
    # physical_topic のイベントは modify_priority_node の decrease_priority で
    # 優先度が 0 未満になると削除されるため，「physical_topic にイベントが残って
    # いるか」で登録済みかどうかを判定すると，同じ人物が映り続けている間に
    # 同じイベントが再登録されてしまう．そこで tracking ドキュメントの
    # emitted.<event> フラグで発行状態を管理する．tracking ドキュメントは
    # 人物を見失うと archive に移されて削除されるため，フラグは instance_id の
    # 生存期間ごとに自然にリセットされる．
    # ------------------------------------------------------------------
    def _mark_emitted(self, instance_id, event: str) -> bool:
        """emitted.<event> を False/未設定 -> True に原子的に変更する．

        Returns:
            bool: このプロセスがフラグを立てた (= イベントを発行すべき) とき True．
                  既に発行済み，または tracking ドキュメントが無いときは False．
        """
        ret = self.tracking_db.update_one(
            {"instance_id": instance_id, f"emitted.{event}": {"$ne": True}},
            {"$set": {f"emitted.{event}": True}},
        )
        return ret.modified_count > 0

    def _unmark_emitted(self, instance_id, event: str) -> None:
        self.tracking_db.update_one(
            {"instance_id": instance_id}, {"$set": {f"emitted.{event}": False}}
        )

    def _withdraw(self, instance_id, event: str) -> None:
        """状態が終わった: フラグを下ろしてイベントを削除する (次にまた出せる)．"""
        self._unmark_emitted(instance_id, event)
        self.physical_db.delete({"event": event, "contents.instance_id": instance_id})

    @staticmethod
    def event_contents(doc: dict) -> dict:
        """tracking ドキュメントから人物イベントの contents を作る．"""
        return {k: v for k, v in doc.items() if k not in _EVENT_EXCLUDE}

    def _emit_once(self, instance_id, event: str, contents: dict, priority: int) -> bool:
        """instance_id ごとに1回だけ physical_topic に event を登録する．"""
        if not self._mark_emitted(instance_id, event):
            return False
        query = {"event": event, "contents.instance_id": instance_id}
        try:
            # フラグ導入前に登録されたイベントが残っている場合は二重登録しない
            if self.physical_db.db.find_one(query) is not None:
                return False
            self.physical_db.insert(event, contents, priority=priority)
        except Exception:
            # 登録に失敗した場合は次回再試行できるようにフラグを戻す
            self._unmark_emitted(instance_id, event)
            raise
        return True

    # --- ASR ---------------------------------------------------------------
    # 音声認識結果はソースごとに形式が違うので，共通の形に正規化してから
    # insert_asr で physical_topic に登録する．共通フィールド:
    #   source, text, confidence, instance_id, angle (正面からの角度 [deg]), turn_end
    # 各ソース固有のフィールドもそのまま残す．

    @staticmethod
    def normalize_kad_asr(d):
        """kad/asr の asr/meta_data (JSON を読んだ dict) を正規化する．

        x: 左右，y: 前方 (human tracker の座標系)．
        """
        q = dict(d)
        q["source"] = "kad"
        q["confidence"] = float(q["scores"])
        q["text"] = "".join(q["words"])
        q["angle"] = float(np.abs(np.rad2deg(np.arctan2(q["x"], q["y"]))))
        return q

    @staticmethod
    def normalize_ssl_asr(d):
        """ssl_asr の recog/ssl/asr/analyzed (JSON を読んだ dict) を正規化する．

        location: [x 前方, y 左, z] (location_frame，通常はロボットの base frame)．
        morph (あれば): ssl_asr morph_node の形態素解析結果．そのまま登録する．
        """
        q = dict(d)
        q["source"] = "ssl"
        q["text"] = q.get("text", "").strip()
        q["confidence"] = float(q.get("confidence", 0.0))
        q["instance_id"] = int(q.get("person_id", -1))
        loc = q.get("location")
        if loc is not None and len(loc) >= 2:
            angle = np.rad2deg(np.arctan2(loc[1], loc[0]))
        else:
            angle = np.rad2deg(q.get("azimuth", 0.0))
        q["angle"] = float(np.abs(angle))
        return q

    def insert_asr(self, q, vap_status=False, priority=100):
        """正規化済みの ASR 結果を登録する (asr_target_angle の外なら asr_from_outside)."""
        if q["text"] == "":
            return
        q["turn_end"] = vap_status
        if (
            "asr_target_angle" in self.config
            and q["angle"] > self.config["asr_target_angle"]
        ):
            self.physical_db.insert("asr_from_outside", q, priority=priority)
        else:
            self.physical_db.insert("asr", q, priority=priority)

    def update_asr(self, asr, vap_status=False, priority=100):
        """kad/asr (asr/meta_data) の結果を登録する．"""
        q = self.normalize_kad_asr(json.loads(asr.data))
        self.insert_asr(q, vap_status=vap_status, priority=priority)

    def update_ssl_asr(self, asr, vap_status=False, priority=100):
        """ssl_asr (recog/ssl/asr/analyzed) の結果を登録する．"""
        q = self.normalize_ssl_asr(json.loads(asr.data))
        self.insert_asr(q, vap_status=vap_status, priority=priority)

    def insert_qrcode(self, texts, priority=200):
        for text in texts:
            if len(text) == 0:
                if (
                    self.physical_db.db.find_one({"event": "qr_code_detect_only"})
                    is None
                ):
                    insert_query = {"text": text}
                    self.physical_db.insert(
                        "qr_code_detect_only", insert_query, priority=priority
                    )
            else:
                query = {"event": "qr_code", "contents.text": text}
                if self.physical_db.db.find_one(query) is None:
                    insert_query = {"text": text}
                    self.physical_db.insert("qr_code", insert_query, priority=priority)

    def insert_weather(self, weather, priority=200):
        self.cyber_db.insert("weather", weather, priority=priority)

    def insert_environment(self, environment, priority=200):
        self.cyber_db.insert("environment", environment, priority=priority)

    # ------------------------------------------------------------------
    # tracked: tracking への登録と，人物の位置・距離によるイベント
    # ------------------------------------------------------------------
    def update_objects(self, tracklet, distance_threshold, in_range_distance=6.0):
        objects = list(tracklet.objects)
        if not objects:
            return
        now = datetime.datetime.now()
        fields = ["life", "emitted", "first_seen", "min_distance", "last_distance",
                  "last_seen", "distance_rate"]
        known = self._fetch([t.instance_id for t in objects], fields)
        # 新しい instance_id: lost_grace 以内に見失った同じ人なら状態を引き継ぐ
        returned = self._restore_returned(
            [t.instance_id for t in objects if t.instance_id not in known], now
        )
        ops = []
        persons = []
        for t in objects:
            q = {}
            q["instance_id"] = t.instance_id
            q["name"] = t.name
            q["class_id"] = t.class_id
            q["confidence"] = t.confidence
            q["location"] = t.location.tolist()
            q["location_sensor"] = t.location_sensor.tolist()
            q["location_global"] = t.location_global.tolist()
            q["last_update"] = now
            q["last_seen"] = now  # 見失い判定 (prune_lost_objects) に使う
            prev = known.get(t.instance_id) or returned.get(t.instance_id)
            q["life"] = 0 if prev is None else prev.get("life", 0) + 1
            q["first_seen"] = (prev or {}).get("first_seen") or now
            distance = self._valid_distance(q["location_sensor"])
            if distance is not None:
                q["distance"] = distance
                last_min = (prev or {}).get("min_distance")
                q["min_distance"] = distance if last_min is None else min(last_min, distance)
                q["last_distance"] = distance  # tracked から (pose の distance とは別)
                rate = self._distance_rate(prev, distance, now)
                if rate is not None:
                    q["distance_rate"] = rate
            if t.instance_id in returned:
                # 追跡中 1 回のイベントだけ引き継ぐ (挨拶し直さない)．状態のイベントは出し直す
                emitted = returned[t.instance_id].get("emitted") or {}
                q["emitted"] = {k: v for k, v in emitted.items() if k in ONCE_EVENTS}
                prev = {**prev, "emitted": q["emitted"]}
                if emitted.get("person_disappear"):
                    # 立ち去ったと判定したが戻ってきた: 取り消す
                    self.physical_db.delete(
                        {"event": "person_disappear", "contents.instance_id": t.instance_id}
                    )
            ops.append(self._set(t.instance_id, q, upsert=True))
            if q["class_id"] == 0:
                persons.append((q, prev))
        self._bulk(ops)

        # 人物イベント: 発行済み (emitted) のものは問い合わせずに飛ばす
        for q, prev in persons:
            if self._emitted(prev, "person_disappear"):
                # 立ち去ったと判定したが戻ってきた: 取り消す
                self._withdraw(q["instance_id"], "person_disappear")
            if not self._emitted(prev, "person_found"):
                self.register_person_found(q)
            if not self._emitted(prev, "person_in_range"):
                self.register_person_in_range(q, in_range_distance)
            if not self._emitted(prev, "person_appear"):
                self.register_person_appear(q, distance_threshold)
            self.register_person_too_near(q, self._emitted(prev, "person_too_near"))

    @staticmethod
    def _distance_rate(prev, distance, now, alpha=0.3):
        """距離の変化の速さ [m/s] (正: 離れていく)．指数平滑．"""
        if not prev or prev.get("last_distance") is None or prev.get("last_seen") is None:
            return None
        dt = (now - prev["last_seen"]).total_seconds()
        if not 0.0 < dt <= 1.0:  # 間が空いたら前の値を使わない
            return None
        rate = (distance - prev["last_distance"]) / dt
        last = prev.get("distance_rate")
        return rate if last is None else (1 - alpha) * last + alpha * rate

    def _restore_returned(self, ids, now) -> dict:
        """lost_grace 以内に archive に移した同じ instance_id の状態 (instance_id -> doc)．"""
        if not ids:
            return {}
        since = now - datetime.timedelta(seconds=self.options["lost_grace_sec"])
        query = {
            "instance_id": {"$in": ids},
            "last_seen": {"$gte": since},
            "returned": {"$ne": True},
        }
        docs = {}
        for d in self.tracking_archive_db.find(query):
            cur = docs.get(d["instance_id"])
            if cur is None or d["last_seen"] > cur["last_seen"]:
                docs[d["instance_id"]] = d
        if docs:
            # 戻ってきたので person_disappear は出さない
            self.tracking_archive_db.update_many(query, {"$set": {"returned": True}})
        return docs

    def prune_lost_objects(self, timeout_sec: float) -> None:
        """last_seen から timeout_sec 経った物体を archive に移す．

        lost_grace 経っても戻らなかった人には person_disappear を出す．
        """
        now = datetime.datetime.now()
        self._register_person_exit(now)
        limit = now - datetime.timedelta(seconds=timeout_sec)
        self._delete_lost_objects({"last_seen": {"$lt": limit}})
        self._register_person_disappear(now)

    def _exit_reason(self, doc):
        """見失ったときの様子から立ち去ったと分かれば理由，分からなければ None．"""
        o = self.options
        loc = doc.get("location") or []
        if len(loc) == 4:
            if loc[0] <= o["edge_margin_px"]:
                return "out_of_view_left"
            if loc[0] + loc[2] >= o["image_width"] - o["edge_margin_px"]:
                return "out_of_view_right"
        rate = doc.get("distance_rate")
        if rate is not None and rate >= o["away_speed"]:
            return "walked_away"
        d = doc.get("last_distance")
        if d is not None and d >= o["far_distance"]:
            return "too_far"
        return None

    def _register_person_exit(self, now, priority: int = 50) -> None:
        """見失って exit_check_sec 経った人のうち，立ち去ったと分かる人に person_disappear．"""
        query = {
            "class_id": 0,
            "last_seen": {"$lt": now - datetime.timedelta(seconds=self.options["exit_check_sec"])},
            "emitted.person_disappear": {"$ne": True},
        }
        for d in self.tracking_db.find(query):
            reason = self._exit_reason(d)
            if reason is not None:
                q = self._disappear_contents(d, reason, now)
                self._emit_once(d["instance_id"], "person_disappear", q, priority)

    @staticmethod
    def _disappear_contents(d, reason, now):
        first_seen = d.get("first_seen") or d["last_seen"]
        return {
            "instance_id": d["instance_id"],
            # out_of_view_left / out_of_view_right / walked_away / too_far: 見失ってすぐ
            # lost: lost_grace 経っても戻らなかった
            "reason": reason,
            "lost_sec": (now - d["last_seen"]).total_seconds(),
            "first_seen": first_seen,
            "last_seen": d["last_seen"],
            "stay_sec": (d["last_seen"] - first_seen).total_seconds(),
            "min_distance": d.get("min_distance"),
            "last_distance": d.get("last_distance"),
            "location_sensor": d.get("location_sensor"),
            # 追跡中に出たイベント (挨拶した / 気づいた など)
            "events": sorted(
                k for k, v in (d.get("emitted") or {}).items() if v and k != "person_disappear"
            ),
            "attributes": d.get("attributes_smoothed", {}),
        }

    def _delete_lost_objects(self, query: dict) -> None:
        for t in self.tracking_db.find(query):
            self.tracking_archive_db.insert_one(t)
            self.clear_person_events(t)
        self.tracking_db.delete_many(query)

    def _register_person_disappear(self, now, priority: int = 50) -> None:
        grace = datetime.timedelta(seconds=self.options["lost_grace_sec"])
        query = {
            "class_id": 0,
            # 古い archive (この機能より前のもの) には出さない
            "last_seen": {"$lt": now - grace, "$gte": now - grace - datetime.timedelta(minutes=1)},
            "returned": {"$ne": True},
            "departed": {"$ne": True},
            # 見失ってすぐ立ち去ったと判定したもの (_register_person_exit) は除く
            "emitted.person_disappear": {"$ne": True},
        }
        for d in self.tracking_archive_db.find(query):
            ret = self.tracking_archive_db.update_one(
                {"_id": d["_id"], "departed": {"$ne": True}}, {"$set": {"departed": True}}
            )
            if ret.modified_count == 0:
                continue
            q = self._disappear_contents(d, "lost", now)
            self.physical_db.insert("person_disappear", q, priority=priority)

    @staticmethod
    def _valid_distance(location_sensor):
        """カメラからの水平距離 [m] (奥行きが無効なら None)．"""
        if len(location_sensor) < 3 or location_sensor[2] <= 0:
            return None
        return float(np.sqrt(location_sensor[0] ** 2 + location_sensor[2] ** 2))

    def register_person_found(self, o: dict, priority: int = 100) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，距離にかかわらず見つけたときに person_found を登録する
        # distance: depth が無効な場合は None
        # location_sensor: 頭のカメラ座標系の位置 (RISM が人の方を向くのに使う．z <= 0 は無効)
        q = {
            "instance_id": o["instance_id"],
            "distance": self._valid_distance(o["location_sensor"]),
            "location_sensor": o["location_sensor"],
        }
        self._emit_once(o["instance_id"], "person_found", q, priority)

    def register_person_appear(self, o: dict, distance_threshold: float) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，距離しきい値内に入ったときに person_appear を登録する
        d = self._calc_distance(o["location_sensor"])
        if d > distance_threshold or d < 0.1:
            return

        q = self.event_contents(o)
        q["distance"] = float(d)
        # その時点で分かっている属性 (服装など．まだ無ければ空)
        attributes = self.tracking_db.find_one(
            {"instance_id": o["instance_id"]}, {"attributes_smoothed": 1}
        )
        q["attributes"] = (attributes or {}).get("attributes_smoothed", {})
        self._emit_once(o["instance_id"], "person_appear", q, 100)

    def register_person_in_range(self, o: dict, in_range_distance: float) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，in_range_distance 以内に初めて入ったときに登録する
        # person_found と違い，遠くで見つけた人が近づいてきたときにも出る
        d = self._valid_distance(o["location_sensor"])
        if d is None or d > in_range_distance or d < 0.1:  # 奥行き無効: 次のフレームで判定
            return
        q = {
            "instance_id": o["instance_id"],
            "distance": d,
            "location_sensor": o["location_sensor"],
        }
        self._emit_once(o["instance_id"], "person_in_range", q, 100)

    def register_person_too_near(self, o: dict, emitted: bool, priority: int = 100) -> None:
        """too_near_distance より近づいたら 1 件，too_near_release_distance より離れたら取り消す．"""
        d = self._valid_distance(o["location_sensor"])
        if d is None or d < 0.1:
            return
        if not emitted and d < self.options["too_near_distance"]:
            q = {
                "instance_id": o["instance_id"],
                "distance": d,
                "location_sensor": o["location_sensor"],
            }
            self._emit_once(o["instance_id"], "person_too_near", q, priority)
        elif emitted and d > self.options["too_near_release_distance"]:
            self._withdraw(o["instance_id"], "person_too_near")

    def clear_person_events(self, o: dict) -> None:
        # 見失った人物の人物イベントを削除する
        for event in PERSON_EVENTS:
            q = {"event": event, "contents.instance_id": o["instance_id"]}
            self.physical_db.delete(q)

    # ------------------------------------------------------------------
    # pose / face / attributes
    # ------------------------------------------------------------------
    def update_poses(self, poses):
        ops = []
        now = datetime.datetime.now()
        for t in poses.persons:
            if t.instance_id < 0:
                continue
            q = {}
            q["last_update"] = now
            q["pose"] = {}
            q["pose"]["dim"] = t.pose.dim
            q["pose"]["keypoints"] = t.pose.keypoints.tolist()
            q["pose"]["confidences"] = t.pose.confidences.tolist()
            q["pose_sensor"] = {}
            q["pose_sensor"]["dim"] = t.pose_sensor.dim
            q["pose_sensor"]["keypoints"] = t.pose_sensor.keypoints.tolist()
            q["pose_sensor"]["confidences"] = t.pose_sensor.confidences.tolist()
            q["face_location_sensor"] = q["pose_sensor"]["keypoints"][0:3]
            q["pose_global"] = {}
            q["pose_global"]["dim"] = t.pose_global.dim
            q["pose_global"]["keypoints"] = t.pose_global.keypoints.tolist()
            q["pose_global"]["confidences"] = t.pose_global.confidences.tolist()
            q["distance"] = float(self._calc_distance(t.body_location_sensor.tolist()))
            ops.append(self._set(t.instance_id, q))  # tracking に無ければ何もしない
        self._bulk(ops)

    def update_faces(self, faces, priority=100):
        ids = [t.instance_id for t in faces.persons if t.instance_id >= 0]
        known = self._fetch(ids, ["emitted"])
        ops = []
        for t in faces.persons:
            if t.instance_id not in known:
                continue
            q = {}
            q["instance_id"] = t.instance_id
            q["face_location"] = t.face_location.tolist()
            q["face_location_sensor"] = t.face_location_sensor.tolist()
            q["face_location_global"] = t.face_location_global.tolist()
            q["face_orientation"] = t.face_orientation.tolist()
            if len(q["face_location_sensor"]) == 3:
                q["distance"] = float(self._calc_distance(q["face_location_sensor"]))
            # 顔の位置・向きを tracking に残す (face_location_sensor は pose からの値より優先)
            face = {k: v for k, v in q.items() if k not in ("instance_id", "distance")}
            ops.append(self._set(t.instance_id, {"face": face}))
            # 同一人物につき1回だけ face_detected を登録する
            if not self._emitted(known[t.instance_id], "face_detected"):
                self._emit_once(t.instance_id, "face_detected", q, priority)
        self._bulk(ops)

    def update_attributes(self, attributes_msg, priority=50):
        """属性を tracking に書く．

        attributes / attribute_confidences: 最新のフレームの値
        attributes_smoothed: {属性名: confidence} の指数平滑 (フレームごとのぶれを抑える)
        """
        persons = [p for p in attributes_msg.persons if p.instance_id >= 0]
        known = self._fetch([p.instance_id for p in persons], ["attributes_smoothed"])
        alpha = self.options["attribute_smoothing"]
        ops = []
        for person in persons:
            if person.instance_id not in known:
                continue
            smoothed = dict(known[person.instance_id].get("attributes_smoothed") or {})
            for name, conf in zip(person.attributes, person.attribute_confidences):
                prev = smoothed.get(name)
                smoothed[name] = float(conf) if prev is None else (1 - alpha) * prev + alpha * float(conf)
            ops.append(
                self._set(
                    person.instance_id,
                    {
                        "attributes": list(person.attributes),
                        "attribute_confidences": list(person.attribute_confidences),
                        "attributes_smoothed": smoothed,
                    },
                )
            )
        self._bulk(ops)

    def _calc_distance(self, location):
        x = location[0]
        z = location[2]
        return np.sqrt(x**2 + z**2)

    # ------------------------------------------------------------------
    # 動作の状態 (action_recognition)．状態が変わったときにイベントを出す
    # ------------------------------------------------------------------
    @staticmethod
    def _life(prev, same):
        """同じ状態が続いた回数 (状態が変わったら 1 から)．"""
        return prev.get("life", 0) + 1 if prev is not None and same(prev) else 1

    def _in_region(self, doc) -> bool:
        """recognition_available_regions の中にいるか (未設定なら常に True)．"""
        location = doc.get("location_global")
        if location is None:
            return False
        return self.region_checker.is_in(location)[0]

    def _state_event(self, instance_id, event, active, emitted, priority):
        """active の間だけ event を 1 件保持する (認識可能領域の外では出さない)．"""
        if active and not emitted:
            doc = self.tracking_db.find_one({"instance_id": instance_id})
            if doc is not None and self._in_region(doc):
                self._emit_once(instance_id, event, self.event_contents(doc), priority)
        elif not active and emitted:
            self._withdraw(instance_id, event)

    def update_hand_state(self, pointings, priority=30):
        # TODO: update pointing target
        known = self._fetch(
            [t.instance_id for t in pointings.pointings], ["hand_state", "emitted"]
        )
        ops = []
        events = []
        for t in pointings.pointings:
            if t.instance_id not in known:
                continue
            prev = known[t.instance_id].get("hand_state")
            q = {
                "raising_right_hand": t.raising_right_hand,
                "raising_left_hand": t.raising_left_hand,
                "life": prev["life"] + 1 if prev else 0,
            }
            ops.append(self._set(t.instance_id, {"hand_state": q}))
            raising = bool(t.raising_right_hand or t.raising_left_hand)
            events.append((t.instance_id, raising, self._emitted(known[t.instance_id], "raising_hand")))
        self._bulk(ops)
        for instance_id, raising, emitted in events:
            self._state_event(instance_id, "raising_hand", raising, emitted, priority)

    def _update_states(self, msg, field, make_state, event=None):
        """{instance_id: 認識結果} の JSON を tracking の field に書く．

        make_state(結果, 前回の状態 or None) -> 新しい状態 (life 込み)
        event: (イベント名, 状態 -> active か, priority) 状態が変わったときに出す
        """
        results = {int(k): v for k, v in json.loads(msg.data).items()}
        known = self._fetch(results, [field, "emitted"])
        states = {i: make_state(r, known[i].get(field)) for i, r in results.items() if i in known}
        self._bulk([self._set(i, {field: s}) for i, s in states.items()])
        if event is None:
            return
        name, is_active, priority = event
        for i, s in states.items():
            emitted = self._emitted(known[i], name)
            if name == "wheelchair":
                # 追跡中 1 回 (座っていなくなっても取り消さない)
                if is_active(s) and not emitted:
                    self._state_event(i, name, True, False, priority)
            else:
                self._state_event(i, name, is_active(s), emitted, priority)

    def update_hand_waving(self, hand_wavings_msg, priority=100):
        def state(target_id, prev):
            waving = target_id == 1
            same = lambda p: p.get("hand_waving") == waving  # noqa: E731
            return {"hand_waving": waving, "life": self._life(prev, same)}

        event = ("waving_hand", lambda s: s["hand_waving"], priority)
        self._update_states(hand_wavings_msg, "hand_waving", state, event)

    def update_lookingat(self, lookingats_msg, priority=50):
        now = datetime.datetime.now()

        def state(target_id, prev):
            # since: この target を見始めた時刻 (check_events が秒で判定する)
            same = lambda p: p.get("target") == target_id and "since" in p  # noqa: E731
            life = self._life(prev, same)
            since = prev["since"] if life > 1 else now
            return {"target": target_id, "life": life, "since": since}

        self._update_states(lookingats_msg, "looking_at", state)

    def update_wheelchair(self, wheelchairs_msg, priority=100):
        def state(target_id, prev):
            sitting = target_id == 1
            same = lambda p: p.get("sitting") == sitting  # noqa: E731
            return {"sitting": sitting, "life": self._life(prev, same)}

        event = ("wheelchair", lambda s: s["sitting"], priority)
        self._update_states(wheelchairs_msg, "wheelchair", state, event)

    def update_noticed(self, noticed_msg, priority=100):
        noticed = {int(k): v for k, v in json.loads(noticed_msg.data).items()}
        known = self._fetch(noticed, ["noticed", "location_sensor", "emitted"])
        ops = []
        emit = []
        for instance_id, result in noticed.items():
            ret = known.get(instance_id)
            if ret is None:
                continue

            is_noticed = int(result.get("noticed", 0)) == 1
            state = dict(result)
            state["noticed"] = is_noticed
            same = lambda p: p.get("noticed") == is_noticed  # noqa: E731
            state["life"] = self._life(ret.get("noticed"), same)
            update = {"noticed": state}
            if not is_noticed:
                # 気づかなくなったら発行済みフラグを下ろし，次に気づいたときに再発行できるようにする
                update["emitted.person_noticed"] = False
            ops.append(self._set(instance_id, update))
            emit.append((instance_id, is_noticed, state, ret))
        self._bulk(ops)

        for instance_id, is_noticed, state, ret in emit:
            # ロボットに気づいている間だけ person_noticed を1件保持し，気づかなくなったら削除する．
            # 気づいている間に優先度の減衰でイベントが消えても，emitted.person_noticed が
            # 立っている限り再登録しない．
            if not is_noticed:
                query = {"event": "person_noticed", "contents.instance_id": instance_id}
                self.physical_db.delete(query)
                continue
            if self._emitted(ret, "person_noticed"):
                continue
            # 気づいたときの位置 (tracking の記録)．RISM はこれを優先して人の方を向く
            q = {
                "instance_id": instance_id,
                "noticed": state,
                "location_sensor": ret.get("location_sensor"),
            }
            self._emit_once(instance_id, "person_noticed", q, priority)

    # ------------------------------------------------------------------
    # 人数・注視 (複数人にまたがる判定．register_db_recog_node が 0.5 s ごとに呼ぶ)
    # ------------------------------------------------------------------
    def check_events(self, now=None):
        now = now or datetime.datetime.now()
        self._check_num_of_person()
        for target in (1, 2):
            self._check_looking(now, target)

    def _check_num_of_person(self):
        """人数が many_people_threshold を超えたとき / 0 になったときに 1 件．"""
        num = self.tracking_db.count_documents({"class_id": 0})
        prev = self.prev_num_person
        self.prev_num_person = num
        if prev == num:
            return
        threshold = self.options["many_people_threshold"]
        if num > threshold and (prev is None or prev <= threshold):
            self.physical_db.insert("many_people", {"num_people": num})
        elif num == 0:
            self.physical_db.insert("no_people", {"num_people": num})

    @staticmethod
    def looking_query(now, target, duration_sec):
        """target を duration_sec 以上見続けている人 (looking_at.since が十分前)．"""
        since = now - datetime.timedelta(seconds=duration_sec)
        return {"looking_at.target": target, "looking_at.since": {"$lte": since}}

    def _check_looking(self, now, target):
        o = self.options
        n = self.tracking_db.count_documents(self.looking_query(now, target, o["many_looking_sec"]))
        if n >= o["many_looking_num_person"]:
            self._put_target_event("many_looking", {"target": target, "num_person": n})
        for event, sec in (("looking", o["looking_sec"]), ("long_looking", o["long_looking_sec"])):
            doc = self.tracking_db.find_one(self.looking_query(now, target, sec))
            if doc is not None:
                duration = (now - doc["looking_at"]["since"]).total_seconds()
                self._put_target_event(event, {"target": target, "duration": duration})

    def _put_target_event(self, event, contents, priority=50):
        """target ごとに 1 件: 無ければ登録し，あれば contents を更新する．"""
        query = {"event": event, "contents.target": contents["target"]}
        if self.physical_db.db.find_one(query) is None:
            self.physical_db.insert(event, contents, priority=priority)
        else:
            self.physical_db.db.update_one(query, {"$set": {"contents": contents}})

    # ------------------------------------------------------------------
    # 優先度の減衰 (modify_priority_node)
    # ------------------------------------------------------------------
    def step_physical_db(self):
        self.physical_db.decrease_priority()

    def step_cyber_db(self):
        self.cyber_db.decrease_priority()
