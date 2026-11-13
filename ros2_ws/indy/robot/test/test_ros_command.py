import threading
import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import Int32, String

import robot.rosCommand as rc
from robot.rosCommand import make_message


# ---------------------------------------------------------------- make_message
def test_int32_conversion():
    assert make_message(20, "std_msgs/msg/Int32").data == 20
    assert make_message("20", "std_msgs/msg/Int32").data == 20
    assert make_message(" 35 ", "std_msgs/msg/Int32").data == 35
    assert make_message(20.0, "std_msgs/msg/Int32").data == 20
    assert make_message("", "std_msgs/msg/Int32").data == 0
    for bad in ["abc", "20.5", 20.5, True, [1], 2**31]:
        with pytest.raises(ValueError):
            make_message(bad, "std_msgs/msg/Int32")


def test_string_and_empty():
    assert make_message("activate", "std_msgs/msg/String").data == "activate"
    assert make_message(5, "std_msgs/msg/String").data == "5"
    # Empty has no data field: data is ignored
    make_message("anything", "std_msgs/msg/Empty")
    with pytest.raises(ValueError):
        make_message("x", "std_msgs/msg/Float32")


# ------------------------------------------------------------- node behaviour
class FakeActions:
    """pyindy ROSCommandManager substitute: a queue of ros_command actions."""

    def __init__(self, *args):
        self.queue = []
        self.status = {}
        self.done_time = {}
        self.lock = threading.Lock()
        self._ids = iter(range(1, 1000))

    def add(self, option):
        with self.lock:
            i = next(self._ids)
            self.queue.append({"_id": i, "option": option})
            return i

    def get_next(self):
        with self.lock:
            return self.queue.pop(0) if self.queue else False

    def set_status(self, _id, status):
        self.status[_id] = status
        self.done_time[_id] = time.monotonic()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(rc, "mngdb", FakeActions)
    rclpy.init()
    node = rc.polling_ros_command_node("testbot")
    listener = rclpy.create_node("listener")
    received = []
    listener.create_subscription(Int32, "robot/set_volume", lambda m: received.append(m.data), 10)
    ex = SingleThreadedExecutor()
    ex.add_node(node)
    ex.add_node(listener)
    stop = threading.Event()
    th = threading.Thread(target=lambda: [ex.spin_once(0.05) for _ in iter(stop.is_set, True)])
    th.start()
    yield node, node.mng, received
    stop.set()
    th.join()
    ex.shutdown()
    listener.destroy_node()
    node.destroy_node()
    rclpy.shutdown()


def wait_status(actions, i, timeout=5.0):
    t0 = time.monotonic()
    while i not in actions.status and time.monotonic() - t0 < timeout:
        time.sleep(0.01)
    return actions.status.get(i)


def test_publisher_reused_and_fast(env):
    node, actions, received = env
    vol = {"topic": "robot/set_volume", "topic_type": "std_msgs/msg/Int32"}

    t0 = time.monotonic()
    i = actions.add(dict(vol, data=20))
    assert wait_status(actions, i) == "done"
    first = actions.done_time[i] - t0

    times = []
    for v in ["30", 40, "50"]:
        t0 = time.monotonic()
        i = actions.add(dict(vol, data=v))
        assert wait_status(actions, i) == "done"
        times.append(actions.done_time[i] - t0)

    time.sleep(0.3)
    assert received == [20, 30, 40, 50]  # nothing lost, including the first
    assert len(node.publishers_by_topic) == 1
    assert first < 2.0
    print(f"first: {first:.3f}s, then: {[round(t, 3) for t in times]}")
    assert max(times) < 0.3, times


def test_failures_are_reported(env):
    node, actions, received = env
    bad = actions.add({"topic": "robot/set_volume", "topic_type": "std_msgs/msg/Int32", "data": "abc"})
    no_topic = actions.add({"topic_type": "std_msgs/msg/Int32", "data": 1})
    unknown = actions.add({"topic": "x", "topic_type": "std_msgs/msg/Float32", "data": 1})
    assert wait_status(actions, bad) == "failed"
    assert wait_status(actions, no_topic) == "failed"
    assert wait_status(actions, unknown) == "failed"


def test_no_subscriber_warns_and_done(env):
    node, actions, _ = env
    t0 = time.monotonic()
    i = actions.add({"topic": "robot/nobody", "topic_type": "std_msgs/msg/Empty", "data": "x"})
    assert wait_status(actions, i) == "done"
    assert 1.9 < actions.done_time[i] - t0 < 3.0  # waited up to the timeout once
    t0 = time.monotonic()
    i = actions.add({"topic": "robot/nobody", "topic_type": "std_msgs/msg/Empty"})
    assert wait_status(actions, i) == "done"
    assert actions.done_time[i] - t0 < 0.3  # no wait for the second time


def test_action_ctl_nav(env):
    node, actions, _ = env
    got = []
    node.create_subscription(String, "robot/action_ctl", lambda m: got.append(m.data), 10)
    i = actions.add({"data": "activate"})
    assert wait_status(actions, i) == "done"
    time.sleep(0.3)
    assert "activate nav" in got
