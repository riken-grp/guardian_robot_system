"""TopicDBManager の人物イベント発行 (emitted フラグ) とインデックス作成のテスト.

MongoDB サーバを使わずに，必要最小限の機能を持つ fake コレクションで検証する.
"""

import itertools
import json
import os
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_management.dbmanager import TopicDBManager  # noqa: E402

_ids = itertools.count(1)


def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _match(doc, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, q) for q in v):
                return False
            continue
        cur = _get(doc, k)
        if isinstance(v, dict) and any(op.startswith("$") for op in v):
            for op, arg in v.items():
                if op == "$ne" and cur == arg:
                    return False
                if op == "$lt" and (cur is None or not cur < arg):
                    return False
                if op == "$gt" and (cur is None or not cur > arg):
                    return False
        elif cur != v:
            return False
    return True


def _set(doc, path, value):
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


class FakeCollection:
    def __init__(self, name="fake"):
        self.name = name
        self.docs = []
        self.indexes = []

    def create_index(self, keys, **kwargs):
        self.indexes.append((list(keys), kwargs))

    def find_one(self, q=None):
        return next((d for d in self.docs if _match(d, q or {})), None)

    def find(self, q=None):
        return [d for d in self.docs if _match(d, q or {})]

    def count_documents(self, q):
        return len(self.find(q))

    def insert_one(self, d):
        d.setdefault("_id", next(_ids))
        self.docs.append(dict(d))

    def _apply(self, d, u):
        before = json.dumps(d, default=str, sort_keys=True)
        for k, v in u.get("$set", {}).items():
            _set(d, k, v)
        for k, v in u.get("$inc", {}).items():
            _set(d, k, (_get(d, k) or 0) + v)
        return before != json.dumps(d, default=str, sort_keys=True)

    def update_one(self, q, u):
        d = self.find_one(q)
        modified = self._apply(d, u) if d is not None else False
        return NS(matched_count=int(d is not None), modified_count=int(modified))

    def update_many(self, q, u):
        n = sum(self._apply(d, u) for d in self.find(q))
        return NS(modified_count=n)

    def delete_many(self, q):
        self.docs = [d for d in self.docs if not _match(d, q)]


class FakePhysical:
    """pyindy DBManager 相当 (insert / delete / decrease_priority)."""

    def __init__(self):
        self.db = FakeCollection("physical_topic")

    def insert(self, event, contents, priority=50):
        self.db.insert_one(
            {"event": event, "contents": contents, "priority": priority}
        )

    def delete(self, q):
        self.db.delete_many(q)

    def decrease_priority(self):
        self.db.update_many({}, {"$inc": {"priority": -1}})
        self.db.delete_many({"priority": {"$lt": 0}})


@pytest.fixture
def m():
    mgr = TopicDBManager.__new__(TopicDBManager)
    mgr.tracking_db = FakeCollection("tracking")
    mgr.tracking_archive_db = FakeCollection("tracking_archive")
    mgr.physical_db = FakePhysical()
    mgr.cyber_db = FakePhysical()
    mgr.config = {}
    return mgr


def arr(*v):
    return np.array(v, float)


def obj(i, z, class_id=0):
    return NS(
        instance_id=i,
        name="person",
        class_id=class_id,
        confidence=0.9,
        location=arr(0, 0, 1, 1),
        location_sensor=arr(0, 0, z),
        location_global=arr(0, 0, 0),
    )


def face(i):
    return NS(
        instance_id=i,
        face_location=arr(0, 0, 1, 1),
        face_location_sensor=arr(0, 0, 1.5),
        face_location_global=arr(0, 0, 0),
        face_orientation=arr(0, 0, 0),
    )


def noticed(d):
    return NS(data=json.dumps(d))


def events(m, name=None):
    return sorted(
        (e["event"], e["contents"]["instance_id"])
        for e in m.physical_db.db.docs
        if name is None or e["event"] == name
    )


