#!/usr/bin/python3
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import String
from std_msgs.msg import Float32
from sensor_msgs.msg import JointState
import os
import json
import time

from pyindy.mongo import GestureManager as mngdb
from pyindy.mongo import ActionPrimitives


class polling_gesture_node_for_robodj(Node):
    def __init__(self, robot_name='none'):
        super().__init__('robodj_gesture_from_MongoDB')
        # 
        print("Start action to gesture node for " + robot_name)
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
        self.get_logger().info("start gesture node" + robot_name)
        self.is_playing=False
        self.publisherRarm = self.create_publisher(JointState, '/right_arm/goal_joints', 10)
        self.publisherLarm = self.create_publisher(JointState, '/left_arm/goal_joints', 10)
        self.publisher_head_body = self.create_publisher(JointState, '/keigan_motor/goal_pose', 10)
        self.publisherBody = self.create_publisher(JointState, '/keigan_motor/goal_pose', 10)
        self.publisherHead = self.create_publisher(JointState, '/keigan_motor/goal_pose', 10)
        self.apmng=ActionPrimitives(self.mongo_uri,self.mongo_port)
    #
    def set_pose(self,name):
        selected_pose= self.apmng.find(name)
        if selected_pose==False:
            return False
        msg_head = JointState()
        msg_body = JointState()
        msg_Rarm = JointState()
        msg_Larm = JointState()
        
        msg_head.name = ["neck_yaw_joint", "neck_pitch_joint"]
        msg_body.name = ["body_pitch_joint"]
        
        msg_head.position = selected_pose['option']['head']
        msg_body.position = selected_pose['option']['body']
        msg_Rarm.position = selected_pose['option']['rightArm']
        msg_Larm.position = selected_pose['option']['leftArm']
        
        self.publisherHead.publish(msg_head)
        self.publisherBody.publish(msg_body)
        self.publisherRarm.publish(msg_Rarm)
        self.publisherLarm.publish(msg_Larm)
        return selected_pose
        
    def action_ctl_pub(self, text):
        msg=String()
        msg.data=text
        data=json.loads(text)
        name=data['gesture']
        self.get_logger().warn("gesture: " + name)
        self.set_pose(name)
        self.mpub.publish(msg)
        time.sleep(5)
        self.set_pose('look_front')
    #
    def timer_callback(self):
        text="robot_name: gesture status: " + self.robot_name + str(self.is_playing)
        #self.get_logger().warn(text)
        self.gesture=self.mng.get_next()
        if self.gesture != False:
            self.mng.set_status(self.gesture['_id'],'is_playing')
            data={}
            data['gesture'] = self.gesture['option']['gesture']
            self.action_ctl_pub(json.dumps(data))
            ts=0.5
            if 'duration' in self.gesture['option'].keys():
                ts=ts+self.gesture['option']['duration']
            if 'offset' in self.gesture['option'].keys():
                ts=ts+self.gesture['option']['offset']
            time.sleep(ts)
            self.mng.set_status(self.gesture['_id'],'done')
            self.get_logger().warn("Fake: " + data['gesture'] + " " + str(ts) +"seconds")
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop':
            print("stop")
            self.get_logger().warn("was not played.")
            self.action_ctl_pub(self.robot_name + ": gesture was stopped.")

def main():
    rclpy.init()
    robot_name=os.getenv("ROBOT_NAME")
    node = polling_gesture_node_for_robodj(robot_name)
    #
    exec=MultiThreadedExecutor()
    exec.add_node(node)
    try:
        exec.spin()
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    exec.shutdown()
    node.destroy_node()

if __name__ == '__main__':
    main()

