"""Common test setup for the robot package."""

import sys
import types

import pytest

try:
    import nav2_msgs.action  # noqa: F401
except ImportError:
    # nav2 is not installed on the development PC: rosNAV_smr only needs the
    # NavigateToPose type (the action client is replaced below)
    class _NavigateToPose:
        class Goal:
            pass

    nav2_msgs = types.ModuleType("nav2_msgs")
    nav2_msgs.action = types.ModuleType("nav2_msgs.action")
    nav2_msgs.action.NavigateToPose = _NavigateToPose
    sys.modules["nav2_msgs"] = nav2_msgs
    sys.modules["nav2_msgs.action"] = nav2_msgs.action


class FakeFuture:
    def __init__(self):
        self.callbacks = []
        self._result = None
        self._exception = None

    def add_done_callback(self, cb):
        self.callbacks.append(cb)

    def set_result(self, result):
        self._result = result
        for cb in self.callbacks:
            cb(self)

    def set_exception(self, e):
        self._exception = e
        for cb in self.callbacks:
            cb(self)

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result


class FakeGoalHandle:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.result_future = FakeFuture()
        self.cancel_requests = 0

    def get_result_async(self):
        return self.result_future

    def cancel_goal_async(self):
        self.cancel_requests += 1
        return FakeFuture()

    def finish(self, status):
        self.result_future.set_result(types.SimpleNamespace(status=status, result=None))


class FakeActionClient:
    """rclpy ActionClient substitute: goals are answered by the test."""

    def __init__(self, node, action_type, name):
        self.action_type, self.name = action_type, name
        self.ready = True
        self.goals = []  # FakeFuture of the goal responses

    def server_is_ready(self):
        return self.ready

    def send_goal_async(self, goal):
        future = FakeFuture()
        self.goals.append(future)
        return future


@pytest.fixture(autouse=True)
def fake_action_client(monkeypatch):
    import robot.rosNAV_smr as rn

    monkeypatch.setattr(rn, "ActionClient", FakeActionClient)
