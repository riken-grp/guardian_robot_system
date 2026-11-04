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
from common_msgs.msg import StringStamped

# import quaternion
### Quaternion
def zangle2quaternion(th):
    return np.array([0., 0., np.sin(th/2.), np.cos(th/2.)])
def quaternion2zangle(q):
    return 2*np.arctan2(q[2],q[3])


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
        self.publisher_ = self.create_publisher(StringStamped, 'rover/butukusa', 10)
    def publish(self, data):
        msg = StringStamped()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        # data={}
        # data['timestamp']=str(datetime.datetime.now())
        # data['mode']=mode
        # data['battery']=per
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
        self.name_space = self.get_namespace()
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
        msg.pose.orientation.w=q[3]
        self.publisher_.publish(msg)
        #
        tfm=TransformStamped()
        tfm.header.stamp = self.get_clock().now().to_msg()
        tfm.header.frame_id = 'map'
        tfm.child_frame_id = self.get_namespace() + '_base_footprint'
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
        # print(msg)
        self.publisher_.publish(msg)

## global variables
x=0.0
y=0.0
th=0.0
operation_state='initial'
volt=0.0
per=0.0
cur=0.0
e_code=0
e_desc=''

## MQTT 
import paho.mqtt.client as paho

def on_connect(self, obj, flag, rc):
    print("rc: "+str(rc))

def on_message(self, obj, msg):
    global x, y, th, volt, per, cur, operation_state, e_code, e_desc
    global pose, battery, butukusa, mqttc
    print("= message =================")
    print(msg.topic)
    # print(msg.topic + " " + str(msg.payload))
    dmsg=json.loads(msg.payload.decode('utf-8'))
    if msg.topic == 'status':
        x=dmsg["location"]["x"]
        y=dmsg["location"]["y"]
        th=dmsg["location"]["angle"]["theta"]
        e_code=dmsg["error"]["code"]
        e_desc=dmsg["error"]["description"]
        # pose.publish(x, y, th)
        volt=dmsg["battery"]["voltage"]
        per=float(dmsg["battery"]["percentage"])
        operation_state=dmsg["operation_state"]
        # print(x, y, th, volt, per)
        # print(dmsg)
        # battery.publish(volt, per)
    if msg.topic == 'status/hardware':
        volt=dmsg["battery"]["voltage"]
        cur=dmsg["battery"]["current"]
        # print(volt, cur)
        # print(dmsg)
    battery.publish(volt, per, cur)
    pose.publish(x, y, th)
    data={}
    data['timestamp']=str(datetime.datetime.now())
    data['mode']=operation_state
    data['battery']=per
    data['error_code']=e_code
    data['error_description']=e_desc
    print(data)
    butukusa.publish(data)

def on_publish(self, obj, mid):
    print("mid: "+str(mid))

def on_subscribe(self, obj, mid, granted_qos):
    print("= subscribe =================")
    print("Subscribed: "+str(mid)+" "+str(granted_qos))

def on_log(self, obj, level, string):
    print(string)

pose=False
battery=False
butukusa=False
mqttc=False

    
def main():
    rclpy.init()
    global pose, battery, butukusa, mqttc
    pose=PosePublisher()
    battery=BatPublisher()
    butukusa=ButukusaPublisher()
    mqttc = paho.Client(paho.CallbackAPIVersion.VERSION1)#mqtt
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_subscribe = on_subscribe
    
    # mqttc.connect("192.168.0.171", 9075, 60)
    mqttc.connect("192.168.4.2", 9075, 60)
    # mqttc.subscribe("nav/amr_pose", 0)
    mqttc.subscribe("status/#",0)
    # mqttc.subscribe("status/hardware",0)
    mqttc.loop_forever()

if __name__ == '__main__':
    main()