def expire_all(m):
    # decrease_priority を十分な回数呼んで全イベントを期限切れにする
    for _ in range(400):
        m.physical_db.decrease_priority()
    assert m.physical_db.db.docs == []


def test_person_events_emitted_once_even_after_expiry(m):
    frame = NS(objects=[obj(1, 8.0), obj(2, 2.0)])
    m.update_objects(frame, 3.0)
    m.update_faces(NS(persons=[face(2)]))
    assert events(m) == [
        ("face_detected", 2),
        ("person_appear", 2),
        ("person_found", 1),
        ("person_found", 2),
        ("person_in_range", 2),
    ]

    # イベントが優先度減衰で消えても，同じ人物が映り続けている間は再登録しない
    expire_all(m)
    for _ in range(5):
        m.update_objects(frame, 3.0)
        m.update_faces(NS(persons=[face(2)]))
    assert events(m) == []

    t2 = m.tracking_db.find_one({"instance_id": 2})
    assert t2["emitted"] == {
        "person_found": True,
        "person_in_range": True,
        "person_appear": True,
        "face_detected": True,
    }


def test_person_appear_when_entering_threshold_later(m):
    m.update_objects(NS(objects=[obj(1, 8.0)]), 3.0)
    assert events(m, "person_appear") == []
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    assert events(m, "person_appear") == [("person_appear", 1)]
    e = m.physical_db.db.find_one({"event": "person_appear"})
    assert "_id" not in e["contents"] and "emitted" not in e["contents"]
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    assert events(m, "person_appear") == [("person_appear", 1)]


def test_non_person_and_untracked_face(m):
    m.update_objects(NS(objects=[obj(5, 2.0, class_id=3)]), 3.0)
    assert events(m) == []
    # tracking に無い instance_id の顔は登録しない
    m.update_faces(NS(persons=[face(99)]))
    assert events(m) == []


def test_lost_person_resets_flags(m):
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    m.update_noticed(noticed({"1": {"noticed": 1}}))
    assert len(m.physical_db.db.docs) == 4
    m.clear_person_events({"instance_id": 1})
    m._delete_lost_objects({"instance_id": 1})
    assert events(m) == []
    assert m.tracking_db.docs == []
    assert len(m.tracking_archive_db.docs) == 1

    # 同じ instance_id が再出現したら新しいライフタイムとして再発行される
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    assert events(m) == [
        ("person_appear", 1),
        ("person_found", 1),
        ("person_in_range", 1),
    ]


def test_person_noticed_lifecycle(m):
    m.update_objects(NS(objects=[obj(3, 2.0)]), 3.0)

    m.update_noticed(noticed({"3": {"noticed": 1}}))
    m.update_noticed(noticed({"3": {"noticed": 1}}))
    assert events(m, "person_noticed") == [("person_noticed", 3)]

    # 気づいている間にイベントが期限切れになっても再登録しない
    expire_all(m)
    m.update_noticed(noticed({"3": {"noticed": 1}}))
    assert events(m, "person_noticed") == []
    assert m.tracking_db.find_one({"instance_id": 3})["noticed"]["life"] == 3

    # 気づかなくなったらフラグを下ろす -> 次に気づいたら再登録
    m.update_noticed(noticed({"3": {"noticed": 0}}))
    assert m.tracking_db.find_one({"instance_id": 3})["emitted"]["person_noticed"] is False
    m.update_noticed(noticed({"3": {"noticed": 1}}))
    assert events(m, "person_noticed") == [("person_noticed", 3)]

    # 気づかなくなったらイベントを削除する
    m.update_noticed(noticed({"3": {"noticed": 0}}))
    assert events(m, "person_noticed") == []


def test_legacy_event_not_duplicated(m):
    # フラグ導入前に登録されたイベントが残っている場合は二重登録しない
    m.tracking_db.insert_one({"instance_id": 7, "class_id": 0, "life": 0})
    m.physical_db.insert("person_found", {"instance_id": 7, "distance": 1.0})
    m.update_objects(NS(objects=[obj(7, 2.0)]), 3.0)
    assert events(m, "person_found") == [("person_found", 7)]


