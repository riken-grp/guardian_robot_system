#!/usr/bin/python3
import numpy as np
import signal
import time
import json

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from sensor_msgs.msg import Joy
from geometry_msgs.msg import Twist
from common_msgs.msg import LocalGoal
from common_msgs.msg import StringStamped
#### MQTT nodes ######################################################
import paho.mqtt.client as mqtt

mqttc =None

def on_connect(self, obj, flag, rc):
    self.subscribe("$SYS/#", 0)
    print("--- ")
    print("Connected with result code: "+str(rc))

def on_disconnect(self, obj, rc):
    if rc != 0:
        print("--- ")
        print("Unexpected disconnection")
        
def on_message(self, obj, msg):
    print(msg.topic+" "+str(msg.qos)+" "+str(msg.payload))

def on_publish(self, obj, mid):
    print("---")
    # print("published: "+str(mid))

def on_log(self, obj, level, string):
    print(string)

def scheduler(arg1, args2):
    global mqttc
    mqttc.publish("control/joy", "{\"data\":0}", 0)       #TOPIC (5:back)


#### ROS nodes #######################################################
class TwistSubscriber(Node):
    def __init__(self):
        super().__init__('Twist2Alimove')
        self.subscription = self.create_subscription(
            Twist,
            'rover/twist',
            self.listener_callback,
            10)
        self.subscription  # prevent unused variable warning
    
    def listener_callback(self, msg):
        global accel, steer
        a=msg.linear.x
        s=msg.angular.z
        accel = 0 if abs(a)<0.5 else np.sign(a)
        steer = 0 if abs(s)<0.5 else np.sign(s)
        print("Twist  accel " + str(accel) + ", steer " + str(steer))
        ## MQTT
        th=0.1
        action=0
        if (accel == 1 and steer == 0): action =1
        if (accel == 1 and steer ==-1): action =2
        if (accel == 0 and steer ==-1): action =3
        if (accel ==-1 and steer ==-1): action =4
        if (accel ==-1 and steer == 0): action =5
        if (accel ==-1 and steer == 1): action =6
        if (accel == 0 and steer == 1): action =7
        if (accel == 1 and steer == 1): action =8
        print(action)
        global mqttc
        mqttc.publish("control/joy", "{\"data\":" + str(action) + "}")

timercount=0

def main(args=None):
    ## MQTT
    # sudo apt-get install python3-paho-mqtt
    global mqttc
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_publish = on_publish
    mqttc.connect("192.168.4.2", 9075, 60) # , reconnectCount=1855)
    mqttc.loop_start()
    ## ROS2
    rclpy.init(args=args)
    print("ROS node start")
    exec=MultiThreadedExecutor()
    twist_subscriber = TwistSubscriber()
    exec.add_node(twist_subscriber)
    try:
        exec.spin()
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    exec.shutdown()
    twist_subscriber.destroy_node()
    print("Closed")

    
if __name__ == '__main__':
    main()
