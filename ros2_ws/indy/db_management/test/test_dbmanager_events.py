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

from db_management.dbmanager import DEFAULT_OPTIONS, TopicDBManager  # noqa: E402
from db_management.recognition_available_region_checker import (  # noqa: E402
    RecognitionAvailableRegionChecker,
)

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
                if op == "$in" and cur not in arg:
                    return False
                if op == "$lt" and (cur is None or not cur < arg):
                    return False
                if op == "$lte" and (cur is None or not cur <= arg):
                    return False
                if op == "$gte" and (cur is None or not cur >= arg):
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

    def find_one(self, q=None, projection=None):
        return next((d for d in self.docs if _match(d, q or {})), None)

    def find(self, q=None, projection=None):
        self.n_find = getattr(self, "n_find", 0) + 1
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

    def update_one(self, q, u, upsert=False):
        d = self.find_one(q)
        if d is None and upsert:
            self.insert_one({k: v for k, v in q.items() if not k.startswith("$")})
            d = self.docs[-1]
            self._apply(d, u)
            return NS(matched_count=0, modified_count=0)
        modified = self._apply(d, u) if d is not None else False
        return NS(matched_count=int(d is not None), modified_count=int(modified))

    def bulk_write(self, ops, ordered=True):
        self.n_bulk = getattr(self, "n_bulk", 0) + 1
        for op in ops:  # pymongo.UpdateOne
            FakeCollection.update_one(self, op._filter, op._doc, upsert=bool(op._upsert))

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
    mgr.options = dict(DEFAULT_OPTIONS)
    mgr.prev_num_person = None
    mgr.region_checker = RecognitionAvailableRegionChecker({})
    return mgr


def arr(*v):
    return np.array(v, float)