def test_emit_failure_rolls_back_flag(m):
    m.tracking_db.insert_one({"instance_id": 8, "class_id": 0, "life": 0})

    def boom(*a, **k):
        raise RuntimeError("db down")

    orig = m.physical_db.insert
    m.physical_db.insert = boom
    with pytest.raises(RuntimeError):
        m._emit_once(8, "person_found", {"instance_id": 8}, 100)
    assert m.tracking_db.find_one({"instance_id": 8})["emitted"]["person_found"] is False
    m.physical_db.insert = orig
    assert m._emit_once(8, "person_found", {"instance_id": 8}, 100) is True
    assert m._emit_once(8, "person_found", {"instance_id": 8}, 100) is False


def test_pose_confidences_key(m):
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    kp = NS(dim=3, keypoints=arr(0, 0, 1), confidences=arr(0.5))
    m.update_poses(
        NS(
            persons=[
                NS(
                    instance_id=1,
                    pose=kp,
                    pose_sensor=kp,
                    pose_global=kp,
                    body_location_sensor=arr(0, 0, 1),
                )
            ]
        )
    )
    pose = m.tracking_db.find_one({"instance_id": 1})["pose"]
    assert "confidences" in pose and "confidneces" not in pose


def test_ensure_indexes(m):
    m._ensure_indexes()
    tracking = m.tracking_db.indexes
    assert tracking[0] == ([("instance_id", 1)], {"unique": True})
    keys = [k for k, _ in tracking]
    assert [("class_id", 1)] in keys
    assert [("last_seen", 1)] in keys
    assert [("looking_at.target", 1), ("looking_at.life", 1)] in keys
    assert [("wheelchair.sitting", 1)] in keys
    assert m.physical_db.db.indexes == [
        ([("event", 1), ("contents.instance_id", 1)], {})
    ]


def test_ensure_indexes_never_raises(m):
    from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

    calls = []

    def dup(keys, **kw):
        calls.append((keys, kw))
        if kw.get("unique"):
            raise OperationFailure("E11000 duplicate key")

    m.tracking_db.create_index = dup
    m._ensure_indexes()
    # unique に失敗したら非 unique で張る
    assert calls[1] == ([("instance_id", 1)], {})

    def down(keys, **kw):
        raise ServerSelectionTimeoutError("no server")

    m.tracking_db.create_index = down
    m._ensure_indexes()  # 例外を投げない


def in_range(m):
    return [e["contents"] for e in m.physical_db.db.docs if e["event"] == "person_in_range"]


def test_person_in_range_when_approaching_from_far(m):
    # 6 m より先で見つけた人: person_found は出るが person_in_range は出ない
    m.update_objects(NS(objects=[obj(7, 9.0)]), 3.0, 6.0)
    assert events(m, "person_found") == [("person_found", 7)]
    assert in_range(m) == []
    m.update_objects(NS(objects=[obj(7, 6.5)]), 3.0, 6.0)
    assert in_range(m) == []
    # 6 m を切ったところで1件
    m.update_objects(NS(objects=[obj(7, 5.8)]), 3.0, 6.0)
    assert in_range(m) == [{"instance_id": 7, "distance": 5.8, "location_sensor": [0.0, 0.0, 5.8]}]
    e = m.physical_db.db.find_one({"event": "person_in_range"})
    assert e["priority"] == 100 and isinstance(e["contents"]["distance"], float)
    # 3 m より先なので person_appear はまだ出ない
    assert events(m, "person_appear") == []


