import datetime
from types import SimpleNamespace as NS

from bson import ObjectId

from robot_looking.looking_target_recognition_node import (
    LookingTargetRecognizer, LookingTargetRecognizerFromAudio)


class Tracking:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q, projection=None):
        return [dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())]

    def find_one(self, q, projection=None):
        r = self.find(q)
        return r[0] if r else None


class Actions:
    def __init__(self):
        self.doc = None

    def say(self, instance_id, age=0.0):
        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age)
        self.doc = {"_id": ObjectId.from_datetime(t),
                    "found": {"contents": {"instance_id": instance_id}}}

    def find_one(self, q, projection=None, sort=None):
        return self.doc


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def person(i, w, count=100):
    return {"instance_id": i, "class_id": 0, "name": "person",
            "location": [0, 0, w, w], "location_sensor": [0, 0, 2], "count": count}


def make(docs, **kw):
    clock = Clock()
    actions = Actions()
    rec = LookingTargetRecognizer(Tracking(docs), actions, max_duration=60,
                                  unobserve_threshold=70, clock=clock, **kw)
    return rec, actions, clock


def test_negative_instance_ids_are_ignored():
    rec, _, _ = make([person(-1, 500), person(3, 10)])
    assert rec()["instance_id"] == 3


def test_talking_person_once_then_stays_without_oscillation():
    rec, actions, clock = make([person(1, 100), person(2, 10)])
    assert rec()["instance_id"] == 1  # largest
    actions.say(2)
    assert rec()["instance_id"] == 2  # just spoke
    for _ in range(5):  # the same (old) asr result must not toggle the target
        clock.t += 0.1
        assert rec()["instance_id"] == 2


def test_old_asr_is_ignored():
    rec, actions, _ = make([person(1, 100), person(2, 10)], asr_max_age=5.0)
    actions.say(2, age=30.0)
    assert rec()["instance_id"] == 1


def test_max_duration_and_unobserved_target():
    docs = [person(1, 100), person(2, 10)]
    rec, actions, clock = make(docs)
    actions.say(2)
    rec()
    docs[1]["count"] = 10  # no longer observed
    assert rec()["instance_id"] == 1


def test_audio_keeps_speaker_by_human_id_and_picks_loudest():
    rec = LookingTargetRecognizerFromAudio(max_duration=60, clock=Clock())
    def ht(hid, power, vad=1):
        return NS(human_id=hid, instance_id=hid + 10, vad=vad, power=power,
                  x=1, y=2, z=3, person_name="")
    vad, t = rec(NS(info=[ht(5, 10), ht(7, 50)]))
    assert vad and t["human_id"] == 7 and t["instance_id"] == 17
    # order changes, the current speaker is kept even if another is louder
    vad, t = rec(NS(info=[ht(9, 99), ht(7, 20)]))
    assert t["human_id"] == 7
    vad, t = rec(NS(info=[ht(7, 20, vad=0)]))
    assert not vad and t is None


def test_max_duration_switches_to_another_target():
    rec, _, clock = make([person(1, 100), person(2, 10)])
    assert rec()["instance_id"] == 1
    clock.t += 61
    assert rec()["instance_id"] == 2  # looked at 1 for max_duration
    clock.t += 0.1
    assert rec()["instance_id"] == 2  # and stays


def test_max_duration_single_target_is_kept():
    rec, _, clock = make([person(1, 100)])
    rec()
    clock.t += 61
    assert rec()["instance_id"] == 1


def test_lookup_and_focus_from_audio():
    rec, _, _ = make([person(1, 100), person(2, 10)])
    assert rec.lookup(-1) is None and rec.lookup(5) is None
    assert rec.lookup(2)["location_sensor"] == [0, 0, 2]
    rec()
    rec.focus(2)  # the speaker found by the audio path
    assert rec()["instance_id"] == 2
