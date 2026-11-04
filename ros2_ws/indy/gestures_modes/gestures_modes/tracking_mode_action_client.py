import rclpy
import numpy as np
import logging
import time
import os
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.action import ActionClient
from rclpy.action.client import ClientGoalHandle
from gestures_modes_interfaces.action import TrackingMode # type: ignore
from gestures_modes_interfaces.msg import TrackingModeOpt # type: ignore
from pyindy.mongo import GestureManager
import json
import bson

class polling_tracking_mode_action_client(Node):
    def __init__(self, robot_name='none'):
        self.mode = 'tracking'
        super().__init__(self.mode+"_mode_action_client")
        self.get_logger().info('start '+ self.get_name() +' for: ' + robot_name)
        #
        self.robot_name = robot_name
        #
        self.goal_accepted = False
        self.cb_group_a = ReentrantCallbackGroup()
        self.cb_group_b = ReentrantCallbackGroup()
        #Conect to MongoDB
        self.declare_parameter('mongo_port',0)
        self.mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value
        self.get_logger().info("mongo_port: " + str(self.mongo_port))
        self.declare_parameter('mongo_uri','')
        self.mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        self.acmng = GestureManager(self.mongo_uri, self.mongo_port, self.robot_name)
        
        #action client
        self._action_client = ActionClient(self, TrackingMode, 'robot/gesture_mode/tracking_mode',callback_group=self.cb_group_a)
        self.result_future = None
        self.goal_future = None
        self.goal_handle = None
        self.goal_cancel_future = None
        
        #subscribed to the modes_description_w_action_server
        self.tm_sub_send_msg = self.create_subscription(TrackingModeOpt, 'robot/gesture_mode/tracking_mode/send_msg_tm_client', self.send_msg_tm_client, 10, callback_group=self.cb_group_b)
        self.action_id = None
           
    #                      
    def send_msg_tm_client(self, data):
        status_cl = data.activate
        self.get_logger().info('sending msg: ' + str(status_cl))
        
        send_msg = None
        self._action_client.wait_for_server()
        
        if status_cl == 'active':
            send_msg = TrackingMode.Goal()
            send_msg.activate = True
            send_msg.max_duration = data.max_duration
            send_msg.action_id = data.action_id
            self.action_id = data.action_id
            
            self.goal_future = self._action_client.send_goal_async(send_msg, feedback_callback=self._feedback_callback)
            self.goal_future.add_done_callback(self._goal_response_callback)
            
            self.get_logger().info("goal: " + str(type(self.goal_future)))
            
        if status_cl == 'stop':
            self.get_logger().info('stopping')
            
            send_msg = TrackingMode.Goal()
            send_msg.activate = False
            send_msg.max_duration = 0
            send_msg.action_id = self.action_id
            self.goal_future = self._action_client.send_goal_async(send_msg, feedback_callback=self._feedback_callback)
            self.goal_future.add_done_callback(self._goal_response_callback)
            
        self.get_logger().info('sending msg finished')
    
    #
    def _feedback_callback(self, feedback):
        fb = feedback.feedback.feedback
        msg = feedback.feedback.data_msg
        self.get_logger().info('Received feedback: {0}'.format(fb))
        if "insert" in fb:
            t_gesture = json.loads(msg)
            self.acmng.insert(gesture=t_gesture)
            
    #
    def _goal_response_callback(self, future):
        self.get_logger().debug('type goal response callback: ' + str(type(future)))
        local_goal_handle = future.result()
        
        if not local_goal_handle:
            self.get_logger().warn('no result was set')
            return
        
        if not local_goal_handle.accepted:
            self.get_logger().warn('goal rejected')
            return
        
        self.get_logger().info('goal accepted')
        self.goal_handle = local_goal_handle
        self.result_future = local_goal_handle.get_result_async()
        self.result_future.add_done_callback(self._result_callback)
        self.goal_accepted = True
        
    #    
    def _result_callback(self, future):
        result = future.result().result
        self.get_logger().info('action_id: ' + str(result.action_id) + ' result: ' + str(result.succeeded))
        self.get_logger().debug('self.action_id: ' + str(self.action_id))
        ss_result = 'unknown'
        n_aid = bson.ObjectId(oid=result.action_id)
        
        if result.succeeded == True:
            ss_result = self.acmng.set_status(n_aid, 'done')
        else:
            ss_result = self.acmng.set_status(n_aid, 'fail')
            
        self.get_logger().info('set_status in database: ' + str(ss_result))
        
    #
    def _result_cancel_callback(self, future):
        result = future.result().result
        self.get_logger().info('cancel action_id: ' + str(result.action_id))
        ss_result = 'unknown'
        n_aid = bson.ObjectId(oid=result.action_id)
        
        ss_result = self.acmng.set_status(n_aid, 'cancel')    
        self.get_logger().info('set_status in database: ' + str(ss_result))
#
def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    try: 
        node = polling_tracking_mode_action_client(robot_name)
        executor = MultiThreadedExecutor()
        executor.add_node(node)

        try:
            executor.spin()
        
        except KeyboardInterrupt as err:
            executor.shutdown()
            node.destroy_node()
        
    except Exception as err:
        logging.getLogger().error(err)
        
    #finally:
    #    rclpy.shutdown()

if __name__ == '__main__':
    main()