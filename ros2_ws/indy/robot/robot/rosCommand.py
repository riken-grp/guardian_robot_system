#!/usr/bin/python3
import json
import os
import time

import rclpy
from pyindy.mongo import ROSCommandManager as mngdb
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Empty, Int32, String

TOPIC_TYPES = {
    "std_msgs/msg/String": String,
    "std_msgs/msg/Int32": Int32,
    "std_msgs/msg/Empty": Empty,
}

# waiting time for a subscriber on a newly created publisher [s]
SUBSCRIBER_WAIT_TIMEOUT = 2.0
SUBSCRIBER_WAIT_INTERVAL = 0.05


def make_message(data, topic_type):
    """Build a message of topic_type from the "data" of the command.

    Raises ValueError when the type is unknown or the data cannot be converted
    (e.g. "abc" for Int32).
    """
    if topic_type not in TOPIC_TYPES:
        raise ValueError(f"unsupported topic_type: {topic_type}")
    msg = TOPIC_TYPES[topic_type]()
    if topic_type == "std_msgs/msg/Empty":
        return msg  # Empty has no data field: ignore "data"
    if data is None or data == "":
        return msg  # default value ("" / 0), as before
    if topic_type == "std_msgs/msg/Int32":
        if isinstance(data, bool):
            raise ValueError(f"invalid Int32 data: {data!r}")
        try:
            # 20, "20", " 20 ", 20.0 -> 20 (but not 20.5)
            value = float(data) if isinstance(data, str) else data
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"invalid Int32 data: {data!r}") from None
        if not -(2**31) <= value < 2**31:
            raise ValueError(f"Int32 data out of range: {value}")
        msg.data = value
    else:  # String
        msg.data = str(data)
    return msg


class polling_ros_command_node(Node):
    def __init__(self, robot_name="none"):
        super().__init__("ros_command_from_MongoDB")
        #
        print("Start ros command node for " + robot_name)
        self.robot_name = robot_name
        #
        self.declare_parameter("mongo_port", 0)
        self.mongo_port = (
            self.get_parameter("mongo_port").get_parameter_value().integer_value
        )
        self.get_logger().info("mongo_port: " + str(self.mongo_port))
        #
        self.declare_parameter("mongo_uri", "")
        self.mongo_uri = (
            self.get_parameter("mongo_uri").get_parameter_value().string_value
        )
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        #
        self.mng = mngdb(self.mongo_uri, self.mongo_port, self.robot_name)
        timer_period = 0.1
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.msub = self.create_subscription(
            String, "robot/action_ctl", self.msg_callback, 10
        )
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        # (topic_name, topic_type) -> publisher, kept for reuse
        self.publishers_by_topic = {}
        self.get_logger().info("start ros command node " + robot_name)

    #
    def action_ctl_pub(self, text):
        msg = String()
        msg.data = text
        self.mpub.publish(msg)
        return True

    def _publisher(self, topic_name, topic_type, wait_timeout=SUBSCRIBER_WAIT_TIMEOUT):
        """Publisher of the topic (created and connected on first use).

        Publishers are kept and reused: only a newly created one waits until
        a subscriber is matched (up to wait_timeout), so that the first
        message is not lost.  The DDS discovery runs in the background, so
        get_subscription_count() is updated without spinning.
        """
        key = (topic_name, topic_type)
        pub = self.publishers_by_topic.get(key)
        if pub is None:
            pub = self.create_publisher(TOPIC_TYPES[topic_type], topic_name, 10)
            self.publishers_by_topic[key] = pub
            deadline = time.monotonic() + wait_timeout
            while pub.get_subscription_count() == 0 and time.monotonic() < deadline:
                time.sleep(SUBSCRIBER_WAIT_INTERVAL)
            if pub.get_subscription_count() == 0:
                self.get_logger().warn(
                    f"no subscriber on {pub.topic_name} yet, publishing anyway"
                )
        return pub

    def ros_cmd_pub(self, data, topic_name, topic_type):
        if topic_type not in TOPIC_TYPES:
            self.get_logger().error(f"unsupported topic_type: {topic_type}")
            return False
        try:
            msg = make_message(data, topic_type)
        except ValueError as e:
            self.get_logger().error(f"{topic_name}: {e}")
            return False
        self._publisher(topic_name, topic_type).publish(msg)
        return True

    #
    def timer_callback(self):
        msg = self.mng.get_next()
        # self.get_logger().info('time callback')
        if msg == False:
            return False
        try:
            ok = self.execute(msg["option"])
        except Exception as e:
            # never leave the action pending: RISM waits for done / failed
            self.get_logger().error(f"ros_command failed: {e!r}")
            ok = False
        self.mng.set_status(msg["_id"], "done" if ok else "failed")
        return ok

    def execute(self, cmd):
        """Run one ros_command; returns True on success."""
        if "topic_type" in cmd:
            if "topic" not in cmd:
                self.get_logger().error(f"ros_command without topic: {cmd}")
                return False
            return self.ros_cmd_pub(cmd.get("data", ""), cmd["topic"], cmd["topic_type"])
        if cmd["data"] == "stop":
            # ActionManager.stop_all() はtopic_typeなしで"stop"を挿入する。
            # " nav"を付けると"stop nav"になりどのノードも反応しないため、そのまま送る
            self.action_ctl_pub(cmd["data"])
        return self.action_ctl_pub(str(cmd["data"]) + " nav")

    #
    def msg_callback(self, msg):
        self.get_logger().info(msg.data)


def main():
    rclpy.init()
    robot_name = os.getenv("ROBOT_NAME")
    node = polling_ros_command_node(robot_name)
    #
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
