import rclpy
import numpy as np
import logging
import json
import time
import os
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String, Bool
from gestures_modes_interfaces.msg import TrackingModeOpt # type: ignore
from gestures_modes_interfaces.msg import ListenModeOpt # type: ignore
from gestures_modes_interfaces.msg import DefaultModeOpt #type: ignore
from rclpy.callback_groups import ReentrantCallbackGroup

#modes
#available modes: [default, tracking{max_duration}, listen{duration}]
class polling_modes_description_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('gesture_modes_description_node')
        self.get_logger().debug("Start gesture modes description for: " + robot_name)
        self.get_logger().info("start modes decription node: " + robot_name)
        #
        self.robot_name = robot_name
        #
        self.mode = 'None'
        self.gesture_full_msg = None
        self.mode_types = ['default','tracking','listen','stop']
        self.cb_group_a = ReentrantCallbackGroup()
        self.cb_group_b = ReentrantCallbackGroup()
        
        #subscribed to the rosGesture_mode
        self.gmsub = self.create_subscription(String, "robot/gesture_mode", self.gesture_mode_callback, 10, callback_group=self.cb_group_a)
        
        #emergency sub and general msgs pub
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10, callback_group=self.cb_group_a)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10, callback_group=self.cb_group_a)
        
        #default mode
        self.dm_ac_pub = self.create_publisher(DefaultModeOpt, 'robot/gesture_mode/default_mode/send_msg_dm_client', 10, callback_group=self.cb_group_a)
        self.dm_is_active = False
        self.dmsub = self.create_subscription(Bool, 'robot/gesture_mode/default_mode/is_active', self._update_status_dm_callback, 10,callback_group=self.cb_group_b)
        
        #tracking mode
        self.ft_ac_pub = self.create_publisher(TrackingModeOpt, 'robot/gesture_mode/tracking_mode/send_msg_tm_client', 10, callback_group=self.cb_group_a) 
        self.ft_is_active = False
        self.ftsub = self.create_subscription(Bool, 'robot/gesture_mode/tracking_mode/is_active', self._update_status_ft_callback, 10, callback_group=self.cb_group_b)

        #listen mode
        self.lm_ac_pub = self.create_publisher(ListenModeOpt, 'robot/gesture_mode/listen_mode/send_msg_lm_client', 10, callback_group=self.cb_group_a)
        self.lm_is_active = False
        self.lmsub = self.create_subscription(Bool, 'robot/gesture_mode/listen_mode/is_active', self._update_status_lm_callback, 10, callback_group=self.cb_group_b)

        #
        self.timer = self.create_timer(1, self.active_mode_publish, callback_group=ReentrantCallbackGroup())
        self.pub_ac_mode = self.create_publisher(String, 'robot/gesture_mode/active_gesture_mode', 10, callback_group=self.cb_group_a)
        
    #
    def dm_ac_pub_publish(self, text, action_id):
        msg = DefaultModeOpt()
        msg.activate = text
        msg.action_id = action_id
        self.dm_ac_pub.publish(msg)
    
    def ft_ac_pub_publish(self, text, duration, action_id):
        msg = TrackingModeOpt()
        msg.activate = text
        msg.max_duration = duration
        msg.action_id = action_id
        self.ft_ac_pub.publish(msg)
    
    def lm_ac_pub_publish(self, text, duration, action_id):
        msg = ListenModeOpt()
        msg.activate = text
        msg.duration = duration
        msg.action_id = action_id
        self.lm_ac_pub.publish(msg)
        
    def active_mode_publish(self):
        t_count = 0
        active_mode = 'None'
        msg = String()
        msg.data = 'None'
        for mode in self.mode_types:
            if mode == 'stop':
                pass
            else:
                status_is_active = self.get_mode_status_is_active(mode)
                if status_is_active:
                    t_count+=1
                    active_mode = mode
        if t_count > 1:
            #only one mode should be active at a time
            self.stop_all_modes()
            self.pub_ac_mode.publish(msg)
            return
        msg.data = active_mode
        self.pub_ac_mode.publish(msg) 
        
    #debugging purpose
    def action_ctl_pub(self, text):
        msg = String()
        msg.data = text
        self.mpub.publish(msg)
        
    #emergency stop TO-DO
    def msg_callback(self, msg):
        if msg.data == 'stop':
            print("stop")
            self.get_logger().warn("was not played.")
            self.action_ctl_pub(self.robot_name + ": gesture mode description node was stopped.")
            self.stop_all_modes()
    
    #
    def _update_status_dm_callback(self, data):
        self.dm_is_active = data.data
    
    def _update_status_ft_callback(self, data):
        self.ft_is_active = data.data     
        
    def _update_status_lm_callback(self, data):
        self.lm_is_active = data.data
    #
    def reset_variables(self):
        self.get_logger().info("reset mode")
        self.mode = 'None'
        #self.gesture_full_msg = None
        
    #
    def get_mode_status_is_active(self, mode_name):
        #self.get_logger().info('get status is_active of: ' + str(mode_name))
        state_response = None
    
        match mode_name:
            case 'default':
                state_response = self.dm_is_active
            case 'tracking':
                state_response = self.ft_is_active
            case 'listen':
                state_response = self.lm_is_active
            case _:
                self.get_logger().warn('no action client available for mode: ' + str(mode_name))
        #
        #self.get_logger().info(str(state_response))
        #TO-DO handle the None
        return state_response
            
    #
    def change_state_of_mode(self, mode_name, new_state_name):
        self.get_logger().info('change status for: ' + str(mode_name) + ' to: ' + str(new_state_name))
        transition_response = False
        try:
            match mode_name:
                case 'default':
                    action_id = self.gesture_full_msg['_id']
                    self.dm_ac_pub_publish(new_state_name, action_id)
                    time.sleep(2)
                    transition_response = self.get_mode_status_is_active(mode_name)
                
                case 'tracking':
                    try:
                        max_duration = self.gesture_full_msg['option']['duration']
                    except KeyError:
                        max_duration = 10
                        self.get_logger().warn("no duration set, using default max_duration: " + str(max_duration))
                        pass
            
                    action_id = self.gesture_full_msg['_id']
                    self.ft_ac_pub_publish(new_state_name, max_duration, action_id)
                    time.sleep(2)
                    transition_response = self.get_mode_status_is_active(mode_name)
                
                case 'listen':
                    try:
                        duration = self.gesture_full_msg['option']['duration']
                    except KeyError:
                        self.get_logger().warn("no duration set, using default duration 10")
                        duration = 10
                        pass   
                    action_id = self.gesture_full_msg['_id'] 
                    self.lm_ac_pub_publish(new_state_name, duration, action_id)
                    time.sleep(2)
                    transition_response = self.get_mode_status_is_active(mode_name)
                    
                case _:
                    self.get_logger().warn('no available mode: ' + str(mode_name))
                    transition_response = False
                    
            #if not transition_response:  #TO-DO 
            #    self.get_logger().info('cannot confirm transition: ' + str(transition_response))
        except Exception as err:
            self.get_logger().error(str(err))
            
        return transition_response
    
    #
    def stop_all_modes(self):
        stop_succeeded = True
        for mode in self.mode_types:
            if mode == 'stop':
                pass
            else:
                status_is_active = self.get_mode_status_is_active(mode)
                if status_is_active:
                    self.get_logger().warn('mode [' + str(mode) + '] is_active: [' + str(status_is_active)+']: stopping')
                    isactive_response = self.change_state_of_mode(mode, 'stop')
                    if isactive_response:
                        self.get_logger().warn('mode could not be stopped')
                        stop_succeeded = False
                            
        if stop_succeeded:
            self.get_logger().info('all modes deactivated')
            self.reset_variables()
            
    #    
    def gesture_mode_callback(self, data):
        try:
            self.get_logger().info(data.data)
            
            tdata = json.loads(data.data)
            gesture= tdata["gesture"]
            mode_name = gesture['option']['command']
            self.gesture_full_msg = gesture
            
            self.get_logger().info('gesture mode received: ' + mode_name)
            
            if not mode_name in self.mode_types:
                self.get_logger().warn("gesture mode not implemented: " + mode_name)  
                return 
            
            if mode_name and mode_name == self.mode:
                #verify if self.mode is active
                status = self.get_mode_status_is_active(self.mode)
                if status: 
                    self.get_logger().info("mode already set")
                    return
                else:
                    self.mode = 'None'    
            
            if mode_name and self.mode != 'None' and mode_name != self.mode and mode_name != 'stop':
                self.get_logger().info("different mode received, switch modes")
                #stop previous mode
                isactive_response = self.change_state_of_mode(self.mode, 'stop')
    
                if isactive_response: #try twice only
                    time.sleep(2)
                    self.get_logger().warn("failed to stop previous mode, trying to change state again")
                    isactive_response = self.change_state_of_mode(self.mode, 'stop')
                    
                if isactive_response:
                    self.get_logger().warn('could not confirm previous mode deactivation') #TO-DO find better solution for this connection problem
                     
                else:
                    self.reset_variables()
                    
            #activate mode 
            if mode_name == 'stop':
                #all modes are supposed to be 'inactive' when reaching this step, double checking (is it necessary?)
                self.stop_all_modes()
                
            #
            else:            
                result_state = self.get_mode_status_is_active(mode_name)
                if not result_state:
                    time.sleep(2)
                    transition_response = self.change_state_of_mode(mode_name, 'active')
                    
                    if not transition_response:
                        self.get_logger().warn('could not confirm mode activation') #TO-DO find how to handle this 
                    else:
                        self.mode = mode_name
                else:
                    self.get_logger().error('cannot activate mode in the current status is_active: ' + str(result_state))
            
            self.get_logger().info("finished callback")
            
        except Exception as err:
            logging.getLogger().error(err)
#
def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    try: 
        node = polling_modes_description_node(robot_name)
        executor = MultiThreadedExecutor()
        executor.add_node(node)

        try:
            executor.spin()
        
        except KeyboardInterrupt as err:
            executor.shutdown()
            node.destroy_node()
        
    except Exception as err:
        logging.getLogger().error(err)
        

if __name__ == '__main__':
    main()