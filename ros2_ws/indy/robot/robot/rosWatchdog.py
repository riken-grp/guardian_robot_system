#!/usr/bin/python3
import json
import os
import time

import numpy as np
import rclpy
from common_msgs.msg import StringStamped
from geometry_msgs.msg import PoseStamped, TransformStamped
from pyindy.functions import is_json
from pyindy.mongo import DialogueHistoryManager
from pyindy.mongo import EyeManager as mngdb
from pyindy.mongo import PhysicalDBWriter, UtteranceManager
from rclpy import qos
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String


class ros_watchdog_node(Node):
    def __init__(self, robot_name="none"):
        super().__init__("ros_watchdog")
        #
        print("Start action to ros watchdog node for " + robot_name)
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
        self.dhm = DialogueHistoryManager(
            self.mongo_uri, self.mongo_port, self.robot_name
        )
        self.trigger_asr = PhysicalDBWriter(
            self.mongo_uri, self.mongo_port, "tBlackBoard", "asr"
        )
        #
        self.subtitle_asr = UtteranceManager(
            self.mongo_uri, self.mongo_port, "asr", "subtitle_indy"
        )
        self.subtitle_rob = UtteranceManager(
            self.mongo_uri, self.mongo_port, self.robot_name, "subtitle_indy"
        )
        ###
        timer_period = 60.0
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.msub = self.create_subscription(
            String,
            "robot/action_ctl",
            self.msg_callback,
            qos_profile=qos.qos_profile_sensor_data,
        )
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.get_logger().info("start ros watchdog node " + robot_name)
        # for subtitle
        self.sub_asr = self.create_subscription(
            StringStamped,
            "asr/meta_data",
            self.asr_callback,
            qos_profile=qos.qos_profile_sensor_data,
        )
        self.sub_bat = self.create_subscription(
            BatteryState,
            "rover/battery",
            self.bat_callback,
            qos_profile=qos.qos_profile_sensor_data,
        )
        self.bat_percentage = 100
        self.bat_current = 0.0

    #
    def action_ctl_pub(self, text):
        msg = String()
        msg.data = text
        self.mpub.publish(msg)

    #
    def timer_callback(self):
        self.get_logger().info("ros watchdog")
        self.get_logger().info(" battery percentage: " + str(self.bat_percentage))
        if self.bat_percentage < 30 and self.bat_current >= 0:
            data = {}
            data["percentage"] = self.bat_percentage
            data["current"] = self.bat_current
            low_battery = PhysicalDBWriter(
                self.mongo_uri, self.mongo_port, "tBlackBoard", "request_battery_charge"
            )
            low_battery.insert(data)
            self.get_logger().info(" battery percentage: " + str(self.bat_percentage))
            self.get_logger().info(" battery current: " + str(self.bat_current))
            return True
        if self.bat_percentage < 40 and self.bat_current >= 0:
            data = {}
            data["percentage"] = self.bat_percentage
            data["current"] = self.bat_current
            low_battery = PhysicalDBWriter(
                self.mongo_uri, self.mongo_port, "tBlackBoard", "low_battery"
            )
            low_battery.insert(data)
            self.get_logger().info(" battery percentage: " + str(self.bat_percentage))
            self.get_logger().info(" battery current: " + str(self.bat_current))
            return True
        if self.bat_percentage > 90 and self.bat_current <= 0.1:  # charging
            data = {}
            data["percentage"] = self.bat_percentage
            data["current"] = self.bat_current
            full_battery = PhysicalDBWriter(
                self.mongo_uri, self.mongo_port, "tBlackBoard", "full_battery"
            )
            full_battery.insert(data)
            self.get_logger().info(" battery percentage: " + str(self.bat_percentage))
            self.get_logger().info(" battery current: " + str(self.bat_current))
            return True

    #
    def msg_callback(self, msg):
        if is_json(msg.data) == False:
            return False
        D = json.loads(msg.data)
        if "speak" in D.keys():
            self.get_logger().info("speak" + D["speak"])
            if len(D["speak"]) < 5:
                self.get_logger().info("speak short word" + D["speak"])
            else:
                # self.get_logger().info('speak ' + D['speak'])
                # self.dhm.insert(self.robot_name, D["speak"])
                item = self.subtitle_rob.insert({"text": D["speak"]})
                self.subtitle_rob.set_status(item.inserted_id, "done")

    def asr_callback(self, msg):
        d = json.loads(msg.data)
        if np.abs(np.degrees(np.arctan2(d["x"], d["y"]))) > 45:
            self.get_logger().info("asr from outside" + d["words"])
        else:
            self.get_logger().info("asr " + d["words"])
            self.dhm.insert("asr", d["words"], d["sep_port"])
            # self.trigger_asr.insert({'text': d['words']})
            item = self.subtitle_asr.insert({"text": d["words"]})
            self.subtitle_asr.set_status(item.inserted_id, "done")

    def bat_callback(self, msg):
        # d=json.dumps(msg.data)
        self.bat_percentage = msg.percentage
        self.bat_current = msg.current
        # self.get_logger().info(str(msg.percentage))
        # self.get_logger().info(str(msg.current))


def main():
    rclpy.init()
    robot_name = os.getenv("ROBOT_NAME")
    node = ros_watchdog_node(robot_name)
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
