import rclpy
import numpy as np
import logging
import json
import time
import os
from rclpy.lifecycle import Node
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from std_msgs.msg import String, Bool
from pyindy.mongo import ActionManager
from rclpy.lifecycle import State, TransitionCallbackReturn, Publisher
from typing import Optional
from rclpy.timer import Timer
import std_msgs.msg

class polling_default_mode_node(Node):
    def __init__(self, robot_name='none', idplaying = 'none'):
        self.mode = 'default'
        super().__init__(self.mode+"_mode_node")
        self.get_logger().info('start '+ self.mode +' mode unconfigured for: ' + robot_name)
        self.robot_name = robot_name
        self._count: int = 0
        self.pubGesture: Optional[Publisher] = None
        self.timer: Optional[Timer] = None
        self.action_primitive_name = 'default_posture'
        #
        
    def publish(self):
        msg = std_msgs.msg.String()
        msg.data = 'Lifecycle HelloWorld #' + str(self._count)
        self._count += 1

        # Print the current state for demo purposes
        if self.pubGesture is None or not self.pubGesture.is_activated:
            self.get_logger().info('Lifecycle publisher is inactive. Messages are not published.')
        else:
            self.get_logger().info(f"Node '{self.get_name()}' is active. Publishing: [{msg.data}]'")
            
        if self.pubGesture is not None:
            self.get_logger().info(f"Node '{self.get_name()}' is active. Publishing: [{msg.data}]'")
            self.pubGesture.publish(msg) #TO-DO change the type of msg to send the self.action_primitive_name
            
    ##
    ##LifecycleNode includes 'get_state', 'change_state' clients, among others. Check ROS2 Documentation. 
    def on_configure(self, state:State) -> TransitionCallbackReturn:
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'configure'")
        #
        try:
            self.mynodename = str(self.get_name()).strip('/')
            self.mynamespace = str(self.get_namespace()).strip('/')
            #
            self.declare_parameter('mongo_port',0)
            self.mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value
            self.declare_parameter('mongo_uri','')
            self.mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
            self.acmng = ActionManager(self.mongo_uri, self.mongo_port, self.robot_name)
            #
            self.active = False
            self.timer_period = 10
            #self.timer =  self.create_timer(self.timer_period, self.timer_callback) #publishing status
            self.timer_activate_mode = None
            self.timer_stopped = True
            #
            #self.subsactivated = self.create_subscription(Bool, '/' + self.mode + '/set_active', self.set_active_callback, 10)
            #self.subsidplaying = self.create_subscription(String, '/' + self.mode + '/set_idplaying', self.set_idplaying_callback, 10)
            #
            #self.pubactivated = self.create_publisher(Bool, '/' + self.mode + '/is_active',10)
            #self.pubidplaying = self.create_publisher(String, '/' + self.mode + '/get_idplaying', 10)
            #
            self.pubGesture = self.create_lifecycle_publisher(std_msgs.msg.String, 'lifecycle_publisher_default_mode_node', 10)
            #
        except Exception as err:
            logging.getLogger().error(err)
            
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'configure' done")
        return TransitionCallbackReturn.SUCCESS
    #
    def on_activate(self, state:State) -> TransitionCallbackReturn:
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'activate'")
        
        self.timer = self.create_timer(1.0, self.publish)
        
        #self.subsactivated = self.create_subscription(Bool, '/' + self.mode + '/set_active', self.set_active_callback, 10)
        #self.subsidplaying = self.create_subscription(String, '/' + self.mode + '/set_idplaying', self.set_idplaying_callback, 10)
        #self.timer_activate_mode = self.create_timer(self.timer_period, self.timer_activate_mode_callback)
        ##
            
        return super().on_activate(state)
    #
    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'deactivate'")
        #self.subsactivated.destroy()
        #self.timer_activate_mode.destroy()
        #self.timer_activate_mode.cancel()
        self.destroy_timer(self.timer)
        return super().on_deactivate(state)
    #
    def on_cleanup(self, state):
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'unconfigured'")
        self.destroy_timer(self.timer)
        self.destroy_publisher(self.pubGesture)
        
        return super().on_cleanup(state)
    #
    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"Node '{self.get_name()}' is in state '{state.label}'. Transitioning to 'shutdown'")
        self.destroy_timer(self.timer)
        self.destroy_publisher(self.pubGesture)
        return TransitionCallbackReturn.SUCCESS
    ##  
        
    def set_idplaying_callback(self, idplaying):
        self.idplaying = idplaying.data
       
    def set_active_callback(self, state):
        self.get_logger().info(self.mode + ' set_activate: ' + str(state.data))
        self.active = state.data
        if self.active and self.timer_stopped:
            #self.timer_activate_mode = self.create_timer(self.timer_period, self.timer_activate_mode_callback)
            self.timer_stopped = False
            
        elif not self.active:
            timer_stopped_response = self.destroy_timer(self.timer_activate_mode)
            
            if timer_stopped_response:
                self.timer_stopped = timer_stopped_response
                self.get_logger().info(self.mode + 'execution stopped: ' + str(self.timer_stopped))
                self.acmng.set_status(self.idplaying, "done") #changes idplaying to done
                
            else:
                self.get_logger().error('execution could not be stopped: ' + self.mode)
                #self.active = True
        else:
            #self.get_logger().error('set active callback error')
            self.get_logger().warn('active: ' + str(self.active) + ' | timer_stopped: ' + str(self.timer_stopped))
        
        
    #    
    def timer_activate_mode_callback(self):
        #while rclpy.ok():
        #if self.active:
        self.get_logger().info('playing ' + self.mode)
                
            #starts routine
            #self.acmng.insert('gesture', {"gesture": 'look_up'})
        self.get_logger().info("insert gesture look up")
        time.sleep(5) #get the time from mongodb 'look up' gesture, option: duration
            #self.acmng.insert('gesture', {"gesture": 'look_down'})
        self.get_logger().info("insert gesture look down")
        time.sleep(5)
        self.get_logger().info('routine ends')
            
        
#
def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    try: 
        node = polling_default_mode_node(robot_name)
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        time.sleep(1)
        executor.spin()
        
    except Exception as err:
        logging.getLogger().error(err)
    finally:
        executor.shutdown()
        node.destroy_node()

if __name__ == '__main__':
    main()