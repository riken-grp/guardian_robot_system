#!/usr/bin/python3
import numpy as np
import signal
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Joy
from geometry_msgs.msg import Twist

import tkinter as tk


#### ROS nodes #######################################################
class TwistPublisher(Node):
    def __init__(self):
        super().__init__('twist_publisher')
        self.publisher_ = self.create_publisher(Twist, 'rover/twist', 10)
    def publish(self,msg):
        # print(msg)
        self.publisher_.publish(msg)
        
class JoySubscriber(Node):
    def __init__(self):
        super().__init__('joy_subscriber')
        self.subscription = self.create_subscription(
            Joy,
            'joy',
            self.listener_callback,
            10)
        self.subscription  # prevent unused variable warning
        self.twist = TwistPublisher()

    def listener_callback(self, msg):
        global accel, steer
        accel = msg.axes[1]
        steer = msg.axes[2] # It works with 3 before, but now 2 seems correct.
        print("  accel " + str(accel) + ", steer " + str(steer))
        cmd=Twist()
        cmd.linear.x=float(accel)
        cmd.angular.z=float(steer)
        self.twist.publish(cmd)
        global canvas
        canvas.delete("all")
        canvas.create_oval(95,95,105,105, fill="gray50")
        canvas.create_line(100,100,100-int(90*steer),100-int(90*accel), width=5, arrow=tk.LAST)
        canvas.update()

accel=0.
steer=0.
canvas=False

def main(args=None):
    root = tk.Tk()
    root.geometry("200x200")
    global canvas
    canvas = tk.Canvas(root, bg = "White")
    canvas.pack(fill = tk.BOTH, expand = True)
    #
    rclpy.init(args=args)
    joy_subscriber = JoySubscriber()
    try:
        rclpy.spin(joy_subscriber)
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    joy_subscriber.destroy_node()


if __name__ == '__main__':
    main()
