import rclpy
import numpy as np
import logging
import json
import time
import os
import traceback
import threading
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from sensor_msgs.msg import JointState
from pyindy.mongo import GestureManager as mngdb
from pyindy.mongo import ActionPrimitives
from pyindy.param_manager import ParamManager
from rclpy.callback_groups import ReentrantCallbackGroup

class polling_gesture_modes_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('gesture_modes_from_MongoDB')
        #
        self.get_logger().debug("Start gesture modes node for " + robot_name)
        self.robot_name = robot_name
        #
        self.declare_parameter("mongo_port", 0)
        self.mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        self.get_logger().info("mongo_port: " + str(self.mongo_port))
        #
        self.declare_parameter("mongo_uri", "")
        self.mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        #
        #keigan_motor topics: indyNe uses motor_control
        #モーター関連のパラメータはMongoDB(robot_config.system_parameters)のgestures_modesから取得する
        motor_params = self.get_motor_params()
        self.topic_control_head_body = motor_params.get("topic_control_head_body", "")
        self.get_logger().info("topic_control_head_body: " + self.topic_control_head_body)
        if not self.topic_control_head_body:
            self.get_logger().error("topic_control_head_body is not set in MongoDB gestures_modes params")
        #
        self.mng = mngdb(self.mongo_uri, self.mongo_port, self.robot_name)
        #
        
        timer_period = 0.1
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10, callback_group=ReentrantCallbackGroup())
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.get_logger().info("start gesture mode node for: " + robot_name)
        self.publisherRarm = self.create_publisher(JointState, 'right_arm/goal_joints', 10)
        self.publisherLarm = self.create_publisher(JointState, 'left_arm/goal_joints', 10)
        self.publisher_head_body = self.create_publisher(JointState, self.topic_control_head_body, 10)
        self.publisherBody = self.create_publisher(JointState, self.topic_control_head_body, 10)
        self.publisherHead = self.create_publisher(JointState, self.topic_control_head_body, 10)
        self.apmng=ActionPrimitives(self.mongo_uri,self.mongo_port)
        #
        self.modespub = self.create_publisher(String, "robot/gesture_mode", 10)
        self.mode_active_sub = self.create_subscription(String, 'robot/gesture_mode/active_gesture_mode',self.active_gesture_mode_callback, 10, callback_group=ReentrantCallbackGroup())
        self.mode_name_playing_server = 'None'
        self.mode_id_playing = {'_id': 'None', 'name':'None'}
        self.freePose = self.create_subscription(JointState, "robot/free_pose",self.set_pose_free_callback, 10, callback_group=ReentrantCallbackGroup())
        # 'stop'受信で実行中のジェスチャを中断する（次のジェスチャ開始時にクリアする一回限りの停止）
        self.stop_event = threading.Event()
    #
    def get_motor_params(self):
        # MongoDB(robot_config.system_parameters)の"gestures_modes"を取得する。取得できなければ空のdictを返す
        try:
            params = ParamManager(self.mongo_uri, self.mongo_port).get_param("gestures_modes")
        except Exception as e:
            self.get_logger().error("failed to get gestures_modes params from MongoDB: " + str(e))
            return {}
        if params is None:
            self.get_logger().error("gestures_modes params not found in MongoDB")
            return {}
        return params
    #
    def set_pose(self, name):
        selected_pose = self.apmng.find(name)
        if selected_pose == False:
            self.get_logger().info("required pose does not exist in the database: ["+name+"]")
            return False
        
        #confirm 'type' is given
        ap_type = selected_pose['option'].get('type', 'False')
        if ap_type == 'False':
            self.get_logger().warn("the action primitive does not have a type: " + name)
        
        
        #if selected_pose['option']['type'] == 'compound':
        if ap_type == 'compound':
            self.get_logger().info("compound action primitive")
            simple_poses = [f'{i}' for i in selected_pose['option']['simple_poses']]
            hold_time = float(selected_pose['option']['hold_time'])
            
            for ap in simple_poses:
                if self.stop_event.is_set():
                    self.get_logger().info("compound action primitive stopped")
                    break
                self.get_logger().info("gesture: " + ap)
                self.set_pose(ap)
                self.stop_event.wait(hold_time)
            self.get_logger().info("compound action primitive finished")
            return selected_pose
            
        msg_head = JointState()
        msg_body = JointState()
        msg_Rarm = JointState()
        msg_Larm = JointState()
        
        msg_head.name = [self.robot_name+"_neck_yaw_joint", self.robot_name+"_neck_pitch_joint"]
        msg_body.name = [self.robot_name+"_body_pitch_joint"]
        
        try:
            head_position_converted = [float(i) for i in selected_pose['option']['head']]
            body_position_converted = [float(i) for i in selected_pose['option']['body']]
            rightArm_position_converted = [float(i) for i in selected_pose['option']['rightArm']]
            leftArm_position_converted = [float(i) for i in selected_pose['option']['leftArm']]
        except KeyError:
            self.get_logger().error("one or more of the following keys were not found in the pose definition: [head],[body],[rightArm],[leftArm]")
            return False
        
        msg_head.position = head_position_converted
        msg_body.position = body_position_converted
        msg_Rarm.position = rightArm_position_converted
        msg_Larm.position = leftArm_position_converted
        
        self.publisherHead.publish(msg_head)
        self.publisherBody.publish(msg_body)
        self.publisherRarm.publish(msg_Rarm)
        self.publisherLarm.publish(msg_Larm)
        return selected_pose
    
    #
    def action_ctl_pub(self, text, ts):
        # stopで中断された場合はFalseを返す
        msg = String()
        msg.data = text
        self.mpub.publish(msg)
        
        data = json.loads(text)
        name = data['gesture']
        self.get_logger().info("  gesture: " + name + " duration: " +str(ts))
        self.set_pose(name)
        stopped = self.stop_event.wait(ts)
        self.set_pose('look_front')
        self.get_logger().info("  gesture: look_front")
        if stopped:
            return False
        time.sleep(2)
        return True
    
    #
    def set_pose_free_callback(self, data):
        msg:JointState = data
        self.get_logger().info('free pose msg received')
        
        match msg.name:
            case ['head']:
                msg.name = [self.robot_name+"_neck_yaw_joint", self.robot_name+"_neck_pitch_joint"]
                self.publisherHead.publish(msg)
                self.get_logger().debug('publish head joints: ' + str(msg.position))
        
            case ['body']:
                msg.name = [self.robot_name+"_body_pitch_joint"]
                self.publisherBody.publish(msg)
                self.get_logger().debug('publish body joints: ' + str(msg.position))
            
            case ['rightArm']:
                #self.publisherRarm.publish(msg)
                self.get_logger().info('publish right arm joints TO-DO')
                
            case ['leftArm']:
                #self.publisherLarm.publish(msg)
                self.get_logger().info('publish left arm joints TO-DO')
                
            case _:
                self.get_logger().warn('joint name missing in msg: ' + str(data))
                pass
        
    #
    def cancel_current_mode_playing(self):
        self.get_logger().info("Cancelling current mode [" + str(self.mode_id_playing.get('name')) + "] id is_playing: " + str(self.mode_id_playing.get('_id')))
        if self.mode_id_playing.get('_id') != 'None':
            self.mng.set_status(self.mode_id_playing.get('_id'), 'done')
            self.mode_id_playing = {'_id': 'None', 'name':'None'}
        #else:
        #    self.get_logger().info('No _id mode was registered to be playing')
    #
    def validate_gesture(self, gesture) -> str | None:
        # Actions文書の書き方を調べる。不正なら理由を、正しければNoneを返す
        if not isinstance(gesture, dict):
            return "document is not a dict"
        option = gesture.get('option')
        if not isinstance(option, dict):
            return "option is not a dict"
        gesture_type = option.get('type')
        if not isinstance(gesture_type, str):
            return "option.type is not a string"
        key = 'command' if 'mode' in gesture_type else 'gesture'
        value = option.get(key)
        if not isinstance(value, str) or not value:
            return "option." + key + " is not a non-empty string"
        for key in ('offset', 'duration'):
            if key in option and (isinstance(option[key], bool) or not isinstance(option[key], (int, float))):
                return "option." + key + " is not a number"
        return None
    #
    def timer_callback(self):
        # 例外でノードが落ちるとlaunch全体(on_exit=Shutdown)が終了するので、ここで全て捕まえる
        self.gesture = False
        try:
            self.process_next_gesture()
        except Exception:
            self.get_logger().error("failed to process gesture:\n" + traceback.format_exc())
            if isinstance(self.gesture, dict) and '_id' in self.gesture:
                try:
                    self.mng.set_status(self.gesture['_id'], 'stopped')
                except Exception:
                    self.get_logger().error("failed to set status 'stopped':\n" + traceback.format_exc())
    #
    def process_next_gesture(self):
        
        #get_next action from MongoDB
        self.gesture=self.mng.get_next()
        if self.gesture != False:
            #不正な文書はstoppedにして読み飛ばす（waitingのままだとget_next()が毎周期同じ文書を返す）
            error = self.validate_gesture(self.gesture)
            if error is not None:
                self.get_logger().error("invalid gesture document (" + error + "): _id=" + str(self.gesture.get('_id')) + " option=" + str(self.gesture.get('option')))
                self.mng.set_status(self.gesture['_id'], 'stopped')
                return
            #
            if 'mode' in self.gesture['option']['type']:
                self.mng.set_status(self.gesture['_id'],'is_playing')   
                self.get_logger().info("Gesture mode received: " + self.gesture['option']['command'])
          
                #available modes: [default, listen, tracking, stop]
                #send entire data to modes description node 
                data={}
                data['gesture']=self.gesture
                msg = String()
                msg.data = json.dumps(data, default=str)
                self.modespub.publish(msg) #send to modes description
                self.mpub.publish(msg) #send to debugger
                time.sleep(2)
                
                #a mode is playing, cancel it, and activate the new request in mongoDB
                #even if it is the same mode
                self.cancel_current_mode_playing()
                    
                if self.gesture['option']['command'] == 'stop':  #type: 'mode', command: 'stop'
                    self.get_logger().info("set _id of mode: 'stop' request to 'done'")
                    self.mng.set_status(self.gesture['_id'], 'done')
                
                else:
                    self.mode_id_playing['_id'] = self.gesture['_id']
                    self.mode_id_playing['name'] = self.gesture['option']['command']
                
                
            else:
                if self.mode_id_playing.get('name') == 'tracking':
                    #tracking mode uses the set_pose_free_callback and needs to be stopped before allowing another action to be executed
                    #if its running properly just wait for mode to finish tracking
                    return
                    ##id_status_mongoDB = self.mng.get_status(self.mode_id_playing.get('_id'))
                    ##if id_status_mongoDB == 'is_playing':
                    ##    return
                    ##elif self.mode_name_playing_server != 'tracking':
                        #update mode
                    ##    self.mode_id_playing = {'_id': 'None', 'name':'None'}
                        
                
                self.stop_event.clear()  # 新しいジェスチャの開始で停止状態を解除する
                self.mng.set_status(self.gesture['_id'],'is_playing')   
                self.get_logger().info('A gesture received')
                data={}    
                data['gesture'] = self.gesture['option']['gesture']
                if 'offset' in self.gesture['option'].keys():
                    offset=self.gesture['option']['offset']
                    self.get_logger().info("  offset: " + str(offset) +" seconds")
                    if self.stop_event.wait(offset):
                        self.mng.set_status(self.gesture['_id'],'stopped')
                        self.get_logger().info("  stopped: " + data['gesture'])
                        return
                ts=5.0
                if 'duration' in self.gesture['option'].keys():
                    ts=self.gesture['option']['duration']
                if self.action_ctl_pub(json.dumps(data), ts):
                    self.mng.set_status(self.gesture['_id'],'done')
                    self.get_logger().info("  executed: " + data['gesture'] + " " + str(ts) +" seconds")
                else:
                    self.mng.set_status(self.gesture['_id'],'stopped')
                    self.get_logger().info("  stopped: " + data['gesture'])
            
    #
    def active_gesture_mode_callback(self, msg):
        updated_mode_name_playing_server = msg.data
        
        if self.mode_name_playing_server == updated_mode_name_playing_server:
            return
        
        else: #mode has changed from server
            if updated_mode_name_playing_server == self.mode_id_playing.get('name'): #confirm the updated_mode is same as current mode id_playing
                self.mode_name_playing_server = updated_mode_name_playing_server #update name of mode 
                return
            
            else: #mode from server is different from mode playing registered
                self.get_logger().info('synchronizing mode status')
                id_status_mongoDB = 'unknown'
                if self.mode_id_playing.get('_id') != 'None':
                    id_status_mongoDB = self.mng.get_status(self.mode_id_playing.get('_id'))                 
                
                if id_status_mongoDB == 'done' and updated_mode_name_playing_server == 'None':
                    self.mode_id_playing = {'_id': 'None', 'name':'None'}
                
                if id_status_mongoDB == 'is_playing':
                    self.cancel_current_mode_playing()
                    
                if 'unknown' in id_status_mongoDB:
                    #send stop all modes.
                    data={'gesture': {}}
                    data['gesture']['option'] = {"type": "mode", "command": "stop", "gesture": "stop", "duration": 1}
                    msg = String()
                    msg.data = json.dumps(data, default=str)
                    self.modespub.publish(msg) #send to modes description
                    self.mode_id_playing = {'_id': 'None', 'name':'None'}
                    
                self.mode_name_playing_server = 'None'
            
        
    def msg_callback(self, msg):
        if msg.data == 'stop':
            self.get_logger().warn("stop: interrupt the current gesture.")
            self.stop_event.set()
            msg = String()
            msg.data = self.robot_name + ": gesture node was stopped."
            self.mpub.publish(msg)

def main():
    rclpy.init()
    robot_name = os.getenv("ROBOT_NAME")
    node = polling_gesture_modes_node(robot_name)
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    
    try: 
        executor.spin()
    except KeyboardInterrupt as err:
        #logging.getLogger().error(err)
        print("Exit: Ctrl + C")
    
    executor.shutdown()
    node.destroy_node()
        
if __name__ == '__main__':
    main()
