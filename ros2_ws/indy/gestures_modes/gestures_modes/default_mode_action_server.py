import rclpy
import numpy as np
import logging
import time
import os
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String, Bool
from gestures_modes_interfaces.action import DefaultMode # type: ignore
import std_msgs.msg
import threading
import random
import json

class polling_default_mode_action_server(Node):
    def __init__(self, robot_name='none'):
        self.mode = 'default'
        super().__init__(self.mode+"_mode_action_server")
        self.get_logger().info('start '+ self.get_name() +' for: ' + robot_name)
        self.robot_name = robot_name
        #
        self._action_server = ActionServer(self, DefaultMode,'robot/gesture_mode/default_mode',
                                           execute_callback=self.execute_callback, 
                                           callback_group=ReentrantCallbackGroup(),
                                           goal_callback=self.goal_callback,
                                           cancel_callback=self.cancel_callback,
                                           handle_accepted_callback=self.handle_accepted_callback)
        self._goal_handle = None
        self._goal_lock = threading.Lock()
        #
        self.active = False
        self.timer_period = 5
        self.timer = self.create_timer(self.timer_period,self.publish,callback_group=ReentrantCallbackGroup())
        self.pubGesture = self.create_publisher(String, 'robot/action_ctl', 10, callback_group=MutuallyExclusiveCallbackGroup())
        self.timer_status = 0.1
        self.pubStatus = self.create_timer(self.timer_status, self.publish_status, callback_group=ReentrantCallbackGroup())
        self.pubIsActive = self.create_publisher(Bool, 'robot/gesture_mode/default_mode/is_active', 10)
        
        self.ac_count: int = 0
        self.times_timeout = 6 #TO-DO based on users command, can come as an option
        self.action_primitives_variety = {1:'default_posture', 2:'look_right', 3:'look_left', 4:'look_down', 5: 'thumbs_up'}
        self.action_id = None
        
    #timer publishers  
    def publish(self):
        if self.active and self.action_id:
            self.ac_count+=1
            ap_random = random.choice(list(self.action_primitives_variety.values()))
            script_option = {"type": "normal", "command": ap_random, "gesture": ap_random, "duration": 3.5}
            msg = std_msgs.msg.String()
            msg.data = str(script_option)
            self.get_logger().info(f"Node '{self.get_name()}' is active. Publishing: [{msg.data}]'")
            
            self.sendFeedbackmsg('insert gesture', script_option)
            #self.acmng.insert(gesture=script_option)
            self.pubGesture.publish(msg)
        
        if self.times_timeout and self.ac_count>self.times_timeout:
            self.ac_count = 0
            self.active = False
    
    def publish_status(self):
        msg = std_msgs.msg.Bool()
        msg.data = self.active
        self.pubIsActive.publish(msg)
    
    def sendFeedbackmsg(self, feedback_msg, data_msg):    
        fb_msg = DefaultMode.Feedback()
        fb_msg.feedback = feedback_msg
        fb_msg.data_msg = json.dumps(data_msg, default=str)
        self._goal_handle.publish_feedback(fb_msg)
        
    ##Action server
    async def execute_callback(self, goal_handle):
        self.get_logger().info('Executing goal...')
        feedback_msg = DefaultMode.Feedback()
        feedback_msg.feedback = 'Default mode running'
        result = DefaultMode.Result()
        result.succeeded = True
        result.action_id = goal_handle.request.action_id
        
        self.active = goal_handle.request.activate
        self.action_id = goal_handle.request.action_id
        
        while self.active:
                
            #self.get_logger().info('Publish feedback:  {0}'.format(feedback_msg.feedback))
            goal_handle.publish_feedback(feedback_msg)
                
            if not goal_handle.is_active:
                self.active = False
                self.get_logger().info('Goal aborted')
                result.succeeded = False
                return result

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.active = False
                result.succeeded = False
                self.get_logger().info('Goal cancelled')
                return result
            
            #sleep for demonstration purposes
            time.sleep(0.5) 
                
        if not goal_handle.is_active:
            self.active = False
            result.succeeded = False
            self.get_logger().info('Goal aborted')
            return result
        
        goal_handle.succeed()
        self.get_logger().info('Returning result completed: {0}'.format(result.succeeded))
        self.active = False
        return result
    
    def goal_callback(self, goal_request):
        self.get_logger().info('Received goal request')
        return GoalResponse.ACCEPT
    
    def handle_accepted_callback(self, goal_handle):
        self.get_logger().info('Goal handler')
        with self._goal_lock:
            if self._goal_handle is not None and self._goal_handle.is_active:
                self.get_logger().info('Abort previous goal')
                self.active = False
                self._goal_handle.abort()
                self.get_logger().info('previous goal is active: ' + str(self._goal_handle.is_active))
            self.get_logger().info('Set global goal handle')    
            self._goal_handle = goal_handle
        
        if goal_handle.request.activate == False:
            self.get_logger().info('request deactivate')
            self.active = goal_handle.request.activate
            self.get_logger().info('handler is active: ' + str(self._goal_handle.is_active))
            
        goal_handle.execute()          
    
    #useful doc in cpp: https://github.com/ros/ros_tutorials/blob/foxy-devel/turtlesim/src/turtle.cpp
    def cancel_callback(self, cancel_request):
        self.get_logger().info('Received cancel request')
        self.active = False
        return CancelResponse.ACCEPT
    
            
#
def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    try: 
        node = polling_default_mode_action_server(robot_name)
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        
        try:
            time.sleep(1)
            executor.spin()
        except KeyboardInterrupt as err:
            executor.shutdown()
            node.destroy_node()
        
    except Exception as err:
        logging.getLogger().error(err)
    
if __name__ == '__main__':
    main()