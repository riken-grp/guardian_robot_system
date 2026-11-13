# -*- coding: utf-8 -*-
import datetime
import json

import numpy as np
from pyindy.mongo import DBManager
from pymongo import ASCENDING, MongoClient
from pymongo.errors import ConnectionFailure, DuplicateKeyError

from .mongo_utils import load_config

object_name_mapping = {}
object_name_mapping["shirt"] = "シャツ"
object_name_mapping["sweater"] = "セーター"
object_name_mapping["jacket"] = "ジャケット"
object_name_mapping["skirt"] = "スカート"
object_name_mapping["pants"] = "パンツ"
object_name_mapping["trausers"] = "ズボン"
object_name_mapping["shoe"] = "靴"
object_name_mapping["glass"] = "メガネ"
object_name_mapping["laptop"] = "パソコン"
object_name_mapping["bag"] = "かばん"
object_name_mapping["backpack"] = "リュック"
object_name_mapping["mug"] = "コップ"
object_name_mapping["cup"] = "コップ"
object_name_mapping["umbrella"] = "傘"
object_name_mapping["cellphone"] = "スマホ"


class TopicDBManager:
    def __init__(self, uri, port, dbname):
        self.client = MongoClient(uri, port)

        self.physical_db = DBManager(uri, port, dbname, "physical_topic")
        self.cyber_db = DBManager(uri, port, dbname, "cyber_topic")

        self.tracking_db = self.client["tBlackBoard"].tracking
        self.tracking_archive_db = self.client["tBlackBoard"].tracking_archive
        self.rel_db = self.client["tBlackBoard"].relations
        # ロボットの設定 (設定 DB 9100)
        # 未登録の場合でも落ちないように空 dict にする
        self.config = load_config()

        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """クエリで使うフィールドにインデックスを張る (冪等，失敗しても起動は継続する)．"""
        tracking_indexes = [
            # update_objects/update_* で instance_id をキーに検索・更新する
            [("instance_id", ASCENDING)],
            # check_num_of_person_node / robot_looking
            [("class_id", ASCENDING)],
            # prune_lost_objects
            [("last_seen", ASCENDING)],
            # check_looking_at_node
            [("looking_at.target", ASCENDING), ("looking_at.life", ASCENDING)],
            # check_waving_hand_node
            [("hand_waving.hand_waving", ASCENDING)],
            # check_arm_state_node ($or の各条件 / 両手 False の AND 条件)
            [
                ("hand_state.raising_right_hand", ASCENDING),
                ("hand_state.raising_left_hand", ASCENDING),
            ],
            [("hand_state.raising_left_hand", ASCENDING)],
            # check_wheelchair_node
            [("wheelchair.sitting", ASCENDING)],
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

    def update_asr_dbg(self, asr, priority=50):
        q = {}
        q["text"] = asr.data
        self.physical_db.insert("asr", q, priority=priority)

    def update_asr(self, asr, vap_status=False, priority=100):
        q = json.loads(asr.data)
        q["confidence"] = float(q["scores"])
        q["text"] = "".join(q["words"])
        q["turn_end"] = vap_status
        if q["text"] == "":
            return

        x, y = q["x"], q["y"]
        angle = np.abs(np.rad2deg(np.arctan2(x, y)))
        if (
            "asr_target_angle" in self.config
            and angle > self.config["asr_target_angle"]
        ):
            self.physical_db.insert("asr_from_outside", q, priority=priority)
        else:
            self.physical_db.insert("asr", q, priority=priority)

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

    def update_objects(self, tracklet, distance_threshold, in_range_distance=6.0):
        for t in tracklet.objects:
            q = {}
            q["instance_id"] = t.instance_id
            q["name"] = t.name
            q["class_id"] = t.class_id
            q["confidence"] = t.confidence
            q["location"] = t.location.tolist()
            q["location_sensor"] = t.location_sensor.tolist()
            q["location_global"] = t.location_global.tolist()
            q["last_update"] = datetime.datetime.now()
            q["last_seen"] = q["last_update"]
            q["life"] = 0
            q["count"] = 100  # decrease if it is not observed
            ret = self.tracking_db.find_one({"instance_id": t.instance_id})
            if ret is None:
                try:
                    self.tracking_db.insert_one(q)
                except DuplicateKeyError:
                    # unique index 下で他から先に insert された場合は update する
                    q.pop("_id", None)
                    self.tracking_db.update_one(
                        {"instance_id": t.instance_id}, {"$set": q}
                    )
                # self.register_object(q, distance_threshold)
            else:
                q["life"] = ret["life"] + 1
                self.tracking_db.update_one({"instance_id": t.instance_id}, {"$set": q})
            self.register_person_found(q)
            self.register_person_in_range(q, in_range_distance)
            self.register_person_appear(q, distance_threshold)
        self.tracking_db.update_many({}, {"$inc": {"count": -1}})

        # delete if it is not observed for a while
        # for o in self.tracking_db.find({"count": {"$lt": 0}}):
        #     self.delete_object(o)
        self._delete_lost_objects({"count": {"$lt": 0}})

    def prune_lost_objects(self, timeout_sec: float) -> None:
        # 検出が0件のときは tracklet が publish されず count が減らないため，
        # 最終観測時刻からの経過時間でも見失った物体を削除する
        limit = datetime.datetime.now() - datetime.timedelta(seconds=timeout_sec)
        self._delete_lost_objects({"last_seen": {"$lt": limit}})

    def _delete_lost_objects(self, query: dict) -> None:
        for t in self.tracking_db.find(query):
            self.tracking_archive_db.insert_one(t)
            self.clear_person_events(t)
        self.tracking_db.delete_many(query)

    def register_person_found(self, o: dict, priority: int = 100) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，距離にかかわらず見つけたときに person_found を登録する
        # (発行済みかどうかは tracking の emitted.person_found で判定する)
        # distance: depth が無効な場合は None
        distance = None
        if o["location_sensor"][2] > 0:  # valid depth
            distance = float(self._calc_distance(o["location_sensor"]))
        # location_sensor: 頭のカメラ座標系の位置 (RISM が人の方を向くのに使う．z <= 0 は無効)
        q = {
            "instance_id": o["instance_id"],
            "distance": distance,
            "location_sensor": o["location_sensor"],
        }
        self._emit_once(o["instance_id"], "person_found", q, priority)

    def register_person_appear(self, o: dict, distance_threshold: float) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，距離しきい値内に入ったときに person_appear を登録する
        # (発行済みかどうかは tracking の emitted.person_appear で判定する)
        d = self._calc_distance(o["location_sensor"])
        if d > distance_threshold or d < 0.1:
            return

        q = {k: v for k, v in o.items() if k not in ("_id", "emitted")}
        q["distance"] = float(d)
        self._emit_once(o["instance_id"], "person_appear", q, 100)

    def register_person_in_range(self, o: dict, in_range_distance: float) -> None:
        if o["class_id"] != 0:
            return

        # 同一人物(instance_id)につき1回だけ，in_range_distance 以内に初めて入ったときに登録する
        # (発行済みかどうかは tracking の emitted.person_in_range で判定する)
        # person_found と違い，遠くで見つけた人が近づいてきたときにも出る
        if o["location_sensor"][2] <= 0:  # 奥行きが無効なら出さない（次のフレームで判定する）
            return
        d = float(self._calc_distance(o["location_sensor"]))
        if d > in_range_distance or d < 0.1:
            return
        q = {
            "instance_id": o["instance_id"],
            "distance": d,
            "location_sensor": o["location_sensor"],
        }
        self._emit_once(o["instance_id"], "person_in_range", q, 100)

    def clear_person_events(self, o: dict) -> None:
        # 見失った人物の人物イベントを削除する
        for event in [
            "person_found",
            "person_in_range",
            "person_appear",
            "face_detected",
            "person_noticed",
        ]:
            q = {"event": event, "contents.instance_id": o["instance_id"]}
            self.physical_db.delete(q)

    def register_object(self, o, distance_threshold):
        if o["class_id"] == 0:
            d = np.sqrt(o["location_sensor"][0] ** 2 + o["location_sensor"][2] ** 2)
            if d > distance_threshold or d < 0.1:
                return
            self.physical_db.insert("person_appear", o, priority=100)
        else:
            self.physical_db.insert("appear", o)

    def update_poses(self, poses):
        for t in poses.persons:
            q = {}
            q["last_update"] = datetime.datetime.now()
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

            ret = self.tracking_db.find_one({"instance_id": t.instance_id})
            if ret is not None:
                self.tracking_db.update_one({"instance_id": t.instance_id}, {"$set": q})

    def update_faces(self, faces, priority=100):
        for t in faces.persons:
            if t.instance_id < 0:
                continue

            # 同一人物につき1回だけ face_detected を登録する
            # (発行済みかどうかは tracking の emitted.face_detected で判定するため，
            #  tracking に存在しない instance_id は登録しない)
            q = {}
            q["instance_id"] = t.instance_id
            q["face_location"] = t.face_location.tolist()
            q["face_location_sensor"] = t.face_location_sensor.tolist()
            q["face_location_global"] = t.face_location_global.tolist()
            q["face_orientation"] = t.face_orientation.tolist()
            if len(q["face_location_sensor"]) == 3:
                q["distance"] = float(self._calc_distance(q["face_location_sensor"]))
            self._emit_once(t.instance_id, "face_detected", q, priority)

    def _calc_distance(self, location):
        x = location[0]
        z = location[2]
        return np.sqrt(x**2 + z**2)

    def clear_scenegraph(self):
        ret = self.tracking_db.update_many({}, {"$set": {"relations": []}})

    def update_scenegraph(self, relations):
        self.clear_scenegraph()
        for t in relations.relations:
            # subject
            if t.subject.instance_id == t.object.instance_id:
                continue
            if t.confidence < 0.5:
                continue
            ret = self.tracking_db.find_one({"instance_id": t.subject.instance_id})
            if ret is not None:
                # if subject is tracked then update it
                q = {}
                q["last_update"] = datetime.datetime.now()
                q["confidence"] = t.confidence
                q["relations"] = ret["relations"]

                r = {}
                r["relation_id"] = t.relation_id
                r["name"] = t.relation_name
                r["confidence"] = t.confidence

                o = {}
                o["instance_id"] = t.object.instance_id
                o["name"] = t.object.name
                o["class_id"] = t.object.class_id
                o["confidence"] = t.object.confidence
                o["location"] = t.object.location.tolist()
                o["location_sensor"] = t.object.location_sensor.tolist()
                o["location_global"] = t.object.location_global.tolist()
                r["object"] = o

                q["relations"].append(r)

                self.tracking_db.update_one(
                    {"instance_id": t.subject.instance_id}, {"$set": q}
                )
                ret = self.tracking_db.find_one({"instance_id": t.subject.instance_id})

                if ret["class_id"] == 0:  # person class
                    if t.relation_name == "wearing":
                        pass
                        # tgt = self.physical_db.db.find_one(
                        #     {
                        #         "event": "wearing",
                        #         "contents.instance_id": t.subject.instance_id,
                        #     }
                        # )
                        # if tgt is None:
                        #     if t.object.name in object_name_mapping:
                        #         ret["wearing"] = object_name_mapping[t.object.name]
                        #     else:
                        #         ret["wearing"] = "何"
                        #     self.physical_db.insert("wearing", ret, priority=100)
                    elif t.relation_name == "has":
                        pass
                        # tgt = self.physical_db.db.find_one(
                        #     {
                        #         "event": "has",
                        #         "contents.instance_id": t.subject.instance_id,
                        #     }
                        # )
                        # if tgt is None:
                        #     if t.object.name in object_name_mapping:
                        #         ret["has"] = object_name_mapping[t.object.name]
                        #     else:
                        #         ret["has"] = "何"
                        #     self.physical_db.insert("has", ret, priority=100)
                    elif t.relation_name == "holding":
                        tgt = self.physical_db.db.find_one(
                            {
                                "event": "has",
                                "contents.instance_id": t.subject.instance_id,
                            }
                        )
                        if tgt is None:
                            if t.object.name in object_name_mapping:
                                ret["has"] = object_name_mapping[t.object.name]
                            else:
                                ret["has"] = "何"
                            self.physical_db.insert("has", ret, priority=100)

            # object
            ret = self.tracking_db.find_one({"instance_id": t.object.instance_id})
            if ret is not None:
                # if object is tracked then update it
                q = {}
                q["last_update"] = datetime.datetime.now()
                q["confidence"] = t.confidence
                q["relations"] = ret["relations"]

                r = {}
                r["relation_id"] = t.relation_id
                r["name"] = t.relation_name
                r["confidence"] = t.confidence

                s = {}
                s["instance_id"] = t.subject.instance_id
                s["name"] = t.subject.name
                s["class_id"] = t.subject.class_id
                s["confidence"] = t.subject.confidence
                s["location"] = t.subject.location.tolist()
                s["location_sensor"] = t.subject.location_sensor.tolist()
                s["location_global"] = t.subject.location_global.tolist()
                r["subject"] = s

                q["relations"].append(r)
                self.tracking_db.update_one(
                    {"instance_id": t.object.instance_id}, {"$set": q}
                )

    def update_hand_state(self, pointings):
        # TODO: update pointing target
        for t in pointings.pointings:
            ret = self.tracking_db.find_one({"instance_id": t.instance_id})
            if ret is None:
                continue
            if "hand_state" in ret:
                prev_l = ret["hand_state"]["raising_left_hand"]
                prev_r = ret["hand_state"]["raising_right_hand"]
                life = ret["hand_state"]["life"] + 1
            else:
                prev_l = False
                prev_r = False
                life = 0

            q = {}
            q["raising_right_hand"] = t.raising_right_hand
            q["raising_left_hand"] = t.raising_left_hand
            q["life"] = life
            ret["hand_state"] = q
            u = {}
            u["hand_state"] = q

            self.tracking_db.update_one({"instance_id": t.instance_id}, {"$set": u})

    def update_hand_waving(self, hand_wavings_msg, priority=50):
        hand_wavings = json.loads(hand_wavings_msg.data)

        for instance_id, target_id in hand_wavings.items():
            instance_id = int(instance_id)
            ret = self.tracking_db.find_one({"instance_id": instance_id})
            if ret is not None:
                hand_waving = {"hand_waving": target_id == 1, "life": 1}
                q = {}

                if "hand_waving" in ret:
                    prev = ret["hand_waving"]
                    if prev["hand_waving"] == (target_id == 1):
                        hand_waving["life"] = prev["life"] + 1

                q["hand_waving"] = hand_waving
                self.tracking_db.update_one({"instance_id": instance_id}, {"$set": q})

    def update_attributes(self, attributes_msg, priority=50):
        for person in attributes_msg.persons:
            instance_id = person.instance_id
            ret = self.tracking_db.find_one({"instance_id": instance_id})
            if ret is not None:
                q = {}
                q["attributes"] = list(person.attributes)
                q["attribute_confidences"] = list(person.attribute_confidences)
                self.tracking_db.update_one({"instance_id": instance_id}, {"$set": q})

    def update_lookingat(self, lookingats_msg, priority=50):
        lookingats = json.loads(lookingats_msg.data)

        for instance_id, target_id in lookingats.items():
            instance_id = int(instance_id)
            ret = self.tracking_db.find_one({"instance_id": instance_id})
            if ret is not None:
                looking_at = {"target": target_id, "life": 1}
                q = {}

                if "looking_at" in ret:
                    prev = ret["looking_at"]
                    if prev["target"] == target_id:
                        looking_at["life"] = prev["life"] + 1

                q["looking_at"] = looking_at
                self.tracking_db.update_one({"instance_id": instance_id}, {"$set": q})

    def update_wheelchair(self, wheelchairs_msg, priority=50):
        wheelchairs = json.loads(wheelchairs_msg.data)

        for instance_id, target_id in wheelchairs.items():
            instance_id = int(instance_id)
            ret = self.tracking_db.find_one({"instance_id": instance_id})
            if ret is not None:
                wheelchair = {"sitting": target_id == 1, "life": 1}
                q = {}

                if "wheelchair" in ret:
                    prev = ret["wheelchair"]
                    if prev["sitting"] == (target_id == 1):
                        wheelchair["life"] = prev["life"] + 1

                q["wheelchair"] = wheelchair
                self.tracking_db.update_one({"instance_id": instance_id}, {"$set": q})

    def update_noticed(self, noticed_msg, priority=100):
        noticed = json.loads(noticed_msg.data)

        for instance_id, result in noticed.items():
            instance_id = int(instance_id)
            ret = self.tracking_db.find_one({"instance_id": instance_id})
            if ret is None:
                continue

            is_noticed = int(result.get("noticed", 0)) == 1
            state = dict(result)
            state["noticed"] = is_noticed
            state["life"] = 1
            if "noticed" in ret and ret["noticed"].get("noticed") == is_noticed:
                state["life"] = ret["noticed"].get("life", 0) + 1
            update = {"noticed": state}
            if not is_noticed:
                # 気づかなくなったら発行済みフラグを下ろし，次に気づいたときに再発行できるようにする
                update["emitted.person_noticed"] = False
            self.tracking_db.update_one({"instance_id": instance_id}, {"$set": update})

            # ロボットに気づいている間だけ person_noticed を1件保持し，気づかなくなったら削除する．
            # 気づいている間に優先度の減衰でイベントが消えても，emitted.person_noticed が
            # 立っている限り再登録しない．
            if not is_noticed:
                query = {"event": "person_noticed", "contents.instance_id": instance_id}
                self.physical_db.delete(query)
                continue
            # 気づいたときの位置 (tracking の記録)．RISM はこれを優先して人の方を向く
            q = {
                "instance_id": instance_id,
                "noticed": state,
                "location_sensor": ret.get("location_sensor"),
            }
            self._emit_once(instance_id, "person_noticed", q, priority)

    def delete_object(self, o):
        if o["class_id"] == 0:
            self.physical_db.insert("person_disappear", o, priority=100)
        else:
            self.physical_db.insert("disappear", o)

        # 削除した際には，person_appearも削除する
        self.clear_person_events(o)

    def step_physical_db(self):
        self.physical_db.decrease_priority()

    def step_cyber_db(self):
        self.cyber_db.decrease_priority()
