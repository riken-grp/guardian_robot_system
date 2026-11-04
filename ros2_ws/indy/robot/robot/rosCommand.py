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
        self.get_logger().info("start ros command node " + robot_name)

    #
    def action_ctl_pub(self, text):
        msg = String()
        msg.data = text
        self.mpub.publish(msg)
        return True

    def ros_cmd_pub(self, text, topic_name, topic_type):
        if topic_type in TOPIC_TYPES:
            msg = TOPIC_TYPES[topic_type]()
        else:
            return False
        if text != "":
            msg.data = text

        pub = self.create_publisher(TOPIC_TYPES[topic_type], topic_name, 10)
        time.sleep(1)
        pub.publish(msg)
        time.sleep(1)
        self.destroy_publisher(pub)
        return True

    #
    def timer_callback(self):
        msg = self.mng.get_next()
        # self.get_logger().info('time callback')
        if msg == False:
            return False
        cmd = msg["option"]

        if "topic_type" in cmd:
            if "topic" not in cmd:
                return False
            topic_name = cmd["topic"]
            topic_type = cmd["topic_type"]
            ret = self.ros_cmd_pub(cmd["data"], topic_name, topic_type)
            if not ret:
                self.mng.set_status(msg["_id"], "failed")
                return False
        elif cmd["data"] == "stop":
            # ActionManager.stop_all() はtopic_typeなしで"stop"を挿入する。
            # " nav"を付けると"stop nav"になりどのノードも反応しないため、そのまま送る
            self.action_ctl_pub(cmd["data"])
        else:
            self.action_ctl_pub(cmd["data"] + " nav")
        self.mng.set_status(msg["_id"], "done")

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