def obj(i, z, class_id=0, x=600.0):
    return NS(
        instance_id=i,
        name="person",
        class_id=class_id,
        confidence=0.9,
        location=arr(x, 300, 80, 200),  # bbox in the 1280 px wide image (center by default)
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

    # lost_grace (15 s) を過ぎて同じ instance_id が再出現したら新しいライフタイムとして再発行される
    import datetime

    m.tracking_archive_db.docs[0]["last_seen"] -= datetime.timedelta(seconds=20)
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
    assert [("looking_at.target", 1), ("looking_at.since", 1)] in keys
    assert [("instance_id", 1), ("last_seen", 1)] in [k for k, _ in m.tracking_archive_db.indexes]
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


def test_one_find_and_one_bulk_write_per_message(m):
    frame = NS(objects=[obj(i, 2.0) for i in range(5)])
    m.update_objects(frame, 3.0)
    m.tracking_db.n_find = m.tracking_db.n_bulk = 0
    m.tracking_db.update_one = None  # emitted: no per-person update anymore
    for _ in range(3):
        m.update_objects(frame, 3.0)
    assert (m.tracking_db.n_find, m.tracking_db.n_bulk) == (3, 3)
    assert [d["life"] for d in m.tracking_db.docs] == [3] * 5
    assert all("count" not in d for d in m.tracking_db.docs)


def test_state_life_counts_same_state(m):
    m.update_objects(NS(objects=[obj(1, 2.0), obj(2, 2.0)]), 3.0)
    for v in [1, 1, 0]:
        m.update_hand_waving(noticed({"1": v, "2": 1, "9": 1}))  # 9: not tracked
    t1 = m.tracking_db.find_one({"instance_id": 1})
    t2 = m.tracking_db.find_one({"instance_id": 2})
    assert t1["hand_waving"] == {"hand_waving": False, "life": 1}
    assert t2["hand_waving"] == {"hand_waving": True, "life": 3}
    assert m.tracking_db.find_one({"instance_id": 9}) is None
    m.update_lookingat(noticed({"1": 0}))
    m.update_lookingat(noticed({"1": 0}))
    m.update_wheelchair(noticed({"2": 1}))
    looking = m.tracking_db.find_one({"instance_id": 1})["looking_at"]
    first_since = looking.pop("since")
    assert looking == {"target": 0, "life": 2}
    m.update_lookingat(noticed({"1": 1}))  # another target: since is reset
    looking = m.tracking_db.find_one({"instance_id": 1})["looking_at"]
    assert looking["life"] == 1 and looking["since"] >= first_since
    assert m.tracking_db.find_one({"instance_id": 2})["wheelchair"] == {"sitting": True, "life": 1}


def test_lost_objects_pruned_by_time(m):
    import datetime

    m.update_objects(NS(objects=[obj(1, 2.0), obj(2, 2.0)]), 3.0)
    m.tracking_db.docs[0]["last_seen"] -= datetime.timedelta(seconds=10)
    m.prune_lost_objects(3.0)
    assert [d["instance_id"] for d in m.tracking_db.docs] == [2]
    assert [d["instance_id"] for d in m.tracking_archive_db.docs] == [1]


def test_looking_duration_in_seconds(m):
    import datetime

    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    m.update_lookingat(noticed({"1": 1}))
    now = datetime.datetime.now()
    q = TopicDBManager.looking_query
    assert m.tracking_db.find_one(q(now, 1, 0.2)) is None  # just started
    later = now + datetime.timedelta(seconds=0.5)
    assert m.tracking_db.find_one(q(later, 1, 0.2))["instance_id"] == 1
    assert m.tracking_db.find_one(q(later, 1, 1.0)) is None
    assert m.tracking_db.find_one(q(later, 2, 0.2)) is None  # other target


# ---------------------------------------------------------------- person lifecycle


def lose(m, i, seconds):
    """instance_id i を seconds 秒前に見失ったことにして archive に移す."""
    import datetime

    for d in m.tracking_db.docs:
        if d["instance_id"] == i:
            d["last_seen"] -= datetime.timedelta(seconds=seconds)
            d["first_seen"] -= datetime.timedelta(seconds=seconds)
    m.prune_lost_objects(3.0)


def test_returning_within_grace_is_not_greeted_again(m):
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    lose(m, 1, 5)  # hidden for 5 s
    first_seen = m.tracking_archive_db.docs[0]["first_seen"]
    assert m.tracking_db.docs == [] and events(m) == []
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    assert events(m) == []  # no person_found / appear again
    doc = m.tracking_db.find_one({"instance_id": 1})
    assert doc["first_seen"] == first_seen
    assert doc["emitted"]["person_found"] is True
    # returned: no person_disappear for the first lifetime
    import datetime

    m._register_person_disappear(datetime.datetime.now() + datetime.timedelta(seconds=20))
    assert events(m, "person_disappear") == []


def test_person_disappear_once_after_grace(m):
    import datetime

    m.update_objects(NS(objects=[obj(1, 2.0), obj(2, 1.0, class_id=5)]), 3.0)
    m.update_faces(NS(persons=[face(1)]))
    lose(m, 1, 5)
    lose(m, 2, 5)
    m._register_person_disappear(datetime.datetime.now())
    assert events(m, "person_disappear") == []  # still within lost_grace
    later = datetime.datetime.now() + datetime.timedelta(seconds=15)
    m._register_person_disappear(later)
    m._register_person_disappear(later)
    assert events(m, "person_disappear") == [("person_disappear", 1)]  # persons only, once
    c = m.physical_db.db.find_one({"event": "person_disappear"})["contents"]
    assert "face_detected" in c["events"] and "person_found" in c["events"]
    assert c["min_distance"] == 2.0 and c["stay_sec"] >= 0


def test_person_too_near_with_hysteresis(m):
    def near(z):
        m.update_objects(NS(objects=[obj(1, z)]), 3.0)
        return events(m, "person_too_near")

    assert near(1.0) == []
    assert near(0.4) == [("person_too_near", 1)]
    assert near(0.6) == [("person_too_near", 1)]  # between 0.5 and 0.7: kept
    assert near(0.8) == []  # backed off: withdrawn
    assert near(0.45) == [("person_too_near", 1)]  # came near again
    assert m.tracking_db.find_one({"instance_id": 1})["min_distance"] == 0.4


def pointing(i, left=False, right=False):
    return NS(instance_id=i, raising_left_hand=left, raising_right_hand=right)


def test_raising_hand_while_raised(m):
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    m.update_hand_state(NS(pointings=[pointing(1, left=True)]))
    m.update_hand_state(NS(pointings=[pointing(1, left=True, right=True)]))
    assert events(m, "raising_hand") == [("raising_hand", 1)]
    c = m.physical_db.db.find_one({"event": "raising_hand"})["contents"]
    assert "_id" not in c and "emitted" not in c and c["hand_state"]["raising_left_hand"]
    m.update_hand_state(NS(pointings=[pointing(1)]))
    assert events(m, "raising_hand") == []
    m.update_hand_state(NS(pointings=[pointing(1, right=True)]))
    assert events(m, "raising_hand") == [("raising_hand", 1)]


def test_raising_hand_outside_region_is_ignored(m):
    m.region_checker = RecognitionAvailableRegionChecker(
        {"recognition_available_regions": [
            {"type": "rectangle", "region_id": 0, "locations": [[5, 5], [6, 6]]}
        ]}
    )
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)  # location_global (0, 0)
    m.update_hand_state(NS(pointings=[pointing(1, left=True)]))
    assert events(m, "raising_hand") == []