def test_person_in_range_once_while_tracked(m):
    for z in [5.0, 7.0, 5.5, 8.0, 4.0, 2.0]:  # 6 m の内外を行き来する
        m.update_objects(NS(objects=[obj(1, z)]), 3.0, 6.0)
    assert in_range(m) == [{"instance_id": 1, "distance": 5.0, "location_sensor": [0.0, 0.0, 5.0]}]
    # 優先度減衰で消えても，追跡が続く間は再発行しない
    expire_all(m)
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0, 6.0)
    assert in_range(m) == []


def test_person_in_range_invalid_depth_waits_for_next_frame(m):
    m.update_objects(NS(objects=[obj(2, 0.0)]), 3.0, 6.0)  # 奥行き無効
    m.update_objects(NS(objects=[obj(2, -1.0)]), 3.0, 6.0)
    assert in_range(m) == []
    assert m.tracking_db.find_one({"instance_id": 2}).get("emitted", {}).get("person_in_range") is not True
    m.update_objects(NS(objects=[obj(2, 4.0)]), 3.0, 6.0)
    assert in_range(m) == [{"instance_id": 2, "distance": 4.0, "location_sensor": [0.0, 0.0, 4.0]}]
    assert all(c["distance"] is not None for c in in_range(m))


def test_person_in_range_cleared_when_lost_and_reissued(m):
    m.update_objects(NS(objects=[obj(3, 4.0)]), 3.0, 6.0)
    assert len(in_range(m)) == 1
    m.clear_person_events({"instance_id": 3})
    m._delete_lost_objects({"instance_id": 3})
    assert in_range(m) == []
    # 再び見つかって 6 m 以内に入ったら，新しい instance_id で1件
    m.update_objects(NS(objects=[obj(4, 9.0)]), 3.0, 6.0)
    assert in_range(m) == []
    m.update_objects(NS(objects=[obj(4, 5.0)]), 3.0, 6.0)
    assert in_range(m) == [{"instance_id": 4, "distance": 5.0, "location_sensor": [0.0, 0.0, 5.0]}]


def test_person_in_range_not_for_objects_and_threshold_parameter(m):
    m.update_objects(NS(objects=[obj(5, 2.0, class_id=3)]), 3.0, 6.0)
    assert in_range(m) == []
    m.update_objects(NS(objects=[obj(6, 7.0)]), 3.0, 8.0)  # 閾値をパラメータで変更
    assert in_range(m) == [{"instance_id": 6, "distance": 7.0, "location_sensor": [0.0, 0.0, 7.0]}]


def contents(m, event):
    return [e["contents"] for e in m.physical_db.db.docs if e["event"] == event]


def test_person_events_have_location_sensor(m):
    # 左 (x < 0) にいる人: RISM が向く方向を求められる位置が入る
    o = obj(5, 4.0)
    o.location_sensor = arr(-1.5, 0.2, 4.0)
    m.update_objects(NS(objects=[o]), 3.0, 6.0)
    for event in ["person_found", "person_in_range"]:
        (c,) = contents(m, event)
        assert c["location_sensor"] == [-1.5, 0.2, 4.0], event

    # person_noticed: 気づいたときの tracking の位置 (動いたあとの位置)
    o.location_sensor = arr(0.8, 0.1, 3.5)
    m.update_objects(NS(objects=[o]), 3.0, 6.0)
    m.update_noticed(noticed({"5": {"noticed": 1}}))
    (c,) = contents(m, "person_noticed")
    assert c["instance_id"] == 5 and c["location_sensor"] == [0.8, 0.1, 3.5]
    # person_found / person_in_range は出したときの位置のまま
    assert contents(m, "person_found")[0]["location_sensor"] == [-1.5, 0.2, 4.0]


def test_person_found_invalid_depth_keeps_location(m):
    # 奥行きが無効でも値はそのまま入れる (RISM 側で z <= 0 は使わない)
    m.update_objects(NS(objects=[obj(6, 0.0)]), 3.0, 6.0)
    (c,) = contents(m, "person_found")
    assert c["distance"] is None and c["location_sensor"] == [0.0, 0.0, 0.0]
