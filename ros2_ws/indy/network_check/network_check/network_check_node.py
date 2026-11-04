import os
import subprocess
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

import rclpy
from rclpy.time import Time
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from geometry_msgs.msg import PoseStamped
from network_msgs.msg import NetworkInfo

class NetworkCheck(Node):
    def __init__(self):
        super().__init__('network_check_node')

        self.declare_parameter('report_rate', 1.0)
        self.declare_parameter('mongo_uri', "")
        self.declare_parameter('mongo_port', 0)
        self.declare_parameter('network_interface', "")

        timer_period = self.get_parameter('report_rate').get_parameter_value().double_value
        mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value
        self.network_interface = self.get_parameter('network_interface').get_parameter_value().string_value

        self.robot_name = os.getenv("ROBOT_NAME")
        if self.robot_name is None:
            self.get_logger().error("failed to get robot name")
            return

        self.host_name = os.uname()[1]

        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        self.network_db = mongo_client["log"]
        self.network_collection = self.network_db["network"]

        cur_status_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        cur_status_db = cur_status_client["current_status"]
        self.cur_status_collection = cur_status_db["network"]

        self.network_info_pub = self.create_publisher(NetworkInfo, "network_check/info", 10)

        self.robot_pose = PoseStamped()
        self.robot_pose_sub = self.create_subscription(PoseStamped, 'rover/pose', self.robot_pose_cb, 10)

        self.timer = self.create_timer(timer_period, self.timer_callback)

    def robot_pose_cb(self, msg):
        self.robot_pose = msg

    def timer_callback(self):
        self.get_logger().debug("timer in")
        connect_flg = True
        
        # Get wireless device name
        if self.network_interface:
            # Use specified interface
            dev_name = self.network_interface
            self.get_logger().debug(f"Using specified wireless interface: {dev_name}")
        else:
            # Auto-detect interface - find connected interface
            iw_dev_res = subprocess.run(["iw", "dev"], capture_output=True, text=True)
            iw_dev_str = iw_dev_res.stdout
            self.get_logger().debug(iw_dev_str)
            
            # Parse all device names from "Interface <dev_name>"
            dev_names = []
            for line in iw_dev_str.split('\n'):
                if "Interface" in line:
                    dev_names.append(line.split()[1])
            
            # Find the first connected interface
            dev_name = None
            for candidate in dev_names:
                check_res = subprocess.run(["iw", "dev", candidate, "link"], capture_output=True, text=True)
                check_str = check_res.stdout
                if "Connected to" in check_str:
                    dev_name = candidate
                    self.get_logger().debug(f"Found connected interface: {dev_name}")
                    break
            
            # If no connected interface found, use the first one
            if dev_name is None and len(dev_names) > 0:
                dev_name = dev_names[0]
                self.get_logger().debug(f"No connected interface found, using first available: {dev_name}")
        
        if dev_name is None:
            self.get_logger().error("Failed to get wireless device name")
            connect_flg = False
            sig_level = "0"
            ap_name = ""
        else:
            # Get link information using iw dev <dev_name> link
            iw_link_res = subprocess.run(["iw", "dev", dev_name, "link"], capture_output=True, text=True)
            iw_link_str = iw_link_res.stdout
            self.get_logger().debug(iw_link_str)
            
            # Check if connected
            if "Not connected" in iw_link_str or iw_link_str.strip() == "":
                connect_flg = False
                sig_level = "0"
                ap_name = ""
            else:
                # Parse signal level
                sig_level = "0"
                for line in iw_link_str.split('\n'):
                    if "signal:" in line:
                        # Format: "signal: -45 dBm"
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "signal:":
                                sig_level = parts[i+1]  # Gets "-45"
                                break
                        break
                
                # Parse AP MAC address (Connected to XX:XX:XX:XX:XX:XX)
                ap_name = ""
                for line in iw_link_str.split('\n'):
                    if "Connected to" in line:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "to":
                                ap_name = parts[i+1]  # Gets MAC address
                                break
                        break
                
                self.get_logger().info("ap_name:%s sig_level:%s dbm" % (ap_name, sig_level))
                
                if sig_level == "0":
                    connect_flg = False

        msg = NetworkInfo()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.host_name = self.host_name
        msg.sig_level = float(sig_level)
        msg.ap_name = ap_name
        msg.robot_pose = self.robot_pose.pose

        self.network_info_pub.publish(msg)
        self.update_db(msg, connect_flg)
        self.update_current_status(msg, connect_flg)

    def update_db(self, msg, connect_flg):
        obj = {}
        obj["time"] = self.to_datetime(Time.from_msg(msg.header.stamp))
        obj["robot"] = self.robot_name
        obj["host"] = msg.host_name
        obj["test"] = "sig_level_" + msg.host_name
        if connect_flg:
            obj["status"] = "OK"
        else:
            obj["status"] = "disconnected"
        obj["signal_level"] = msg.sig_level
        obj["ap_name"] = msg.ap_name
        pose = msg.robot_pose.position
        obj["robot_position(x,y,z)"] = [pose.x, pose.y, pose.z]
        rot = msg.robot_pose.orientation
        obj["robot_orientation(w,x,y,z)"] = [rot.w, rot.x, rot.y, rot.z]

        self.network_collection.insert_one(obj)

    def update_current_status(self, msg, connect_flg):
        all_document = [doc for doc in self.cur_status_collection.find()]

        for document in all_document:
            if "robot" not in document.keys() or "test" not in document.keys():
                continue
            if (document["test"] == "sig_level_" + msg.host_name):
                self.cur_status_collection.delete_one({"_id": document["_id"]})
    
        obj = {}
        obj["time"] = self.to_datetime(Time.from_msg(msg.header.stamp))
        obj["robot"] = self.robot_name
        obj["host"] = msg.host_name
        obj["test"] = "sig_level_" + msg.host_name
        if connect_flg:
            obj["status"] = "OK"
        else:
            obj["status"] = "disconnected"
        obj["signal_level"] = msg.sig_level
        obj["ap_name"] = msg.ap_name

        self.cur_status_collection.insert_one(obj)

    def to_datetime(self, t):
        s, n = t.seconds_nanoseconds()
        sn = s + n * 10e-9
        dt = datetime.fromtimestamp(sn, tz=timezone(timedelta(hours=9)))
        return dt


def main():
    rclpy.init()
    node = NetworkCheck()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()