#!/usr/bin/python3
import numpy as np
import signal
import time
import json
import datetime

## ROS
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Joy
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import Twist
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TransformStamped
from tf2_msgs.msg import TFMessage
from tf2_ros import TransformBroadcaster
from tf2_ros import StaticTransformBroadcaster

# import quaternion
### Quaternion
def zangle2quaternion(th):
    return np.array([0., 0., np.sin(th/2.), np.cos(th/2.)])
def quaternion2zangle(q):
    return np.array(q[2],q[3])


#### ROS nodes #######################################################
class TestPublisher(Node):
    def __init__(self):
        super().__init__('test_publisher')
        self.publisher_ = self.create_publisher(String, 'test', 10)
    def publish(self, text):
        msg = String()
        data={}
        data['timestamp']=str(datetime.datetime.now())
        data['message']=text
        msg.data = json.dumps(data)
        print(msg)
        self.publisher_.publish(msg)

class ButukusaPublisher(Node):
    def __init__(self):
        super().__init__('rover_butukusa')
        self.publisher_ = self.create_publisher(String, 'rover/butukusa', 10)
    def publish(self, mode, per):
        msg = String()
        data={}
        data['timestamp']=str(datetime.datetime.now())
        data['mode']=mode
        data['battery']=per
        msg.data = json.dumps(data)
        print(msg)
        self.publisher_.publish(msg)

class TwistPublisher(Node):
    def __init__(self):
        super().__init__('rover_twist')
        self.publisher_ = self.create_publisher(Twist, 'rover/twist', 10)
    def publish(self,msg):
        # print(msg)
        self.publisher_.publish(msg)

class PosePublisher(Node):
    def __init__(self):
        super().__init__('rover_pose')
        self.publisher_ = self.create_publisher(PoseStamped, 'rover/pose', 10)
        # self.tfpublisher_ = self.create_publisher(TransformStamped, '/tf', 10)
        self.tfpublisher_ = self.create_publisher(TFMessage, '/tf', 10)
    def publish(self,x, y, th):
        # print(msg)
        msg=PoseStamped()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        msg.pose.position.x=x
        msg.pose.position.y=y
        msg.pose.position.z=0.0
        #q=quaternion.from_euler_angles(0.,0.,th)
        q=zangle2quaternion(th)
        print(q)
        #msg.pose.orientation.x=q.x
        msg.pose.orientation.x=q[0]
        #msg.pose.orientation.y=q.y
        msg.pose.orientation.y=q[1]
        #msg.pose.orientation.z=q.z
        msg.pose.orientation.z=q[2]
        #msg.pose.orientation.w=q.w
        msg.pose.orientation.z=q[3]
        self.publisher_.publish(msg)
        #
        tfm=TransformStamped()
        # tfm.header.stamp = now.to_msg()
        tfm.header.frame_id = 'home'
        tfm.child_frame_id = 'rover'
        tfm.transform.translation.x = x
        tfm.transform.translation.y = y
        tfm.transform.translation.z = 0.0
        tfm.transform.rotation.x = q[0]
        tfm.transform.rotation.y = q[1]
        tfm.transform.rotation.z = q[2]
        tfm.transform.rotation.w = q[3]
        tfs=TFMessage()
        tfs.transforms=[tfm]
        self.tfpublisher_.publish(tfs)
        
class BatPublisher(Node):
    def __init__(self):
        super().__init__('rover_battery')
        self.publisher_ = self.create_publisher(BatteryState, 'rover/battery', 10)
    def publish(self, volt, per, cur):
        # print(msg)
        msg=BatteryState()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        msg.voltage=volt
        msg.percentage=per
        msg.current=cur
        self.publisher_.publish(msg)


class tfStaticPublisher(Node):
    def __init__(self):
        super().__init__('rover_tf_static')
        self.publisher_=self.create_publisher(TFMessage, '/tf_static2', 10)
    def publish(self):
        tfm=TransformStamped()
        # tfm.header.stamp = now.to_msg()
        tfm.header.frame_id = 'rover'
        tfm.child_frame_id = 'head'
        tfm.transform.translation.x = 0.0
        tfm.transform.translation.y = 0.0
        tfm.transform.translation.z = 1.0
        tfm.transform.rotation.x = 0.0
        tfm.transform.rotation.y = 0.0
        tfm.transform.rotation.z = 0.0
        tfm.transform.rotation.w = 1.0
        tfms=TFMessage()
        tfms.transforms=[tfm]
        self.publisher_.publish(tfms)

    
def main():
    rclpy.init()
    tfs=tfStaticPublisher()
    try:
        rclpy.spin(tfs)
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    tfs.destroy_node()

if __name__ == '__main__':
    main()

