#!/usr/bin/env python3
"""Measure the rate and latency of the recognition pipeline.

For every topic in ``topics`` ("<topic>:<package>/msg/<Type>", the message
must have a ``header``) the node logs every ``period`` seconds:

* rate [Hz]
* delay: arrival time of the message minus the arrival time of the
  ``reference`` message (default: the first topic) with the *same stamp*.
  Since frame_gate_node gives all the results of a frame the stamp of its
  color image, this is the processing latency of each stage measured on this
  host only (independent of the clock offset between the robot and the
  server).  ``matched`` is the ratio of the messages for which the reference
  frame was seen.
* age: arrival time minus header stamp (includes the transport from the
  robot; meaningful only when the clocks are synchronized)

Example:
  ros2 run scene_understanding pipeline_monitor_node --ros-args -r __ns:=/indy3e
"""

import time
from collections import OrderedDict

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

DEFAULT_TOPICS = [
    "local_recog/color/image_raw/compressed:sensor_msgs/msg/CompressedImage",
    "local_recog/depth/image_raw/compressedDepth:sensor_msgs/msg/CompressedImage",
    "recog/object/tracked:recognition_msgs/msg/Objects",
    "recog/person/pose:recognition_msgs/msg/Persons",
    "recog/person/face:recognition_msgs/msg/Persons",
    "recog/person/pose/associated:recognition_msgs/msg/Persons",
    "recog/person/face/associated:recognition_msgs/msg/Persons",
    "recog/person/attributes:recognition_msgs/msg/Persons",
    "recog/person/hand_state:recognition_msgs/msg/Pointings",
    "recog/person/hand_waving:common_msgs/msg/StringStamped",
    "recog/person/looking_at:common_msgs/msg/StringStamped",
    "recog/person/noticed:common_msgs/msg/StringStamped",
]

# BEST_EFFORT matches both RELIABLE and BEST_EFFORT publishers
QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


def _summary(values):
    if not values:
        return "-"
    return f"{np.mean(values) * 1e3:.0f}/{np.max(values) * 1e3:.0f}ms"


class _TopicStats:
    def __init__(self):
        self.count = 0
        self.matched = 0
        self.delay = []
        self.age = []


class PipelineMonitorNode(Node):
    def __init__(self, name="pipeline_monitor_node"):
        super().__init__(name)
        self.declare_parameter("topics", DEFAULT_TOPICS)
        self.declare_parameter("reference", "")  # "": the first topic
        self.declare_parameter("period", 10.0)
        self.declare_parameter("history_sec", 10.0)  # reference arrivals kept

        specs = [s for s in self.get_parameter("topics").value if s]
        self.topics = []
        for spec in specs:
            topic, _, type_name = spec.rpartition(":")
            try:
                msg_type = get_message(type_name)
            except (AttributeError, ModuleNotFoundError, ValueError) as e:
                self.get_logger().error(f"unknown message type '{type_name}': {e}")
                continue
            self.topics.append(topic)
            self.create_subscription(
                msg_type, topic, lambda msg, t=topic: self._callback(t, msg), QOS
            )
        self.reference = self.get_parameter("reference").value or (
            self.topics[0] if self.topics else ""
        )
        self.history_ns = int(self.get_parameter("history_sec").value * 1e9)
        self.ref_arrival = OrderedDict()  # stamp [ns] -> arrival [s]
        self.stats = {t: _TopicStats() for t in self.topics}
        self.t_start = time.monotonic()
        self.create_timer(float(self.get_parameter("period").value), self._log)
        self.get_logger().info(f"reference: {self.reference}, topics: {self.topics}")

    def _callback(self, topic, msg):
        mono = time.monotonic()
        wall = time.time()
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        s = self.stats[topic]
        s.count += 1
        s.age.append(wall - stamp * 1e-9)
        if topic == self.reference:
            self.ref_arrival.setdefault(stamp, mono)
            while self.ref_arrival:
                oldest = next(iter(self.ref_arrival))
                if oldest >= stamp - self.history_ns:
                    break
                self.ref_arrival.popitem(last=False)
        if stamp in self.ref_arrival:
            s.matched += 1
            s.delay.append(mono - self.ref_arrival[stamp])

    def _log(self):
        now = time.monotonic()
        elapsed = max(now - self.t_start, 1e-6)
        width = max((len(t) for t in self.topics), default=0)
        lines = [
            f"[pipeline {elapsed:.0f}s] delay from '{self.reference}' "
            f"(avg/max), age = arrival - stamp (avg/max)"
        ]
        for topic in self.topics:
            s = self.stats[topic]
            matched = f"{100 * s.matched / s.count:.0f}%" if s.count else "-"
            lines.append(
                f"  {topic:<{width}}  {s.count / elapsed:5.1f} Hz  "
                f"delay {_summary(s.delay):>13} (matched {matched:>4})  "
                f"age {_summary(s.age):>13}"
            )
            self.stats[topic] = _TopicStats()
        self.get_logger().info("\n".join(lines))
        self.t_start = now


def main():
    rclpy.init()
    node = PipelineMonitorNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
