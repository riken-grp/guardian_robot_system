"""rosNAV_smr: a navigation is held until the rover becomes idle (no sleep)."""

import json
import time

import pytest
import rclpy
from common_msgs.msg import StringStamped
from std_msgs.msg import String

import robot.rosNAV_smr as rn


class FakeNavMan:
    """pyindy NavigationManager substitute: a queue of navigations."""

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
    """Publisher substitute: rover/stop, rover/rotate, ..."""

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
    n.rover_init = True  # skip the initial pose
    n.sent = []
    n.stop_pub = Recorder("stop", n.sent)
    n.rot_pub = Recorder("rotate", n.sent)
    n.mov_pub = Recorder("move", n.sent)
    n.nav_pub = Recorder("navigate", n.sent)
    yield n
    n.destroy_node()
    rclpy.shutdown()


def rover(n, **state):
    """rover/butukusa as update_error receives it."""
    n.update_error(StringStamped(data=json.dumps(state)))


def tick(n):
    t0 = time.monotonic()
    n.timer_callback()
    return time.monotonic() - t0


def test_waits_for_idle_without_sleeping(node):
    rover(node, mode="executing", arrived=False)  # just after a stop
    i = node.mng.add({"rotate": 0.622})
    assert tick(node) < 0.1  # no sleep in the callback
    assert node.mng.status[i] == "is_playing"
    assert node.sent == [("stop", None)]  # rover/stop once
    assert tick(node) < 0.1  # still not idle: keep waiting
    assert node.sent == [("stop", None)]  # no more stop, not started

    rover(node, mode="idle")  # update_error runs between the timer callbacks
    tick(node)
    assert node.sent[-1][0] == "rotate"
    assert node.sent[-1][1] == pytest.approx(0.622)
    assert node.mng.status[i] == "is_playing"  # executing (not failed)
    assert node.p is True and node.waiting_idle_since is None


def test_idle_starts_at_once_even_if_not_arrived(node):
    rover(node, mode="idle", arrived=False)
    i = node.mng.add({"move": 1.0})
    assert tick(node) < 0.1
    assert node.sent == [("move", 1.0)]  # no stop, no wait
    assert node.mng.status[i] == "is_playing" and node.p is True


def test_fails_after_timeout(node, monkeypatch):
    monkeypatch.setattr(rn, "IDLE_WAIT_TIMEOUT", 0.3)
    rover(node, mode="executing")
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    time.sleep(0.1)
    tick(node)
    assert node.mng.status[i] == "is_playing"
    time.sleep(0.3)
    tick(node)
    assert node.mng.status[i] == "failed"
    assert node.waiting_idle_since is None and node.p is False
    # the next navigation is handled normally
    rover(node, mode="idle")
    j = node.mng.add({"rotate": 2.0})
    tick(node)
    assert ("rotate", 2.0) in node.sent and node.mng.status[j] == "is_playing"
    assert ("rotate", 1.0) not in node.sent


def test_stop_while_waiting(node):
    rover(node, mode="executing")
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    node.msg_callback(String(data="stop"))
    assert node.mng.status[i] == "stopped"
    assert node.waiting_idle_since is None
    rover(node, mode="idle")
    tick(node)  # does not start afterwards
    assert ("rotate", 1.0) not in node.sent
    assert node.mng.status[i] == "stopped"


def test_stop_while_executing(node):
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    node.msg_callback(String(data="stop"))
    assert node.mng.status[i] == "stopped" and node.p is False


def test_deactivate_while_waiting(node):
    rover(node, mode="executing")
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    node.msg_callback(String(data="deactivate nav"))
    assert node.mng.status[i] == "ignored" and node.waiting_idle_since is None
    rover(node, mode="idle")
    tick(node)
    assert ("rotate", 1.0) not in node.sent


def test_deactivated_is_ignored_without_waiting(node):
    node.msg_callback(String(data="deactivate nav"))
    rover(node, mode="executing")
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    assert node.mng.status[i] == "ignored" and node.waiting_idle_since is None
    assert node.sent == []


def test_error_recovery_does_not_sleep(node):
    rover(node, mode="error", error_description="bumper")
    for _ in range(3):
        assert tick(node) < 0.1
    # rover/stop at most every ERROR_RECOVERY_INTERVAL
    assert node.sent == [("stop", None)]
    # a navigation sent during the error is held, and starts after recovery
    i = node.mng.add({"rotate": 1.0})
    tick(node)
    assert node.waiting_idle_since is not None
    rover(node, mode="idle")
    tick(node)
    assert ("rotate", 1.0) in node.sent and node.mng.status[i] == "is_playing"


def test_nav_error_waits_without_taking_the_next(node):
    # nav2 failure: rover_wrapper returns to idle in about 1 s by itself
    rover(node, mode="error", error_source="nav", error_description="goal aborted")
    i = node.mng.add({"rotate": 1.0})
    assert tick(node) < 0.1
    assert node.mng.status == {} and node.sent == []  # not taken, no stop
    rover(node, mode="idle", error_source="")
    tick(node)
    assert ("rotate", 1.0) in node.sent and node.mng.status[i] == "is_playing"


def test_stop_sends_rover_stop(node):
    node.mng.add({"rotate": 1.0})
    tick(node)
    node.msg_callback(String(data="stop"))
    assert node.sent[-1] == ("stop", None)
