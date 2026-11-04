#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import String
import os
import json
import time

from pyindy.mongo import EyeManager as mngdb


class ros_watchdog_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('ros_watchdog')
        # 
        print("Start action to ros watchdog node for " + robot_name)
        self.robot_name=robot_name
        #
        self.declare_parameter("mongo_port", 0)
        self.mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        self.get_logger().info("mongo_port: " + str(self.mongo_port))
        #
        self.declare_parameter("mongo_uri", "")
        self.mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        #
        self.mng=mngdb(self.mongo_uri,self.mongo_port,self.robot_name)
        timer_period = 10.0
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.get_logger().info("start ros watchdog node" + robot_name)
    #
    def action_ctl_pub(self, text):
        msg=String()
        msg.data=text
        self.mpub.publish(msg)
    #
    def timer_callback(self):
        self.get_logger().info('ros watchdog')
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop':
            print("stop")
            self.get_logger().warn("was not played.")
            self.action_ctl_pub(self.robot_name + ": gesture was stopped.")
            self.cdt=0.0

def main():
    rclpy.init()
    robot_name=os.getenv("ROBOT_NAME")
    node = ros_watchdog_node(robot_name)
    #
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

