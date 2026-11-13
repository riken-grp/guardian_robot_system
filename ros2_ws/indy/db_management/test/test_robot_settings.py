"""Reading the robot settings (config DB 9100 via pyindy)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db_management.mongo_utils as mu  # noqa: E402
import db_management.recognition_available_region_checker as rc  # noqa: E402

REGIONS = [{"type": "rectangle", "region_id": "hall", "locations": [[0, 0], [2, 2]]}]


def test_uses_pyindy_load_robot_settings(monkeypatch):
    calls = []

    def load_robot_settings(robot_id=None):
        calls.append(robot_id)
        return {"asr_target_angle": 30, "recognition_available_regions": REGIONS}

    monkeypatch.setattr(mu, "load_robot_settings", load_robot_settings)
    assert mu.load_config()["asr_target_angle"] == 30
    assert calls == [None]  # robot_id: ROBOT_NAME (resolved by pyindy)


def test_pyindy_returns_nothing_or_raises(monkeypatch):
    monkeypatch.setattr(mu, "load_robot_settings", lambda: None)
    assert mu.load_config() == {}

    def boom():
        raise RuntimeError("config DB down")

    monkeypatch.setattr(mu, "load_robot_settings", boom)
    assert mu.load_config() == {}  # never raises


def test_region_checker(monkeypatch):
    monkeypatch.setattr(rc, "load_config", lambda: {"recognition_available_regions": REGIONS})
    c = rc.RecognitionAvailableRegionChecker()
    assert c.is_in((1, 1)) == (True, "hall")
    assert c.is_in((3, 1)) == (False, None)
    # indy3e: no regions -> everywhere
    monkeypatch.setattr(rc, "load_config", lambda: {})
    assert rc.RecognitionAvailableRegionChecker().is_in((99, 99)) == (True, None)
