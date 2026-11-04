import os
import subprocess
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

class NodeMonitor(Node):
    def __init__(self):
        super().__init__('node_monitor_node')

        self.robot_name = self.get_namespace().removeprefix("/")
        self.host_name = os.uname()[1]

        self.declare_parameter('report_rate', 1.0)
        self.declare_parameter('node_list', [""])
        self.declare_parameter('mongo_uri', "")
        self.declare_parameter('mongo_port', 0)

        timer_period = self.get_parameter('report_rate').get_parameter_value().double_value
        node_list = self.get_parameter('node_list').get_parameter_value().string_array_value
        mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value

        self.node_name_list = []
        for node_name in node_list:
            node_name = node_name.removeprefix("/")
            self.node_name_list.append("/" + self.robot_name + "/" + node_name)

        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        node_db = mongo_client["log"]
        self.node_collection = node_db["node"]

        cur_status_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        cur_status_db = cur_status_client["current_status"]
        self.cur_status_collection = cur_status_db["node"]

        self.timer = self.create_timer(timer_period, self.timer_callback)

    def timer_callback(self):
        self.get_logger().debug("timer in")
        current_time = datetime.now(timezone(timedelta(hours=9)))
        node_list_cmd = subprocess.run(["ros2", "node", "list"], capture_output=True, text=True)
        node_list_str = node_list_cmd.stdout
        node_str = node_list_str.splitlines()
        
        node_info_list = []
        for check_node in self.node_name_list:
            node_alive_flg = False
            for current_node in node_str:
                if check_node == current_node:
                    node_alive_flg = True
                    break
            node_info_list.append([check_node, node_alive_flg, current_time])
        self.update_db(node_info_list)
        self.update_current_status(node_info_list)

    def update_db(self, node_info_list):
        insert_list = []
        for node_info in node_info_list:
            obj = {}
            obj["time"] = node_info[2]
            obj["robot"] = self.robot_name
            obj["host"] = self.host_name
            obj["test"] = node_info[0]
            if node_info[1]:
                obj["status"] = "OK"
                self.get_logger().debug("alive: " + node_info[0])
            else:
                obj["status"] = "FAIL"
                self.get_logger().debug("not found: " + node_info[0])
            insert_list.append(obj)

        self.node_collection.insert_many(insert_list)

    def update_current_status(self, node_info_list):
        all_document = [doc for doc in self.cur_status_collection.find()]

        for document in all_document:
            if "robot" not in document.keys() or "test" not in document.keys():
                continue
            if (document["robot"] == self.robot_name and
                document["test"] in [node_info[0] for node_info in node_info_list]):
                self.cur_status_collection.delete_one({"_id": document["_id"]})

        insert_list = []
        for node_info in node_info_list:
            obj = {}
            obj["time"] = node_info[2]
            obj["robot"] = self.robot_name
            obj["host"] = self.host_name
            obj["test"] = node_info[0]
            if node_info[1]:
                obj["status"] = "OK"
            else:
                obj["status"] = "FAIL"
            insert_list.append(obj)

        self.cur_status_collection.insert_many(insert_list)


def main():
    rclpy.init()
    node = NodeMonitor()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()