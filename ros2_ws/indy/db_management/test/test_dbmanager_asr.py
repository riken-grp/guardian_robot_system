"""TopicDBManager の ASR 結果の正規化と登録のテスト (MongoDB 不要)."""

import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_management.dbmanager import TopicDBManager  # noqa: E402


class FakePhysical:
    def __init__(self):
        self.docs = []

    def insert(self, event, contents, priority=50):
        self.docs.append({"event": event, "contents": contents, "priority": priority})


@pytest.fixture
def m():
    mgr = TopicDBManager.__new__(TopicDBManager)
    mgr.physical_db = FakePhysical()
    mgr.config = {"asr_target_angle": 30}
    return mgr


def msg(d):
    return NS(data=json.dumps(d, ensure_ascii=False))


def kad(x, y, words="こんにちは"):
    return {"words": words, "scores": "0.9", "sep_port": 5562,
            "instance_id": 3, "x": x, "y": y, "z": 0.0}


def ssl(location, text="こんにちは", **kw):
    d = {"person_id": 7, "text": text, "confidence": 0.8,
         "azimuth": 0.0, "distance": 1.0, "location": location}
    d.update(kw)
    return d


def test_kad_front_is_asr(m):
    m.update_asr(msg(kad(0.0, 1.0)), vap_status=True)
    (e,) = m.physical_db.docs
    assert e["event"] == "asr"
    c = e["contents"]
    assert (c["source"], c["text"], c["confidence"], c["turn_end"]) == ("kad", "こんにちは", 0.9, True)
    assert c["instance_id"] == 3 and c["angle"] == pytest.approx(0.0)


def test_kad_side_is_outside(m):
    m.update_asr(msg(kad(1.0, 0.0)))
    assert m.physical_db.docs[0]["event"] == "asr_from_outside"


def test_ssl_front_is_asr(m):
    m.update_ssl_asr(msg(ssl([1.0, 0.1, 0.0])), vap_status=False)
    (e,) = m.physical_db.docs
    assert e["event"] == "asr"
    c = e["contents"]
    assert (c["source"], c["text"], c["instance_id"]) == ("ssl", "こんにちは", 7)
    assert "words" not in c and "sep_port" not in c
    assert "morph" not in c
    assert c["confidence"] == 0.8 and c["turn_end"] is False
    # ソース固有のフィールドも残す
    assert c["location"] == [1.0, 0.1, 0.0] and c["person_id"] == 7


def test_ssl_morph_is_kept(m):
    morph = {"surface": ["こんにちは"], "base_form": ["こんにちは"],
             "reading": ["こんにちは"], "pos": ["感動詞"], "span": ["こんにちは"]}
    m.update_ssl_asr(msg(ssl([1.0, 0.0, 0.0], morph=morph)))
    assert m.physical_db.docs[0]["contents"]["morph"] == morph


def test_ssl_left_is_outside(m):
    m.update_ssl_asr(msg(ssl([0.0, 1.0, 0.0])))
    assert m.physical_db.docs[0]["event"] == "asr_from_outside"


def test_ssl_without_location_uses_azimuth(m):
    d = ssl(None, azimuth=-1.2)
    del d["location"]
    m.update_ssl_asr(msg(d))
    c = m.physical_db.docs[0]["contents"]
    assert c["angle"] == pytest.approx(68.75, abs=0.01)


def test_empty_text_is_not_registered(m):
    m.update_ssl_asr(msg(ssl([1.0, 0.0, 0.0], text="  ")))
    m.update_asr(msg(kad(0.0, 1.0, words="")))
    assert m.physical_db.docs == []
