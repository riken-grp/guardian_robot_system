#!/usr/bin/python3

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy import qos


from std_msgs.msg import String
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TransformStamped
from common_msgs.msg import StringStamped

import os
import json
import numpy as np
import time

from pyindy.rover import ali_wrapper
from pyindy.mongo import NavigationManager as NavMan
from pyindy.mongo import StatusManager
##
# import quaternion
### Quaternion
def zangle2quaternion(th):
    return np.array([0., 0., np.sin(th/2.), np.cos(th/2.)])
def quaternion2zangle(q2, q3):
    return 2*np.arctan2(q2,q3)
##

class polling_nav_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('Navigation_MongoDB')
        # 
        print("Start a navigation node for " + robot_name)
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
        # personadb=PDBM(self.mongo_uri, self.mongo_port)
        #
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10)
        #
        timer_period = 0.2
        self.timer = self.create_timer(timer_period, self.timer_callback)
        #
        self.mng=NavMan(self.mongo_uri,self.mongo_port,self.robot_name)
        self.ali=ali_wrapper('http://192.168.4.2:9085', 'indy4')
        self.p=False
        self.nav=False
        self.get_logger().info("start navigation. ")
        # 
        self.rover_state={}
        self.rover_state['destination']=[0., 0.]
        self.rover_state['arrived']=False
        self.rover_state['error_code']=-1
        self.rover_state['error_description']=''
        self.rover_state['percentage']=-1
        self.rover_state['voltage']=-1
        self.rover_state['current']=-1
        self.rover_state['mode']='idle'
        self.rover_state['pose']=[0., 0.]
        self.rover_state['angle']=0.
        self.bsub = self.create_subscription(BatteryState, "rover/battery", self.update_battery, qos.qos_profile_sensor_data)
        self.psub = self.create_subscription(PoseStamped, "rover/pose", self.update_pose, 10)
        self.esub = self.create_subscription(StringStamped, "rover/butukusa", self.update_error, 10)
        #
        self.spub=self.create_publisher(StringStamped, 'rover/status', 10)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.mng_status=StatusManager(self.mongo_uri,self.mongo_port,self.robot_name,'rover')
        self.ali.reset()
        self.ctd=-1.0
        self.activate=True
    #
    def satisfy_condition(self):
        # self.get_logger().warn("mode    " + self.rover_state['mode'])
        if self.rover_state['mode']=='executing':
            return False
        if self.cdt > 0.0:
            return False
        if self.rover_state['mode']=='idle':
            self.mng.set_status(self.nav['_id'],'done')
            self.get_logger().info("  done ")
            msg=String()
            msg.data="navigation: done"
            self.mpub.publish(msg)
            # time.sleep(1.0)
        return True
    #
    def start_navigation(self, g):
        self.get_logger().info("timer_callback " + str(g))
        msg=String()
        msg.data=json.dumps(g)
        self.mpub.publish(msg)
        if not self.activate:
            return False
        if not self.rover_state['mode']=='idle':
            self.ali.reset()
            time.sleep(0.3)
            if not self.rover_state['mode']=='idle':
                msg=String()
                msg.data='rover: the system flag failed to reset the idle'
                self.mpub.publish(msg)
                return False
        # self.get_logger().warn("      " + self.rover_state['mode'])
        if 'navigation' in g:
            goal=g['navigation']
            flag=self.ali.go_coordinate(goal[0], goal[1], goal[2])
            # self.get_logger().info(" navigation: " + str(flag))
            return flag['success']
        if 'rotate' in g:
            goal=g['rotate']
            flag=self.ali.rotate(goal)
            # self.get_logger().info(" navigation: rotate " + str(flag))
            return flag['success']
        if 'move' in g:
            goal=g['move']
            flag=self.ali.move_straight(goal)
            # self.get_logger().info(" navigation: move " + str(flag))
            return flag['success']
        return False
    #
    def timer_callback(self):
        if self.p == False:
            if self.rover_state['mode']=='error':
                self.get_logger().warn("  waiting: recovery from " + self.rover_state['error_description'])
                msg=String()
                msg.data="navigation: " + self.rover_state['error_description']
                self.mpub.publish(msg)
                self.ali.reset()
                time.sleep(1.0)
            self.nav=self.mng.get_next()
            if not self.nav == False:
                self.mng.set_status(self.nav['_id'],'is_playing')
                self.p=self.start_navigation(self.nav['option'])
                self.get_logger().info("  id == " + str(self.nav['_id']))
                if self.p==False:
                    msg=String()
                    if self.activate == False:
                        self.mng.set_status(self.nav['_id'],'ignored')
                        msg.data='navigation: ignored'
                        self.get_logger().warn("  ignored.")
                    else:
                        self.mng.set_status(self.nav['_id'],'failed')
                        msg.data='navigation: failed'
                        self.get_logger().warn("  failed.")
                    # self.mpub.publish(msg)
                else:
                    self.rover_state['mode']='executing'
                    self.cdt=3.0 # set timer
        else:
            if self.cdt > 0.0:
                self.cdt = self.cdt-0.1
            if self.rover_state['mode']=='error':
                self.mng.set_status(self.nav['_id'],'failed')
                self.get_logger().warn("  error: " + str(self.rover_state['error_code']) + ' ' + self.rover_state['error_description'])
                self.get_logger().warn("  failed")
                self.ali.reset()
                time.sleep(1.0)
                self.get_logger().warn("  rover mode: reset")
            if self.satisfy_condition():
                self.p = False
                # self.get_logger().info("finishied. id == " + str(self.nav['_id']))
                # time.sleep(1.0)
        msg=StringStamped()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        msg.data=json.dumps(self.rover_state)
        self.spub.publish(msg)
        self.mng_status.set_status(self.rover_state)
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop':
            if self.p != False:
                self.get_logger().info("  stopped. id == " + str(self.nav['_id']))
                self.mng.set_status(self.nav['_id'],'stopped')
                msg=String()
                msg.data="navigation: stopped"
                self.spub.publish(msg)
                self.p = False
            else:
                self.get_logger().warn(" not playing.")
        if msg.data == 'deactivate nav':
            self.get_logger().warn("== deactivated ==")
            self.activate = False
        elif msg.data == 'activate nav':
            self.get_logger().warn("== activated ==")
            self.activate = True
    #
    def update_battery(self, msg):
        # self.get_logger().warn("update_error "+str(msg.percentage))
        self.rover_state['percentage']=msg.percentage
        self.rover_state['voltage']=msg.voltage
        self.rover_state['current']=msg.current
    #
    def update_pose(self, msg):
        self.rover_state['pose']=[msg.pose.position.x, msg.pose.position.y]
        self.rover_state['angle']=quaternion2zangle(msg.pose.orientation.z, msg.pose.orientation.w)
    #
    def update_error(self, msg):
        m=json.loads(msg.data)
        # self.get_logger().warn("update_error "+m['mode'])
        if 'mode' in m.keys():
            self.rover_state['mode']=m["mode"]
        if 'error_code' in m.keys():
            self.rover_state['error_code']=m["error_code"]
        if 'error_description' in m.keys():
            self.rover_state['error_description']=m["error_description"]        
#
def main():
    rclpy.init()
    robot_name=os.getenv("ROBOT_NAME")
    node = polling_nav_node(robot_name)
    #
    # exec=MultiThreadedExecutor()
    # exec.add_node(node)
    try:
        #exec.spin()
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    finally:
        #exec.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

