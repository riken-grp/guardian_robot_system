#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import String
import os
import json
import time

from pyindy.mongo import EyeManager as mngdb

from pathlib import Path
from ament_index_python.packages import get_package_share_directory


class polling_eye_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('eye_from_MongoDB')
        # 
        print("Start action to eye node for " + robot_name)
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
        timer_period = 0.1
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.lepub = self.create_publisher(String, "eye_display/left/target_file", 10)
        self.repub = self.create_publisher(String, "eye_display/right/target_file", 10)        
        self.get_logger().info("start eye node" + robot_name)
        self.is_playing=False
        self.cdt=-1.0
        self.p=False
        self.default_image='neutral1.jpg'
        self.image_dir = Path(get_package_share_directory('lcd_control')) / 'image'
        self.images=[
                        image_path.name for image_path in self.image_dir.iterdir()
                        if image_path.is_file() and image_path.suffix.lower() == ".jpg"
                    ]
    #
    def action_ctl_pub(self, text):
        msg=String()
        msg.data=text
        self.mpub.publish(msg)
    #
    def timer_callback(self):
        text="robot_name: eye status: " + self.robot_name + str(self.is_playing)
        #self.get_logger().warn(text)
        if not self.p:
            self.p=self.mng.get_next()
            if self.p != False:
                self.mng.set_status(self.p['_id'],'is_playing')
                data={}
                if 'image' in self.p['option']:
                    data['image'] = self.p['option']['image']
                else:
                    data['image'] = self.default_image
                self.action_ctl_pub(json.dumps(data))
                self.cdt=2.0
                if 'duration' in self.p['option'].keys():
                    self.cdt=self.p['option']['duration']
                # self.p=True
                #
                lmsg=String()
                lmsg.data="L"+data['image']
                self.lepub.publish(lmsg)
                rmsg=String()
                rmsg.data="R"+data['image']
                self.repub.publish(rmsg)
                #
                self.get_logger().info(data['image'])
        else:
            if self.cdt > 0.0:
                self.cdt=self.cdt-0.1
            else:
                self.mng.set_status(self.p['_id'],'done')
                self.get_logger().warn("eye: " + self.default_image)
                self.p=False
                #
                lmsg=String()
                lmsg.data="L"+self.default_image
                self.lepub.publish(lmsg)
                rmsg=String()
                rmsg.data="R"+self.default_image
                self.repub.publish(rmsg)
                # 
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop' or msg.data == "stop eye":
            print("stop")
            self.get_logger().warn("was not played.")
            self.action_ctl_pub(self.robot_name + ": gesture was stopped.")
            self.cdt=0.0

def main():
    rclpy.init()
    robot_name=os.getenv("ROBOT_NAME")
    node = polling_eye_node(robot_name)
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

