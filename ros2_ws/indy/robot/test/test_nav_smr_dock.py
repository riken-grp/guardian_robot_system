"""rosNAV_smr: {"dock": true} calls navigate_to_charge and waits for its result."""

import json
import time

import pytest
import rclpy
from action_msgs.msg import GoalStatus
from common_msgs.msg import StringStamped
from std_msgs.msg import String

import robot.rosNAV_smr as rn
from conftest import FakeGoalHandle

DOCK = {"dock": True}


class FakeNavMan:
    def __init__(self, *args):
        self.queue = []
        self.status = {}
        self._ids = iter(range(1, 1000))

    def add(self, option):
        i = next(self._ids)
        self.queue.append({"_id": i, "option": option})
        return i

    def get_next(self):
        return self.queue.pop(0) if self.queue else False

    def set_status(self, _id, status):
        self.status[_id] = status


class FakeStatus:
    def __init__(self, *args):
        pass

    def set_status(self, state):
        pass

    def get_status(self):
        return None


class Recorder:
    def __init__(self, name, sent):
        self.name, self.sent = name, sent

    def publish(self, msg):
        self.sent.append((self.name, getattr(msg, "data", None)))


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setattr(rn, "NavMan", FakeNavMan)
    monkeypatch.setattr(rn, "StatusManager", FakeStatus)
    rclpy.init()
    n = rn.polling_nav_node("testbot")
    n.timer.cancel()  # callbacks are driven by the test
    n.rover_init = True
    n.sent = []
    for attr, name in (("stop_pub", "stop"), ("rot_pub", "rotate"), ("mov_pub", "move"),
                       ("nav_pub", "navigate"), ("mpub", "action_ctl")):
        setattr(n, attr, Recorder(name, n.sent))
    yield n
    n.destroy_node()
    rclpy.shutdown()


def rover(n, **state):
    n.update_error(StringStamped(data=json.dumps(state)))


def tick(n):
    t0 = time.monotonic()
    n.timer_callback()
    return time.monotonic() - t0


def start_dock(n):
    """Add a dock navigation and take it; returns (id, goal response future)."""
    i = n.mng.add(DOCK)
    assert tick(n) < 0.1
    assert len(n.dock_client.goals) == 1
    return i, n.dock_client.goals[-1]


def accept(future):
    gh = FakeGoalHandle()
    future.set_result(gh)
    return gh


def ctl(n):
    return [d for name, d in n.sent if name == "action_ctl"]


def test_client(node):
    assert node.dock_client.name == "navigate_to_charge"


def test_done_when_charging_starts(node):
    i, f = start_dock(node)
    assert node.mng.status[i] == "is_playing" and node.p is True
    gh = accept(f)
    rover(node, mode="idle")  # the rover mode does not finish a docking
    for _ in range(20):
        tick(node)
    assert node.mng.status[i] == "is_playing"
    gh.finish(GoalStatus.STATUS_SUCCEEDED)
    tick(node)
    assert node.mng.status[i] == "done" and node.p is False
    assert "navigation: done" in ctl(node)


@pytest.mark.parametrize("status", [GoalStatus.STATUS_ABORTED, GoalStatus.STATUS_CANCELED])
def test_failed(node, status):
    i, f = start_dock(node)
    accept(f).finish(status)
    tick(node)
    assert node.mng.status[i] == "failed" and node.p is False
    assert "navigation: failed" in ctl(node)


def test_rejected(node):
    i, f = start_dock(node)
    f.set_result(FakeGoalHandle(accepted=False))
    tick(node)
    assert node.mng.status[i] == "failed" and node.p is False


def test_no_server_fails_at_once(node):
    node.dock_client.ready = False
    i = node.mng.add(DOCK)
    assert tick(node) < 0.1
    assert node.mng.status[i] == "failed" and node.p is False
    assert node.dock_client.goals == []


def test_stop_cancels_the_goal(node):
    i, f = start_dock(node)
    gh = accept(f)
    node.msg_callback(String(data="stop"))
    assert gh.cancel_requests == 1
    assert node.mng.status[i] == "stopped" and node.p is False
    # the canceled result arriving later does not change the status
    gh.finish(GoalStatus.STATUS_CANCELED)
    tick(node)
    assert node.mng.status[i] == "stopped"


def test_stop_before_accepted(node):
    i, f = start_dock(node)
    node.msg_callback(String(data="stop"))
    gh = accept(f)  # accepted after the stop: canceled at once
    assert gh.cancel_requests == 1
    assert node.mng.status[i] == "stopped"


def test_dock_while_deactivated(node):
    node.msg_callback(String(data="deactivate nav"))
    i, f = start_dock(node)
    accept(f).finish(GoalStatus.STATUS_SUCCEEDED)
    tick(node)
    assert node.mng.status[i] == "done"
    # activate is not changed by the docking
    assert node.activate is False
    j = node.mng.add({"rotate": 1.0})
    tick(node)
    assert node.mng.status[j] == "ignored"


def test_dock_failure_while_deactivated_is_failed(node):
    node.msg_callback(String(data="deactivate nav"))
    node.dock_client.ready = False
    i = node.mng.add(DOCK)
    tick(node)
    assert node.mng.status[i] == "failed"


def test_dock_waits_for_idle_even_if_deactivated(node):
    node.msg_callback(String(data="deactivate nav"))
    rover(node, mode="executing")
    i = node.mng.add(DOCK)
    tick(node)
    assert node.waiting_idle_since is not None and node.dock_client.goals == []
    node.msg_callback(String(data="deactivate nav"))  # a held dock is not ignored
    assert node.mng.status[i] == "is_playing"
    rover(node, mode="idle")
    tick(node)
    assert len(node.dock_client.goals) == 1


def test_other_navigation_waits_until_dock_ends(node):
    i, f = start_dock(node)
    gh = accept(f)
    j = node.mng.add({"rotate": 1.0})
    for _ in range(10):
        tick(node)
    assert j not in node.mng.status  # still waiting in the queue
    assert ("rotate", 1.0) not in node.sent
    gh.finish(GoalStatus.STATUS_SUCCEEDED)
    tick(node)
    rover(node, mode="idle")
    tick(node)
    assert ("rotate", 1.0) in node.sent and node.mng.status[j] == "is_playing"


def test_no_result_safeguard(node, monkeypatch):
    monkeypatch.setattr(rn, "DOCK_RESULT_TIMEOUT", 0.2)
    i, f = start_dock(node)
    gh = accept(f)
    time.sleep(0.3)
    tick(node)
    assert node.mng.status[i] == "failed" and gh.cancel_requests == 1


def test_next_dock_ignores_old_results(node):
    i, f = start_dock(node)
    old = accept(f)
    node.msg_callback(String(data="stop"))
    j = node.mng.add(DOCK)
    tick(node)
    new = accept(node.dock_client.goals[-1])
    old.finish(GoalStatus.STATUS_ABORTED)  # the old goal's result
    tick(node)
    assert node.mng.status[j] == "is_playing"
    new.finish(GoalStatus.STATUS_SUCCEEDED)
    tick(node)
    assert node.mng.status[j] == "done"
