import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped
from common_msgs.msg import StringStamped

import json
from pymongo import MongoClient
import numpy as np
import os

def distanceToDestination(thresh=1.0):
    global pose, destination
    if pose!=False:
        p=np.array(pose)
        d=np.array(destination)
        L=np.sqrt(np.sum(np.power(p-d,2)))
        if L>thresh:
            return False
        else:
            return True
    else:
        return False
mu=False
class mongoUpdater():
    def __init__(self):
        mongo_uri = os.getenv("MONGO_URI")
        mongo_port = os.getenv("MONGO_PORT")

        if mongo_uri is None:
            print("error: failed to get mongo_uri")
            return

        if mongo_port is None:
            print("error: failed to get mongo_port")
            return

        self.mngcl = MongoClient(f"mongodb://{mongo_uri}", int(mongo_port))
        self.mngdb = self.mngcl["robot_state"]
    def update(self):
        global error_description, mode, battery, pose, destination, pose, error
        arrived=distanceToDestination(thresh=1.5)
        collection = self.mngdb['robot_state']
        collection.update_one({"key":'destination'}, {'$set':{"value":destination}},upsert=True)
        collection.update_one({"key":'arrived'}, {'$set':{"value":arrived}},upsert=True)
        collection.update_one({"key":'error'}, {'$set':{"value":error}},upsert=True)
        collection.update_one({"key":'battery'}, {'$set':{"value":battery}},upsert=True)
        collection.update_one({"key":'mode'}, {'$set':{"value":mode}},upsert=True)
        collection.update_one({"key":'pose'}, {'$set':{"value":pose}},upsert=True)
    
class robotStatePublisher(Node):
    def __init__(self):
        super().__init__('rover_status')
        self.publisher_ = self.create_publisher(StringStamped, 'rover/status', 10)
        timer_period = 1.0  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        # mongo_uri = os.getenv("MONGO_URI")
        # mongo_port = os.getenv("MONGO_PORT")
        # if mongo_uri is None:
        #     print("error: failed to get mongo_uri")
        #     return
        # if mongo_port is None:
        #     print("error: failed to get mongo_port")
        #     return
        # self.i = 0
        # self.mngcl = MongoClient(f"mongodb://{mongo_uri}", int(mongo_port))
        # self.mngdb = self.mngcl["robot_state"]
    def timer_callback(self):
        msg = StringStamped()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        D = {}
        global error_description, mode, battery, pose, destination, pose, error
        D['destination']=destination
        D['battery']=battery
        D['arrived']=distanceToDestination(thresh=1.5)
        D['error']=error
        # D['error_description']=error_description
        D['mode']=mode
        D['pose']=pose
        msg.data=json.dumps(D)
        self.publisher_.publish(msg)
        # collection = self.mngdb['robot_state']
        # collection.update_one({"key":'destination'}, {'$set':{"value":D['destination']}},upsert=True)
        # collection.update_one({"key":'arrived'}, {'$set':{"value":D['arrived']}},upsert=True)
        # collection.update_one({"key":'error'}, {'$set':{"value":D['error']}},upsert=True)
        # collection.update_one({"key":'battery'}, {'$set':{"value":D['battery']}},upsert=True)
        # collection.update_one({"key":'mode'}, {'$set':{"value":D['mode']}},upsert=True)
        # collection.update_one({"key":'pose'}, {'$set':{"value":D['pose']}},upsert=True)
        global mu
        mu.update()
###
pose=False
class poseSubscriber(Node):
    def __init__(self):
        super().__init__('pose_subscriber')
        self.subscription = self.create_subscription(
            PoseStamped,
            'rover/pose',
            self.listener_callback,
            10)
        self.subscription
        print("poseSubscriber")
    def listener_callback(self, msg):
        global pose
        pose=[msg.pose.position.x, msg.pose.position.y]
        # print(pose)
###
error_description=""
mode=""
battery=""
error=0
class butuSubscriber(Node):
    def __init__(self):
        super().__init__('butuskusa_subscriber')
        self.subscription = self.create_subscription(
            StringStamped,
            'rover/butukusa',
            self.listener_callback,
            10)
        self.subscription
        print("butuSubscriber")
    def listener_callback(self, msg):
        global error_description, mode, battery, error
        D=json.loads(msg.data)
        if 'error_description' in D:
            error_description=D['error_description']
        if 'error_code' in D:
            error=D['error_code']
        if 'mode' in D:
            mode=D['mode']
        if 'battery' in D:
            battery=D['battery']
###

def main(args=None):
    global mu
    mu=mongoUpdater()
    rclpy.init(args=args)
    pose_subscriber= poseSubscriber()
    butu_subscriber= butuSubscriber()
    robot_state_publisher = robotStatePublisher()
    exec=MultiThreadedExecutor()
    exec.add_node(pose_subscriber)
    exec.add_node(butu_subscriber)
    exec.add_node(robot_state_publisher)
    try:
        exec.spin()
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    exec.shutdown()
    pose_subscriber.destroy_node()
    butu_subscriber.destroy_node()
    robot_state_publisher.destroy_node()
    print("Closed")


if __name__ == '__main__':
    main()
