#!/usr/bin/env python3
"""Frame gate: hand the very same RGB-D frames to all the recognition nodes.

The recognition nodes (detection_and_tracking, body_pose, head_pose, ...) run
in separate processes at different speeds.  When each of them picks frames
from the 30 fps camera by itself, they process *different* frames, and
association_node has to join their results by approximate stamps (slop,
timeout), which costs latency and loses results.

This node matches the color and depth streams by stamp (``RgbdMatcher``) and
republishes the matched pairs.  The depth header stamp is replaced by the
color stamp, so that the pairs match exactly downstream and every result of a
frame carries the stamp of its color image.

``rate`` (default 0: no limit) caps the published frames per second
(``FrameRateLimiter``, a token bucket on the stamps).  The camera stream
arrives at < 10 Hz and irregularly (in bursts) over zenoh, so a cap would only
drop needed frames; set it to (or below) the rate of the slowest node only if
the stream arrives faster than the nodes can process.

The images are not decoded here (the messages are forwarded as they are).

It replaces the former topic_tools relays: over zenoh-bridge-ros2dds the
camera stream crosses the network once per host whatever the number of local
subscribers, so the relays were not needed to save bandwidth.

Topics:
  in_color_topic   (sensor_msgs/CompressedImage)  camera color (jpeg)
  in_depth_topic   (sensor_msgs/CompressedImage)  aligned depth (compressedDepth)
  out_color_topic  (sensor_msgs/CompressedImage)  selected color frames
  out_depth_topic  (sensor_msgs/CompressedImage)  depth of the selected frames
                                                  (stamp = color stamp)
"""

import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.qos import (HistoryPolicy, QoSProfile, ReliabilityPolicy,
                       qos_profile_sensor_data)
from sensor_msgs.msg import CompressedImage

from .rgbd_matcher import FrameRateLimiter, RgbdMatcher

# Output: RELIABLE (matches both RELIABLE and BEST_EFFORT subscribers) so that
# a lost fragment of a large depth image does not make the nodes see
# different frames; a small KEEP_LAST queue keeps a slow subscriber on the
# latest frames.
OUT_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=2,
)


def stamp_ns(msg):
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


class FrameGateNode(Node):
    def __init__(self, name="frame_gate_node"):
        super().__init__(name)
        any_number = ParameterDescriptor(dynamic_typing=True)
        # max selected frames per second (<= 0: every matched frame)
        self.declare_parameter("rate", 0.0, any_number)
        # frames that may pass in a row after a gap (token bucket size)
        self.declare_parameter("burst", 3.0, any_number)
        # max color / depth stamp difference [s]
        self.declare_parameter("rgbd_slop", 0.1, any_number)
        self.declare_parameter("rgbd_buffer_duration", 2.0, any_number)  # [s]
        self.declare_parameter("stats_period", 10.0, any_number)  # [s], <= 0: no log

        self.rate = float(self.get_parameter("rate").value)
        self.matcher = RgbdMatcher(
            slop_sec=float(self.get_parameter("rgbd_slop").value),
            buffer_sec=float(self.get_parameter("rgbd_buffer_duration").value),
        )
        self.limiter = FrameRateLimiter(
            self.rate, burst=float(self.get_parameter("burst").value)
        )
        self.n_pairs = 0
        self.n_published = 0
        self.t_stats = time.monotonic()

        self.pub_color = self.create_publisher(
            CompressedImage, "out_color_topic", OUT_QOS
        )
        self.pub_depth = self.create_publisher(
            CompressedImage, "out_depth_topic", OUT_QOS
        )
        self.create_subscription(
            CompressedImage, "in_color_topic", self._color_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            CompressedImage, "in_depth_topic", self._depth_callback,
            qos_profile_sensor_data,
        )
        period = float(self.get_parameter("stats_period").value)
        if period > 0:
            self.create_timer(period, self._log_stats)
        self.get_logger().info(
            f"frame gate: rate={self.rate} Hz "
            f"in: {self.resolve_topic_name('in_color_topic')}, "
            f"{self.resolve_topic_name('in_depth_topic')} -> "
            f"out: {self.resolve_topic_name('out_color_topic')}, "
            f"{self.resolve_topic_name('out_depth_topic')}"
        )

    def _check_time_jump(self, t):
        # rosbag loop etc.: drop the buffers and restart the selection
        if self.limiter.jumped_back(t):
            self.get_logger().warn("timestamp jumped back; resetting the frame gate")
            self.matcher.reset()
            self.limiter.reset()

    def _color_callback(self, msg):
        t = stamp_ns(msg)
        self._check_time_jump(t)
        self._handle(self.matcher.add_color(t, msg, time.monotonic()))

    def _depth_callback(self, msg):
        t = stamp_ns(msg)
        self._check_time_jump(t)
        self._handle(self.matcher.add_depth(t, msg, time.monotonic()))

    def _handle(self, pair):
        if pair is None:
            return
        self.n_pairs += 1
        color, depth = pair
        if not self.limiter.accept(stamp_ns(color)):
            return
        # same stamp as the color frame: exact match downstream
        depth.header.stamp = color.header.stamp
        self.pub_color.publish(color)
        self.pub_depth.publish(depth)
        self.n_published += 1

    def _log_stats(self):
        now = time.monotonic()
        elapsed = max(now - self.t_stats, 1e-6)
        stats = self.matcher.reset_stats()
        self.get_logger().info(
            f"[gate {elapsed:.0f}s] out={self.n_published / elapsed:.1f} Hz "
            f"(pairs={self.n_pairs / elapsed:.1f} Hz) "
            + stats.format(elapsed, len(self.matcher.colors), len(self.matcher.depths))
        )
        self.n_pairs = 0
        self.n_published = 0
        self.t_stats = now


def main():
    rclpy.init()
    node = FrameGateNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
