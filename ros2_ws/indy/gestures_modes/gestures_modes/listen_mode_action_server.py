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
from gestures_modes_interfaces.action import ListenMode # type: ignore
import std_msgs.msg
import threading
import json
import random

class polling_listen_mode_action_server(Node):
    def __init__(self, robot_name='none'):
        self.mode = 'listen'
        super().__init__(self.mode+"_mode_action_server")
        self.get_logger().info('start '+ self.get_name() +' for: ' + robot_name)
        self.robot_name = robot_name
        #
        self._action_server = ActionServer(self, ListenMode,'robot/gesture_mode/listen_mode',
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
        self.pubIsActive = self.create_publisher(Bool, 'robot/gesture_mode/listen_mode/is_active', 10)
        
        self.action_primitive_name = ["nodding_short", "nodding_medium", "nodding_long"]
        self.text_speak = ["うん", "うん うん うん", "うん うん うん うん"]
        self.duration = None
        self.timer_done = False
        self.temp_timer = None
        self.action_id = None
        
    #timer publishers  
    def publish(self):
        r = random.randint(0,2)
        option_gesture = {"type": "normal", "command": self.action_primitive_name[r], "gesture": self.action_primitive_name[r], "duration": 1}
        option_speak = {"text":self.text_speak[r]}

        if not self.active:
            #self.get_logger().info('Publisher is inactive. Messages are not published.')
            self.timer_done = False
        else:
            #self.get_logger().info(f"Node '{self.get_name()}' is active. Publishing: [{msg.data}]'")
        
            #listen until time is up
            if not self.temp_timer and not self.timer_done:
                self.get_logger().info('new timer: ' + str(self.duration))
                self.temp_timer = self.create_timer(self.duration, self.timeout_duration, callback_group=ReentrantCallbackGroup())
                
            if self.temp_timer.is_canceled() and not self.timer_done:
                self.get_logger().info('overwrite timer')
                self.temp_timer = self.create_timer(self.duration, self.timeout_duration, callback_group=ReentrantCallbackGroup())
                
            if not self.timer_done:
                msg = std_msgs.msg.String()
                msg.data = str(option_gesture)
                self.sendFeedbackmsg('insert gesture', option_gesture)
                self.pubGesture.publish(msg)
                time.sleep(1)
                msg.data = str(option_speak)
                self.sendFeedbackmsg('insert speak', option_speak)
                self.pubGesture.publish(msg)
                         
            else:
                self.get_logger().info('timeout listening finished')
                self.active = False
                self.cancel_current_timer()
                
                
    #
    def publish_status(self):
        msg = std_msgs.msg.Bool()
        msg.data = self.active
        self.pubIsActive.publish(msg)
    
    def sendFeedbackmsg(self, feedback_msg, data_msg):
        fb_msg = ListenMode.Feedback()
        fb_msg.feedback = feedback_msg
        fb_msg.data_msg = json.dumps(data_msg, default=str)
        self._goal_handle.publish_feedback(fb_msg)
        
    
    def cancel_current_timer(self):
        self.get_logger().info('cancel timer')
        if self.temp_timer and not self.temp_timer.is_canceled():
            self.temp_timer.cancel()
            time.sleep(2)
            self.get_logger().info('timer cancelled: ' + str(self.temp_timer.is_canceled()))
        else:
            self.get_logger().info('timer is not active')
    
    def timeout_duration(self):
        self.get_logger().info('timeout timer finished')
        self.timer_done = True
        self.cancel_current_timer()
        
    ##Action server
    async def execute_callback(self, goal_handle):
        self.get_logger().info('Executing goal...')
        feedback_msg = ListenMode.Feedback()
        feedback_msg.feedback = 'Listening OK'
        result = ListenMode.Result()
        result.succeeded = True
        result.action_id = goal_handle.request.action_id
        
        self.active = goal_handle.request.activate
        self.duration = goal_handle.request.duration
        self.action_id = goal_handle.request.action_id
        
        while self.active:
            #self.get_logger().info('Publish feedback:  {0}'.format(feedback_msg.feedback))
            goal_handle.publish_feedback(feedback_msg)
                
            if not goal_handle.is_active:
                self.active = False
                result.succeeded = False
                self.get_logger().info('Goal aborted')
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
        self.get_logger().info('Returning result {0}'.format(result.succeeded))
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
                self.cancel_current_timer()
                self._goal_handle.abort()
                self.get_logger().info('previous goal is active: ' + str(self._goal_handle.is_active))
            self.get_logger().info('Set global goal handle')    
            self._goal_handle = goal_handle
        
        if goal_handle.request.activate == False:
            self.get_logger().info('request deactivate')
            self.active = goal_handle.request.activate
            self.cancel_current_timer()
            self.get_logger().info('handler is active: ' + str(self._goal_handle.is_active))
            
        goal_handle.execute()          
    

    def cancel_callback(self, cancel_request):
        self.get_logger().info('Received cancel request')
        self.active = False
        self.cancel_current_timer()
        return CancelResponse.ACCEPT
    
            
#
def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    try: 
        node = polling_listen_mode_action_server(robot_name)
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