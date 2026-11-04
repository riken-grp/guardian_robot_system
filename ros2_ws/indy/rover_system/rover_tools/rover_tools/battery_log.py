from datetime import datetime, timedelta, timezone
from importlib import import_module
from pymongo import MongoClient
import time
import os

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy import qos
from sensor_msgs.msg import BatteryState

class BatteryLog(Node):
    def __init__(self):
        super().__init__('battery_log_node')

        self.robot_name = self.get_namespace().removeprefix("/")
        self.host_name = os.uname()[1]

        self.declare_parameter('mongo_uri', "")
        self.declare_parameter('mongo_port', 0)

        update_rate = 300.0
        mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value

        cur_status_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        cur_status_db = cur_status_client["tBlackBoard"]
        self.battery_collection = cur_status_db["battery_log"]

        self.percentage = 0.0
        self.current = 0.0
        self.voltage = 0.0

        timer_cb_group = MutuallyExclusiveCallbackGroup()

        self.create_subscription(BatteryState, "rover/battery", self.battery_cb, qos.qos_profile_sensor_data)

        self.timer = self.create_timer(update_rate, self.timer_callback, callback_group=timer_cb_group)
    
    def battery_cb(self, msg):
        self.percentage = msg.percentage
        self.current = msg.current
        self.voltage = msg.voltage

    def timer_callback(self):
        while self.percentage == 0.0:
            time.sleep(0.1)
        current_time = datetime.now(timezone(timedelta(hours=9)))

        self.update_db(current_time)

    def update_db(self, current_time):
        obj = {}
        obj["robot"] = self.robot_name
        obj["host"] = self.host_name
        obj["percentage"] = self.percentage
        obj["current"] = self.current
        obj["voltage"] = self.voltage
        obj["time"] = current_time

        try:
            self.battery_collection.insert_one(obj)
        except:
            self.get_logger().warn("Failed to update battery_log")


def main():
    rclpy.init()
    node = BatteryLog()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
