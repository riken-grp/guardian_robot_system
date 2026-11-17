"""navigate_to_charge_server: succeed only when charging continues and auto_charge has stopped."""

import sys
import threading
import time
import types

import pytest
import rclpy
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Bool

try:
    import nav2_msgs.action  # noqa: F401
except ImportError:
    # nav2 is not installed on the development PC: the server only needs the
    # NavigateToPose type (the action server is replaced below)
    class _NavigateToPose:
        class Goal:
            pass

        class Result:
            pass

        class Feedback:
            pass

    nav2_msgs = types.ModuleType("nav2_msgs")
    nav2_msgs.action = types.ModuleType("nav2_msgs.action")
    nav2_msgs.action.NavigateToPose = _NavigateToPose
    sys.modules["nav2_msgs"] = nav2_msgs
    sys.modules["nav2_msgs.action"] = nav2_msgs.action

import auto_charge.navigate_to_charge_server as srv  # noqa: E402

NOT_CHARGING = 0.036  # current observed on indy1e 0.3 m in front of the station
CHARGING = 0.0


class FakeGoalHandle:
    def __init__(self):
        self.is_cancel_requested = False
        self.state = None

    def publish_feedback(self, msg):
        pass

    def succeed(self):
        self.state = "succeeded"

    def abort(self):
        self.state = "aborted"

    def canceled(self):
        self.state = "canceled"


class Recorder:
    def __init__(self):
        self.count = 0
        self.on_publish = None  # plays auto_charge: called with the count

    def publish(self, msg):
        self.count += 1
        if self.on_publish is not None:
            self.on_publish(self.count)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("ROBOT_NAME", "testbot")
    monkeypatch.setattr(srv, "ActionServer", lambda *a, **k: None)
    rclpy.init()
    n = srv.NavigateToChargeServer()
    n.docking_start_wait_timeout = 1.0
    n.docking_timeout = 5.0
    n.charge_confirm_time = 0.5
    n.charge_settle_time = 0.3
    n.stop_wait_timeout = 1.0
    n.cancel_confirm_timeout = 1.0
    n.dock_start_pub = Recorder()
    n.dock_cancel_pub = Recorder()
    yield n
    n.destroy_node()
    rclpy.shutdown()


class Run:
    """execute_callback in a thread; the test plays auto_charge and the battery."""

    def __init__(self, node):
        self.node = node
        self.gh = FakeGoalHandle()
        self.thread = threading.Thread(target=node.execute_callback, args=(self.gh,))
        self.thread.start()

    def docking(self, value):
        self.node.dock_status_callback(Bool(data=value))

    def current(self, value):
        self.node.battery_callback(BatteryState(current=value))

    def wait(self, timeout=10.0):
        self.thread.join(timeout)
        assert not self.thread.is_alive()
        return self.gh.state


def test_momentary_contact_is_not_success(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.3)
    r.current(CHARGING)  # the contacts touch for a moment while auto_charge retries
    time.sleep(0.2)
    r.current(NOT_CHARGING)
    time.sleep(0.4)
    r.current(CHARGING)  # the confirmation time starts again
    time.sleep(0.3)
    r.current(NOT_CHARGING)
    time.sleep(0.4)
    assert r.gh.state is None and server.dock_cancel_pub.count == 0
    r.docking(False)  # auto_charge gives up
    assert r.wait() == "aborted"


def test_success_stops_auto_charge(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.current(CHARGING)
    time.sleep(0.9)
    # charging continued: auto_charge is told to stop, the goal waits for it
    assert server.dock_cancel_pub.count == 1 and r.gh.state is None
    time.sleep(0.3)
    assert r.gh.state is None
    r.docking(False)
    t0 = time.monotonic()
    assert r.wait() == "succeeded"
    assert time.monotonic() - t0 >= 0.25  # charging is checked after the stop


def test_success_when_auto_charge_finishes_by_itself(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.current(CHARGING)
    time.sleep(0.1)
    r.docking(False)  # auto_charge: "docking complete"
    assert r.wait() == "succeeded"
    assert server.dock_cancel_pub.count == 0


def test_charging_stops_after_auto_charge_stopped(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.current(CHARGING)
    time.sleep(0.9)
    r.docking(False)
    r.current(NOT_CHARGING)
    assert r.wait() == "aborted"


def test_auto_charge_does_not_stop(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.current(CHARGING)
    assert r.wait() == "aborted"
    # charging confirmed, did not stop, and dock_cancel sent again while checking
    assert server.dock_cancel_pub.count >= 3


def test_no_battery_message_is_not_charging(server):
    r = Run(server)
    assert r.wait() == "aborted"  # docking did not start in time
    assert server.dock_cancel_pub.count == 1


def test_already_charging(server):
    r = Run(server)
    r.current(CHARGING)  # auto_charge replies "Charging now" and does not start
    assert r.wait() == "succeeded"


def stops_on(server, r, nth):
    """auto_charge stops when it receives the nth dock_cancel."""
    server.dock_cancel_pub.on_publish = lambda count: r.docking(False) if count >= nth else None


def test_cancel(server):
    r = Run(server)
    stops_on(server, r, 1)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.gh.is_cancel_requested = True
    assert r.wait() == "canceled"
    assert server.dock_cancel_pub.count == 1


def test_timeout_stops_auto_charge(server):
    server.docking_timeout = 1.5
    r = Run(server)
    stops_on(server, r, 1)
    r.current(NOT_CHARGING)
    r.docking(True)  # auto_charge keeps retrying
    t0 = time.monotonic()
    assert r.wait() == "aborted"
    assert time.monotonic() - t0 >= 1.3
    assert server.dock_cancel_pub.count == 1 and server.is_docking is False


def test_dock_cancel_sent_again_until_auto_charge_stops(server):
    server.docking_timeout = 1.0
    r = Run(server)
    stops_on(server, r, 2)  # the first dock_cancel is lost
    r.current(NOT_CHARGING)
    r.docking(True)
    assert r.wait() == "aborted"
    assert server.dock_cancel_pub.count == 2 and server.is_docking is False


def test_cancel_when_auto_charge_does_not_stop(server):
    r = Run(server)
    r.current(NOT_CHARGING)
    r.docking(True)
    time.sleep(0.2)
    r.gh.is_cancel_requested = True
    assert r.wait() == "canceled"  # gives up after cancel_confirm_timeout
    assert server.dock_cancel_pub.count >= 2
