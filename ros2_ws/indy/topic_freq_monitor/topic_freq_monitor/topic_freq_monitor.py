from datetime import datetime, timedelta, timezone
from functools import partial
from importlib import import_module
import collections
from pymongo import MongoClient
import os

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

class TopicFreqMonitor(Node):
    def __init__(self):
        super().__init__('topic_freq_monitor')

        self.robot_name = self.get_namespace().removeprefix("/")
        self.host_name = os.uname()[1]

        self.declare_parameter('update_rate', 1.0)
        self.declare_parameter('timeout_time', 3.0)
        self.declare_parameter('comp_ratio', 3.0)
        self.declare_parameter('queue_size', 5)
        self.declare_parameter('topic_list', [""])
        self.declare_parameter('mongo_uri', "")
        self.declare_parameter('mongo_port', 0)

        update_rate = self.get_parameter('update_rate').get_parameter_value().double_value
        self.timeout_time = self.get_parameter('timeout_time').get_parameter_value().double_value
        comp_ratio = self.get_parameter('comp_ratio').get_parameter_value().double_value
        queue_size = self.get_parameter('queue_size').get_parameter_value().integer_value
        topic_info_list = self.get_parameter('topic_list').get_parameter_value().string_array_value
        mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value

        if (len(topic_info_list) % 4) != 0:
            self.get_logger().error("Size of topic_list is wrong.")
            return

        topic_size = int(len(topic_info_list) / 4)
        topic_list = []
        package_list = []
        class_list = []
        error_time_list = []
        for i in range(topic_size):
            topic_list.append(topic_info_list[4 * i])
            package_list.append(topic_info_list[4 * i + 1])
            class_list.append(topic_info_list[4 * i + 2])
            error_time = 1.0 / float(topic_info_list[4 * i + 3]) * comp_ratio
            error_time_list.append(error_time)

        msg_type_list = self.import_msg_module(package_list, class_list)

        self.topic_update_time = {}
        for topic_name in topic_list:
            self.topic_update_time[topic_name] = collections.deque([], queue_size)

        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        log_db = mongo_client["log"]
        self.topic_freq_collection = log_db["topic_frequency"]

        cur_status_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        cur_status_db = cur_status_client["current_status"]
        self.cur_status_collection = cur_status_db["topic_frequency"]

        self.create_subscribers(topic_list, msg_type_list)

        timer_callback = partial(self.check_topic_freq, topic_list, error_time_list)
        self.timer = self.create_timer(update_rate, timer_callback)

    def import_msg_module(self, package_list, class_list):
        msg_type_list = []
        for package_name, class_name in zip(package_list, class_list):
            module_name = package_name + ".msg"
            msg_type = getattr(import_module(module_name), class_name)
            msg_type_list.append(msg_type)
        return msg_type_list

    def create_subscribers(self, topic_list, msg_type_list):
        for topic_name, msg_type in zip(topic_list, msg_type_list):
            callback = partial(self.update_topic_time, topic_name)
            self.create_subscription(msg_type, topic_name, callback, 10)

    def update_topic_time(self, topic_name, msgs):
        dt = datetime.now(timezone(timedelta(hours=9)))
        self.topic_update_time[topic_name].append(dt)

    def check_topic_freq(self, topic_list, error_time_list):
        current_time = datetime.now(timezone(timedelta(hours=9)))
        for topic_name, error_time in zip(topic_list, error_time_list):
            queue_size = len(self.topic_update_time[topic_name])
            if queue_size == 0:
                self.get_logger().debug("%s: NotReceived" % topic_name)
                self.update_db(topic_name, current_time, "NotReceived", 0.0)
                self.update_current_status(topic_name, current_time, "NotReceived", 0.0)
                continue

            first_time = self.topic_update_time[topic_name][0]
            last_time = self.topic_update_time[topic_name][queue_size - 1]
            last_duration = current_time.timestamp() - last_time.timestamp()
            ave_time = (last_time.timestamp() - first_time.timestamp()) / (queue_size - 1)

            if last_duration > self.timeout_time:
                topic_state = "Timeout"
                ave_freq = 0.0
            elif ave_time > error_time:
                topic_state = "Error"
                ave_freq = 1.0 / ave_time
            elif len(self.topic_update_time[topic_name]) == 0:
                topic_state = "OK"
                ave_freq = 0.0
            else:
                topic_state = "OK"
                ave_freq = 1.0 / ave_time
            self.get_logger().debug("%s: %s" % (topic_name, topic_state))

            self.update_db(topic_name, current_time, topic_state, ave_freq)
            self.update_current_status(topic_name, current_time, topic_state, ave_freq)

    def update_db(self, topic_name, current_time, topic_state, ave_freq):
        obj = {}
        obj["time"] = current_time
        obj["robot"] = self.robot_name
        obj["topic_name"] = "/" + self.robot_name + "/" + topic_name
        obj["test"] = topic_name
        obj["status"] = topic_state
        obj["current_frequency"] = ave_freq

        self.topic_freq_collection.insert_one(obj)
    
    def update_current_status(self, topic_name, current_time, topic_state, ave_freq):
        all_document = [doc for doc in self.cur_status_collection.find()]

        for document in all_document:
            if "robot" not in document.keys() or "test" not in document.keys():
                continue
            if (document["robot"] == self.robot_name and
                document["test"] == topic_name):
                self.cur_status_collection.delete_one({"_id": document["_id"]})

        obj = {}
        obj["time"] = current_time
        obj["robot"] = self.robot_name
        obj["test"] = topic_name
        obj["status"] = topic_state
        obj["current_frequency"] = ave_freq

        self.cur_status_collection.insert_one(obj)


def main():
    rclpy.init()
    node = TopicFreqMonitor()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