def test_waving_hand_and_wheelchair_events(m):
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    m.update_hand_waving(noticed({"1": 1}))
    m.update_hand_waving(noticed({"1": 1}))
    assert events(m, "waving_hand") == [("waving_hand", 1)]
    m.update_hand_waving(noticed({"1": 0}))
    assert events(m, "waving_hand") == []
    m.update_wheelchair(noticed({"1": 1}))
    m.update_wheelchair(noticed({"1": 0}))
    m.update_wheelchair(noticed({"1": 1}))
    assert events(m, "wheelchair") == [("wheelchair", 1)]  # once while tracked
    expire_all(m)
    m.update_wheelchair(noticed({"1": 1}))
    assert events(m, "wheelchair") == []


def test_number_of_people_events(m):
    def names():
        return [e["event"] for e in m.physical_db.db.docs]

    m.check_events()
    assert names() == ["no_people"]  # at start without anybody (as before)
    m.update_objects(NS(objects=[obj(i, 8.0) for i in range(4)]), 3.0)
    m.physical_db.db.docs = []
    m.check_events()
    assert names() == ["many_people"]  # 4 > 3
    m.check_events()
    assert names() == ["many_people"]  # only on the change
    m.tracking_db.docs = []
    m.check_events()
    assert names() == ["many_people", "no_people"]


def test_looking_events_per_target(m):
    import datetime

    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    m.update_lookingat(noticed({"1": 1}))
    now = datetime.datetime.now()
    m.check_events(now)
    assert not [e for e in m.physical_db.db.docs if "looking" in e["event"]]
    m.check_events(now + datetime.timedelta(seconds=0.5))
    m.check_events(now + datetime.timedelta(seconds=2))
    looking = [e for e in m.physical_db.db.docs if e["event"].endswith("looking")]
    assert sorted(e["event"] for e in looking) == ["long_looking", "looking"]  # one each
    assert all(e["contents"]["target"] == 1 for e in looking)
    assert max(e["contents"]["duration"] for e in looking) >= 2.0


def test_attributes_smoothed_and_in_person_appear(m):
    m.update_objects(NS(objects=[obj(1, 8.0)]), 3.0)  # far: no person_appear yet
    for conf in (1.0, 0.0):
        m.update_attributes(NS(persons=[NS(instance_id=1, attributes=["skirt"], attribute_confidences=[conf])]))
    doc = m.tracking_db.find_one({"instance_id": 1})
    assert doc["attribute_confidences"] == [0.0]
    assert doc["attributes_smoothed"]["skirt"] == pytest.approx(0.7)
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    c = m.physical_db.db.find_one({"event": "person_appear"})["contents"]
    assert c["attributes"]["skirt"] == pytest.approx(0.7)


