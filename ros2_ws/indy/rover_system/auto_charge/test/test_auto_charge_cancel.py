"""auto_charge: dock_cancel stops the rover and a dock_start received meanwhile does not restart it."""

import threading
import time

import pytest
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import Empty

from auto_charge.auto_charge import AutoCharge


class World(threading.Thread):
    """Spins the AutoCharge node and a test node that plays the station finder."""

    def __init__(self):
        super().__init__(daemon=True)
        self.node = AutoCharge()
        self.peer = rclpy.create_node("auto_charge_test_peer")
        self.start_pub = self.peer.create_publisher(Empty, "auto_charge/dock_start", 10)
        self.cancel_pub = self.peer.create_publisher(Empty, "auto_charge/dock_cancel", 10)
        self.pose_pub = self.peer.create_publisher(PoseStamped, "auto_charge/dock_target_pose", 10)
        self.events = []  # (time, "stop" | "move")
        self.peer.create_subscription(Empty, "rover/stop", lambda m: self.events.append((time.monotonic(), "stop")), 10)
        self.peer.create_subscription(Twist, "rover/cmd_vel", self._cmd_vel, 10)
        self.peer.create_timer(0.1, self._station)  # the station stays visible
        self.executor = MultiThreadedExecutor(num_threads=6)
        self.executor.add_node(self.node)
        self.executor.add_node(self.peer)
        self.running = True

    def _cmd_vel(self, msg):
        if msg.linear.x != 0.0 or msg.angular.z != 0.0:
            self.events.append((time.monotonic(), "move"))

    def _station(self):
        pose = PoseStamped()
        pose.pose.position.x = -1.5  # 1.5 m away
        pose.pose.position.y = 0.05  # slightly to the side
        pose.pose.orientation.w = 1.0
        self.pose_pub.publish(pose)

    def run(self):
        while self.running and rclpy.ok():
            self.executor.spin_once(timeout_sec=0.05)

    def wait_until(self, cond, timeout=3.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def moves_after(self, t):
        return [e for e in self.events if e[0] > t and e[1] == "move"]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("ROBOT_NAME", "testbot")
    rclpy.init()
    w = World()
    w.start()
    time.sleep(0.5)  # discovery
    yield w
    w.node.cancel_requested = True  # end a docking still running
    w.wait_until(lambda: not w.node.docking_busy)
    w.running = False
    w.join(2.0)
    w.node.destroy_node()
    w.peer.destroy_node()
    rclpy.shutdown()


def start(w):
    w.start_pub.publish(Empty())
    assert w.wait_until(lambda: w.node.docking_busy)
    assert w.wait_until(lambda: w.moves_after(0.0))  # the rover is driven


def test_dock_cancel_stops_the_rover(world):
    start(world)
    world.cancel_pub.publish(Empty())
    assert world.wait_until(lambda: not world.node.docking_busy, timeout=1.0)
    t_end = time.monotonic()
    assert any(kind == "stop" for _, kind in world.events)
    time.sleep(1.0)
    assert world.moves_after(t_end) == [] and not world.node.docking_busy


def test_dock_start_during_docking_does_not_restart(world):
    start(world)
    for _ in range(3):
        world.start_pub.publish(Empty())  # rejected at once, not queued
        time.sleep(0.1)
    world.cancel_pub.publish(Empty())
    assert world.wait_until(lambda: not world.node.docking_busy, timeout=1.0)
    t_end = time.monotonic()
    time.sleep(1.0)
    assert not world.node.docking_busy and world.moves_after(t_end) == []


def test_docking_again_after_cancel(world):
    start(world)
    world.cancel_pub.publish(Empty())
    assert world.wait_until(lambda: not world.node.docking_busy, timeout=1.0)
    start(world)  # the old cancel request is not carried over
    time.sleep(0.5)
    assert world.node.docking_busy
