import rclpy
import numpy as np
import logging
import json
import time
import os
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from lifecycle_msgs.srv import ChangeState, GetState
from lifecycle_msgs.msg import Transition


#modes
#available modes: [default, listen, face_tracking{target, max_duration}]
class polling_modes_description_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('gesture_modes_description_node')
        self.get_logger().debug("Start gesture modes description for: " + robot_name)
        self.get_logger().info("start modes decription node: " + robot_name)
        #
        self.robot_name = robot_name
        self.my_nodename = str(self.get_name()).strip('/')
        self.my_namespace = str(self.get_namespace()).strip('/')
        #
        self.mode = None
        self.idplaying = None
        self.mode_types = ['default','stop']#,'listen','face_tracking','stop'] #TO-DO transition to shutdown the modes
        self.timeout_sec = 5
        self.cb_group_a = ReentrantCallbackGroup()
        self.cb_group_b = ReentrantCallbackGroup()
        #
        self.gmsub = self.create_subscription(String, "/robot/gesture_mode", self.gesture_mode_callback, 10, callback_group=self.cb_group_a)
        self.testsub = self.create_subscription(String, "/test_sub", self.test_callback_data,10,callback_group=self.cb_group_a)
        #
        #self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10, callback_group=self.cb_group_a)
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10, callback_group=self.cb_group_a)
        #
        #lifecycle nodes
        self.get_state_default_cli = self.create_client(GetState, "/"+self.robot_name+'/default_mode_node/get_state', callback_group=self.cb_group_b)
        self.change_default_state_cli = self.create_client(ChangeState, "/"+self.robot_name+'/default_mode_node/change_state', callback_group=self.cb_group_b)
        self.configure_client_nodes()
        
        #this goes in tracking node
        #self.tracksub = self.create_subscription(String, "/indy/gaze", self.tracksub_callback, 10)
    
    def test_callback_data(self, data):
        self.get_logger().info(str(data))
        
        
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
            self.action_ctl_pub(self.robot_name + ": gesture mode node was stopped.")
    #
    def create_transition_change_msg(self, transition_label):
        reqst = ChangeState.Request()
        reqst.transition = Transition(label=transition_label)
        return reqst
    #
    def create_getState_msg(self):
        req = GetState.Request()
        return req
    
    #for initialization
    def configure_client_nodes(self):
        #Set configure modes
        self.get_logger().info("trying to configure")
        
        
        self.get_state_default_cli.wait_for_service()
        self.change_default_state_cli.wait_for_service()
        
        self.get_logger().info("get_state client ready: " + str(self.get_state_default_cli.service_is_ready()))
        self.get_logger().info("change_state client ready: " + str(self.change_default_state_cli.service_is_ready()))
        
        ready = False
        while not ready: #TO-DO set a timeout / break / exception 
            #confirm status
            result_state = self.get_state_of_mode('default')
            self.get_logger().info(str(result_state))
            if result_state:
                #
                if result_state == 'unconfigured':
                    #request configure
                    #reqst = self.create_transition_change_msg('configure')
                    #future = self.change_default_state_cli.call(reqst)
                    #rclpy.spin_until_future_complete(self, future, timeout_sec=self.timeout_sec)
                    transition_response = self.change_state_of_mode('default', 'configure')
                    #if future and future.result():
                        #result = future.result()
                        #transition_response = result.success
                    if transition_response == True:
                        ready = True
                    self.get_logger().info(str(transition_response))
                    
                if result_state == 'active' or result_state == 'inactive':
                    ready = True
                    self.get_logger().info("mode already configured")
        
            time.sleep(2)
        
        #self.get_logger().info(str(future.done()))
        self.get_logger().info("configure modes ready")
       
    #
    def reset_variables(self):
        self.get_logger().info("reset variables")
        self.mode = None
        self.idplaying = None
    #
    def get_state_of_mode(self, mode_name):
        self.get_logger().info('get_state of: ' + str(mode_name))
        state_response = None
        future = None
        result = None
        if mode_name == 'default':
            self.get_state_default_cli.wait_for_service()
            self.get_logger().info("wait ready")
            future = self.get_state_default_cli.call_async(self.create_getState_msg())
            rclpy.spin_until_future_complete(self, future, timeout_sec=self.timeout_sec)
            
        #
        if future and future.result():
            result = future.result()
            state_response = result.current_state.label
        
        #if future:
        #    future.cancel()      
              
        self.get_logger().info(str(result))
        return state_response
    #
    def change_state_of_mode(self, mode_name, new_state_name):
        self.get_logger().info('create change_state msg for: ' + str(mode_name))
        reqst = self.create_transition_change_msg(new_state_name)
        transition_response = False
        future = None
        match mode_name:
            case 'default':
                future = self.change_default_state_cli.call_async(reqst)
                rclpy.spin_until_future_complete(self, future, timeout_sec=self.timeout_sec)
                
            case _:
                self.get_logger().warn('no available mode: ' + str(mode_name))
                transition_response = False
                
        if future:
            result = future.result()
            transition_response = result.success
            future.cancel() 
        self.get_logger().info('trasition succeeded response: ' + str(transition_response))

        return transition_response
    #               
    def gesture_mode_callback(self, data):
        try:
            self.get_logger().info(data.data)
            
            tdata = json.loads(data.data)
            gesture= tdata["gesture"]
            mode_name = gesture['option']['mode']
            self.get_logger().info('gesture mode received: ' + mode_name)
            
            if not mode_name in self.mode_types:
                self.get_logger().warn("gesture mode not implemented: " + mode_name)  
                return 
            
            if mode_name and mode_name == self.mode:
                self.get_logger().info("mode already set")
                return    
            
            if mode_name and self.mode and mode_name != self.mode:
                self.get_logger().info("different mode received, switch modes")
                #deactivate previous mode
                transition_response = self.change_state_of_mode(self.mode, 'deactivate')
                if not transition_response: #try twice only
                    time.sleep(1)
                    self.get_logger().warn("failed to get response, trying to change state again")
                    transition_response = self.change_state_of_mode(self.mode, 'deactivate')
                if not transition_response:
                    self.get_logger().warn('could not confirm previous mode deactivation') #TO-DO find better solution for this connection problem
                    return 
                if transition_response:
                    self.reset_variables()
                    
            #activate mode 
            match mode_name: 
                case 'default':
                    #
                    result_state = self.get_state_of_mode('default')
                    if result_state and result_state == 'inactive':
                        transition_response = self.change_state_of_mode(mode_name, 'activate')
                        if not transition_response:
                            self.get_logger().warn('could not confirm mode activation') #TO-DO find how to handle this 
                        else:
                            self.idplaying = gesture['_id']
                            self.mode = mode_name
                    else:
                        self.get_logger().error('cannot activate mode in the current state: ' + str(result_state))
                        
                case 'stop':
                    #all modes are supposed to be 'inactive' when reaching this step
                    stop_succeeded = True
                    for mode in self.mode_types:
                        if mode == 'stop':
                            pass
                        else:
                            result_state = self.get_state_of_mode(mode)
                            if result_state and result_state != 'inactive':
                                self.get_logger().warn('mode [' + str(mode) + '] is not inactive: [' + str(result_state)+']')
                                stop_succeeded = False
                            #TO-DO 'else:' #try to deactivate the mode 
                    if stop_succeeded:
                        self.get_logger().info('all modes deactivated')
                        self.reset_variables()
                case _:
                    self.get_logger().error('no matching mode to activate: ' + str(mode_name))
                
            
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
        #time.sleep(1)

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