def test_face_is_kept_in_tracking(m):
    m.update_objects(NS(objects=[obj(2, 2.0)]), 3.0)
    m.update_faces(NS(persons=[face(2)]))
    m.update_faces(NS(persons=[face(2)]))
    assert m.tracking_db.find_one({"instance_id": 2})["face"]["face_orientation"] == [0, 0, 0]
    assert events(m, "face_detected") == [("face_detected", 2)]


def lost_for(m, i, seconds):
    """instance_id i を seconds 秒前に最後に見たことにする (tracking に残したまま)."""
    import datetime

    for d in m.tracking_db.docs:
        if d["instance_id"] == i:
            d["last_seen"] -= datetime.timedelta(seconds=seconds)
            d["first_seen"] -= datetime.timedelta(seconds=seconds)


def disappear(m):
    return {
        e["contents"]["instance_id"]: e["contents"]["reason"]
        for e in m.physical_db.db.docs
        if e["event"] == "person_disappear"
    }


def test_exit_at_the_image_edge_is_reported_at_once(m):
    m.update_objects(NS(objects=[obj(1, 2.0, x=5.0), obj(2, 2.0, x=1220.0), obj(3, 2.0)]), 3.0)
    lost_for(m, 1, 0.5)
    m.prune_lost_objects(3.0)
    assert disappear(m) == {}  # before exit_check_sec
    for i in (1, 2, 3):
        lost_for(m, i, 1.0)
    m.prune_lost_objects(3.0)
    # 1, 2: left the image at the edges; 3: lost in the middle -> wait for lost_grace
    assert disappear(m) == {1: "out_of_view_left", 2: "out_of_view_right"}
    m.prune_lost_objects(3.0)
    lost_for(m, 1, 2.0)  # archived at lost_timeout: the event stays
    m.prune_lost_objects(3.0)
    assert disappear(m) == {1: "out_of_view_left", 2: "out_of_view_right"}
    c = m.physical_db.db.find_one({"event": "person_disappear"})["contents"]
    assert c["lost_sec"] >= 1.0 and "person_found" in c["events"]


def test_walking_away_and_far(m):
    import datetime

    z = 2.0
    for k in range(5):  # moving away at ~1 m/s
        m.update_objects(NS(objects=[obj(1, z), obj(2, 7.0)]), 3.0)
        for d in m.tracking_db.docs:
            d["last_seen"] -= datetime.timedelta(seconds=0.2)
        z += 0.2
    assert m.tracking_db.find_one({"instance_id": 1})["distance_rate"] > 0.3
    for i in (1, 2):
        lost_for(m, i, 1.0)
    m.prune_lost_objects(3.0)
    assert disappear(m) == {1: "walked_away", 2: "too_far"}


def test_returning_after_a_quick_exit_withdraws_it(m):
    m.update_objects(NS(objects=[obj(1, 2.0, x=5.0)]), 3.0)
    lost_for(m, 1, 1.0)
    m.prune_lost_objects(3.0)
    assert disappear(m) == {1: "out_of_view_left"}
    m.update_objects(NS(objects=[obj(1, 2.0, x=5.0)]), 3.0)  # back (still in tracking)
    assert disappear(m) == {}
    assert events(m, "person_found") == [("person_found", 1)]
    # again, and this time back from the archive (lost 5 s)
    lost_for(m, 1, 1.0)
    m.prune_lost_objects(3.0)
    lose(m, 1, 4)
    assert disappear(m) == {1: "out_of_view_left"}
    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    assert disappear(m) == {}
    assert events(m, "person_found") == []  # deleted when lost, not greeted again


def test_lost_in_the_middle_waits_for_grace(m):
    import datetime

    m.update_objects(NS(objects=[obj(1, 2.0)]), 3.0)
    lose(m, 1, 5)
    assert disappear(m) == {}
    m._register_person_disappear(datetime.datetime.now() + datetime.timedelta(seconds=15))
    assert disappear(m) == {1: "lost"}
