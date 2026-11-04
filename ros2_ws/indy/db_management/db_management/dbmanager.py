# -*- coding: utf-8 -*-
import datetime
import json

import numpy as np
from pyindy.mongo import DBManager
from pymongo import MongoClient

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
        self.config = self.client["rism_configs"].rism_config.find_one()

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

    def update_objects(self, tracklet, distance_threshold):
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
            q["life"] = 0
            q["count"] = 100  # decrease if it is not observed
            ret = self.tracking_db.find_one({"instance_id": t.instance_id})
            if ret is None:
                self.tracking_db.insert_one(q)
                # self.register_object(q, distance_threshold)
            else:
                q["life"] = ret["life"] + 1
                self.tracking_db.update_one({"instance_id": t.instance_id}, {"$set": q})
        self.tracking_db.update_many({}, {"$inc": {"count": -1}})

        # delete if it is not observed for a while
        # for o in self.tracking_db.find({"count": {"$lt": 0}}):
        #     self.delete_object(o)
        to_be_delete = self.tracking_db.find({"count": {"$lt": 0}})
        for t in to_be_delete:
            self.tracking_archive_db.insert_one(t)
        self.tracking_db.delete_many({"count": {"$lt": 0}})

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
            q["pose"]["confidneces"] = t.pose.confidences.tolist()
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
            query = {"event": "face_detected", "contents.instance_id": t.instance_id}
            if self.physical_db.db.find_one(query) is not None:
                continue

            q = {}
            q["instance_id"] = t.instance_id
            q["face_location"] = t.face_location.tolist()
            q["face_location_sensor"] = t.face_location_sensor.tolist()
            q["face_location_global"] = t.face_location_global.tolist()
            q["face_orientation"] = t.face_orientation.tolist()
            if len(q["face_location_sensor"]) == 3:
                q["distance"] = float(self._calc_distance(q["face_location_sensor"]))
            self.physical_db.insert("face_detected", q, priority=priority)

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

    def delete_object(self, o):
        if o["class_id"] == 0:
            self.physical_db.insert("person_disappear", o, priority=100)
        else:
            self.physical_db.insert("disappear", o)

        # 削除した際には，person_appearも削除する
        q = {"event": "person_appear", "contents.instance_id": o["instance_id"]}
        self.physical_db.delete(q)
        q = {"event": "face_detected", "contents.instance_id": o["instance_id"]}
        self.physical_db.delete(q)

    def step_physical_db(self):
        self.physical_db.decrease_priority()

    def step_cyber_db(self):
        self.cyber_db.decrease_priority()
