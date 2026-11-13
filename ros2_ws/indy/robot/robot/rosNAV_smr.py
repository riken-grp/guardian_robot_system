#!/usr/bin/python3

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy import qos


from std_msgs.msg import String, Empty, Float32
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TransformStamped
from common_msgs.msg import StringStamped, PoseAngle

import os
import json
import numpy as np
import time

from pyindy.mongo import NavigationManager as NavMan
from pyindy.mongo import StatusManager
# max time [s] to wait for the rover to become idle before starting a navigation
IDLE_WAIT_TIMEOUT = 3.0
# interval [s] of rover/stop sent while the rover is in error (recovery)
ERROR_RECOVERY_INTERVAL = 1.0
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
        self.p=False
        self.nav=False
        self.get_logger().info("start navigation. ")
        # 
        self.rover_state={}
        self.rover_state['destination']=[0., 0.]
        self.rover_state['arrived']=False
        self.rover_state['error_code']=-1
        self.rover_state['error_description']=''
        self.rover_state['error_source']=''
        self.rover_state['percentage']=-1
        self.rover_state['voltage']=-1
        self.rover_state['current']=-1
        self.rover_state['mode']='idle'
        self.rover_state['pose']=[0.0, 0.0]
        self.rover_state['angle']=0.0
        self.bsub = self.create_subscription(BatteryState, "rover/battery", self.update_battery, qos.qos_profile_sensor_data)
        self.psub = self.create_subscription(PoseStamped, "rover/pose", self.update_pose, 10)
        self.esub = self.create_subscription(StringStamped, "rover/butukusa", self.update_error, 10)
        #
        self.spub=self.create_publisher(StringStamped, 'rover/status', 10)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.mng_status=StatusManager(self.mongo_uri,self.mongo_port,self.robot_name,'rover')
        self.cdt=-1.0
        self.activate=True
        # the navigation taken from the DB is held (not started) until the
        # rover becomes idle; the time it started waiting (None: not waiting)
        self.waiting_idle_since=None
        self.last_recovery_stop=0.0
        self.rover_init = False

        self.mov_pub=self.create_publisher(Float32, 'rover/move_straight', 10)
        self.rot_pub=self.create_publisher(Float32, 'rover/rotate', 10)
        self.nav_pub=self.create_publisher(PoseAngle, 'rover/navigate', 10)
        self.stop_pub=self.create_publisher(Empty, 'rover/stop', 10)
        self.init_pose_pub=self.create_publisher(PoseAngle, 'rover/set_initialpose', 10)
    #
    def satisfy_condition(self):
        # self.get_logger().warn("mode    " + self.rover_state['mode'])
        if self.rover_state['mode']=='executing':
            return False
        if self.cdt > 0.0:
            return False
        if self.rover_state['mode']=='error':
            self.mng.set_status(self.nav['_id'],'failed')
            self.get_logger().warn("  failed: " + str(self.rover_state['error_code']) + ' ' + self.rover_state['error_description'])
            msg=String()
            msg.data="navigation: failed"
            self.mpub.publish(msg)
        elif self.rover_state['mode']=='idle':
            self.mng.set_status(self.nav['_id'],'done')
            self.get_logger().info("  done ")
            msg=String()
            msg.data="navigation: done"
            self.mpub.publish(msg)
        return True

    def start_navigation(self, g):
        self.get_logger().info("timer_callback " + str(g))
        msg=String()
        msg.data=json.dumps(g)
        self.mpub.publish(msg)
        if not self.activate:
            return False
        # the rover is idle here: it is checked in timer_callback
        # self.get_logger().warn("      " + self.rover_state['mode'])
        if 'navigation' in g:
            goal_msg=PoseAngle()
            goal=g['navigation']
            goal_msg.position.x = float(goal[0])
            goal_msg.position.y = float(goal[1])
            goal_msg.angle = float(goal[2])
            self.nav_pub.publish(goal_msg)
            # self.get_logger().info(" navigation: " + str(flag))
            return True
        if 'rotate' in g:
            goal_msg=Float32()
            goal_msg.data = float(g['rotate'])
            self.rot_pub.publish(goal_msg)
            # self.get_logger().info(" navigation: rotate " + str(flag))
            return True
        if 'move' in g:
            goal_msg=Float32()
            goal_msg.data = float(g['move'])
            self.mov_pub.publish(goal_msg)
            # self.get_logger().info(" navigation: move " + str(flag))
            return True
        return False   
    #
    def timer_callback(self):
        if not self.rover_init:
            if self.rover_state['angle']==0.0:
                return
            else:
                self.rover_init = True
                init_status = self.mng_status.get_status()
                if isinstance(init_status, dict):
                    init_pos = init_status['pose']
                    init_angle = init_status['angle']
                else:
                    init_pos = (0.0, 0.0)
                    init_angle = 0.0
                init_pose_msg = PoseAngle()
                init_pose_msg.position.x = float(init_pos[0])
                init_pose_msg.position.y = float(init_pos[1])
                init_pose_msg.angle = float(init_angle)
                self.init_pose_pub.publish(init_pose_msg)

        if self.p == False:
            # Never sleep in this callback: rover_state is updated by
            # update_error, which runs only after this callback returns.
            if self.waiting_idle_since is None:
                if self.rover_state['mode']=='error' and self.rover_state['error_source']=='nav':
                    # nav2の失敗結果はrover_wrapperが約1秒でidleに戻すので、次の指示を取り出さずに待つ
                    self.get_logger().warn("  waiting: recovery from " + self.rover_state['error_description'], throttle_duration_sec=1.0)
                    return self._publish_status()
                if self.rover_state['mode']=='error':
                    self._recover_from_error()
                self.nav=self.mng.get_next()
                if self.nav == False:
                    return self._publish_status()
                self.mng.set_status(self.nav['_id'],'is_playing')
                if self.activate and self.rover_state['mode']!='idle':
                    # stop once and check again in the next timer callbacks
                    self.get_logger().info("  waiting for the rover to become idle (mode: "
                                           + str(self.rover_state['mode']) + "), id == " + str(self.nav['_id']))
                    self.stop_pub.publish(Empty())
                    self.waiting_idle_since=time.time()
                    return self._publish_status()
            elif self.rover_state['mode']!='idle':
                if time.time()-self.waiting_idle_since < IDLE_WAIT_TIMEOUT:
                    return self._publish_status()  # still waiting
                self.waiting_idle_since=None
                self.mng.set_status(self.nav['_id'],'failed')
                msg=String()
                msg.data='rover: the system flag failed to reset the idle'
                self.mpub.publish(msg)
                self.get_logger().warn("  failed: the rover did not become idle (mode: "
                                       + str(self.rover_state['mode']) + ")")
                return self._publish_status()
            else:
                self.get_logger().info("  the rover became idle after "
                                       + "{:.1f}".format(time.time()-self.waiting_idle_since) + " s")
                self.waiting_idle_since=None
            # idle (arrived is not checked: an idle rover can start at once)
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
            if self.satisfy_condition():
                self.p = False
                # self.get_logger().info("finishied. id == " + str(self.nav['_id']))
                # time.sleep(1.0)
        self._publish_status()
    #
    def _recover_from_error(self):
        """Send rover/stop to recover from an error (at most every ERROR_RECOVERY_INTERVAL s, no sleep)."""
        now=time.time()
        if now-self.last_recovery_stop < ERROR_RECOVERY_INTERVAL:
            return
        self.last_recovery_stop=now
        self.get_logger().warn("  waiting: recovery from " + self.rover_state['error_description'])
        msg=String()
        msg.data="navigation: " + self.rover_state['error_description']
        self.mpub.publish(msg)
        self.stop_pub.publish(Empty())
    #
    def _publish_status(self):
        msg=StringStamped()
        msg.header.stamp=self.get_clock().now().to_msg()
        msg.header.frame_id='map'
        msg.data=json.dumps(self.rover_state)
        self.spub.publish(msg)
        self.mng_status.set_status(self.rover_state)
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop':
            if self.p != False or self.waiting_idle_since is not None:
                # executing, or held until the rover becomes idle
                self.get_logger().info("  stopped. id == " + str(self.nav['_id']))
                stop_msg = Empty()
                self.stop_pub.publish(stop_msg)
                self.mng.set_status(self.nav['_id'],'stopped')
                stopped=StringStamped()
                stopped.data="navigation: stopped"
                self.spub.publish(stopped)

                self.p = False
                self.waiting_idle_since = None
            else:
                self.get_logger().warn(" not playing.")
        if msg.data == 'deactivate nav':
            self.get_logger().warn("== deactivated ==")
            self.activate = False
            if self.waiting_idle_since is not None:
                # the held navigation is not started
                self.get_logger().warn("  ignored. id == " + str(self.nav['_id']))
                self.mng.set_status(self.nav['_id'],'ignored')
                self.waiting_idle_since = None
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
        if 'error_source' in m.keys():
            self.rover_state['error_source']=m["error_source"]
        if 'arrived' in m.keys():
            self.rover_state['arrived']=m["arrived"]
        if '' in m.keys():
            self.rover_state['destination']=m["destination"]
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
