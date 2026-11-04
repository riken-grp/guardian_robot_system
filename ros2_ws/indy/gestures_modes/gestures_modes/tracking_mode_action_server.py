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
from sensor_msgs.msg import RegionOfInterest
from geometry_msgs.msg import Point
from gestures_modes_interfaces.action import TrackingMode # type: ignore
from recognition_msgs.msg import Persons, Person #type: ignore
import std_msgs.msg
import threading
from sensor_msgs.msg import JointState, CameraInfo
from common_msgs.msg import StringStamped #type: ignore
import json
from pyindy.param_manager import ParamManager

class polling_tracking_mode_action_server(Node):
    def __init__(self, robot_name='none'):
        self.mode = 'tracking'
        super().__init__(self.mode+"_mode_action_server")
        self.get_logger().info('start '+ self.get_name() +' for: ' + robot_name)
        self.robot_name = robot_name
        #
        self.declare_parameter("mongo_port", 0)
        self.mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        self.declare_parameter("mongo_uri", "")
        self.mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        #
        #モーター関連のパラメータはMongoDB(robot_config.system_parameters)のgestures_modesから取得する
        motor_params = self.get_motor_params()
        #
        self.topic_control_joints = motor_params.get("topic_control_joints", "")
        self.get_logger().info("topic_control_joints: " + self.topic_control_joints)
        if not self.topic_control_joints:
            self.get_logger().error("topic_control_joints is not set in MongoDB gestures_modes params")
        #
        self.head_joint_limit_up = float(motor_params.get("head_joint_limit_up", 0.0))
        self.head_joint_limit_down = float(motor_params.get("head_joint_limit_down", 0.0))
        self.head_joint_limit_right = float(motor_params.get("head_joint_limit_right", 0.0))
        self.head_joint_limit_left = float(motor_params.get("head_joint_limit_left", 0.0))
        #
        self.get_logger().info("head_joint_limits [up, down, right, left]: [" + str(self.head_joint_limit_up) + ", " + str(self.head_joint_limit_down) + ", " + str(self.head_joint_limit_right)+", "+ str(self.head_joint_limit_left)+"]")
                
        self._action_server = ActionServer(self, TrackingMode,'robot/gesture_mode/tracking_mode',
                                           execute_callback=self.execute_callback, 
                                           callback_group=ReentrantCallbackGroup(),
                                           goal_callback=self.goal_callback,
                                           cancel_callback=self.cancel_callback,
                                           handle_accepted_callback=self.handle_accepted_callback)
        self._goal_handle = None
        self._goal_lock = threading.Lock()
        #
        self.active = False
        self.timer_period = 0.25
        self.timer = self.create_timer(self.timer_period,self.publish,callback_group=ReentrantCallbackGroup())
        self.pubGesture = self.create_publisher(String, 'robot/action_ctl', 10, callback_group=MutuallyExclusiveCallbackGroup())
        self.timer_status = 0.1
        self.pubStatus = self.create_timer(self.timer_status, self.publish_status, callback_group=ReentrantCallbackGroup())
        self.pubIsActive = self.create_publisher(Bool, 'robot/gesture_mode/tracking_mode/is_active', 10)
        
        self.action_key: int = 1
        self.timer_done = False
        #ros2 topic info /indy1/recog/person/face
        #    Type: recognition_msgs/msg/Persons
        #    Publisher count: 1
        #    Subscription count: 2
        #ros2 interface show recognition_msgs/msg/Persons
        #Person[] persons
        #         float32[] face_location
        
        #in case the target is sent as RegionOfInterest
        #self.target_sub = self.create_subscription(RegionOfInterest, 'tracking/target_roi', self.target_roi_callback, 10, callback_group=ReentrantCallbackGroup())
        
        #using recognition_msgs/msgs/Persons
        #self.target_sub = self.create_subscription(Persons, 'recog/person/face', self.target_persons_callback, 10, callback_group=ReentrantCallbackGroup())
        #
        
        #using recog/robot_looking_target  （センサ相対座標のxyz: xは右，yは下，zは奥行き）
        #{
        #"instance_id": 1,
        #"type": "person",
        #"class_id": 0,
        #"name": "person",
        #"location": [1.2, -0.1, 4.5]
        #}
        self.target_sub = self.create_subscription(StringStamped, 'recog/robot_looking_target', self.robot_looking_target_callback, 10, callback_group=ReentrantCallbackGroup())
        
        self.target = None
        self.max_duration = None
        self.temp_timer = None
        self.center_camera_image = Point() #[w: 1280 | h: 720] 
        self.camera_info_set = False
        self.target_reached = False
        self.action_id = None
        
        #    
        self.pubHeadJoints = self.create_publisher(JointState, "robot/free_pose", 10, callback_group=ReentrantCallbackGroup())
        #self.subCameraInfo = self.create_subscription(CameraInfo, 'indy1_camera/color/camera_info', self.camera_info_callback, 10, callback_group=ReentrantCallbackGroup())
        self.subJointStates = self.create_subscription(JointState, self.topic_control_joints, self.joint_states_callback, 10, callback_group=ReentrantCallbackGroup()) 
        
        #updated in joint_states_callback
        self.jointNeckYaw = 0.0 #x
        self.jointNeckPitch = 0.0 #y
        
        #tracking sequence
        #a person is detected -> head follows the person for n seconds.
        #'look_front'
        self.sequence_action = {1:'tracking', 2:'look_front'}
        
    #timer publishers  
    def publish(self):
        msg = String()
        msg.data = 'Separate publisher #' + str(self.action_key)

        # Print the current status for demo purposes
        if not self.active:
            #self.get_logger().info('Publisher is inactive. Messages are not published.')
            self.target_reached = False
            self.action_key = 1
            self.timer_done = False        
            
        else:
            self.get_logger().info(f"Node '{self.get_name()}' is active.")            
            seq_act = self.sequence_action.get(self.action_key)
            
            if  seq_act == 'tracking':
                self.get_logger().info('tracking person')
                if not self.temp_timer and not self.timer_done:
                    self.get_logger().info('new timer: ' + str(self.max_duration))
                    self.temp_timer = self.create_timer(self.max_duration, self.time_out_max_duration, callback_group=ReentrantCallbackGroup())
                
                if self.temp_timer.is_canceled() and not self.timer_done:
                    self.get_logger().info('overwrite timer')
                    self.temp_timer = self.create_timer(self.max_duration, self.time_out_max_duration, callback_group=ReentrantCallbackGroup())
                    
                if not self.timer_done:
                    self.publish_tracking_coordinates()    
                else:
                    self.action_key = 2
                    self.cancel_current_timer()
                    self.get_logger().info('timeout while tracking; target reached: ' + str(self.target_reached))
                    
            seq_act = self.sequence_action.get(self.action_key)    
            if seq_act == 'look_front':
                script_option = {"type": "normal", "command": str(seq_act), "gesture": str(seq_act), "duration": 2}
                self.get_logger().info("go to look_front position")
                #self.acmng.insert(gesture=script_option) 
                self.sendFeedbackmsg('insert gesture',script_option)

            if self.timer_done:
                self.get_logger().info('timeout sequence finished; target reached: ' + str(self.target_reached))
                self.active = False
                self.action_key = 1
                self.cancel_current_timer()
        
    def sendFeedbackmsg(self,feedback_msg, data_msg):
        fb_msg = TrackingMode.Feedback()
        fb_msg.feedback = feedback_msg
        fb_msg.data_msg = json.dumps(data_msg, default=str)
        self._goal_handle.publish_feedback(fb_msg)
    #        
    def publish_tracking_coordinates(self):
        
        if self.target:
            #self.get_logger().info('Publishing tracking coordinates')
            new_jointNeckYaw = 0.0
            new_jointNeckPitch = 0.0
            yaw_reached = False
            pitch_reached =  False
            self.target_reached = False
            add_up = self.head_joint_limit_up / 5
            add_down = self.head_joint_limit_down / 5
            add_right = self.head_joint_limit_right / 10
            add_left = self.head_joint_limit_left / 10
            
            #if not self.camera_info_set:
            #    self.get_logger().warn('missing camera info')
            #    self.camera_info_default()
                
            
            #compare self.target [x,y] with self.center_camera_image [x,y]
            #difference_x = self.center_camera_image.x - self.target.x # negative = target is on the right, positive = target is on the left
            #difference_y = self.target.y - self.center_camera_image.y # negative = target is up, positive = target is down
            
            #（センサ相対座標のxyz: xは右，yは下，zは奥行き）[1.2, -0.1, 4.5]
            difference_x = self.target.x
            difference_y = self.target.y
            
            #YAW right and left
            if difference_x > 0.0:
                new_jointNeckYaw = self.jointNeckYaw + add_right
                if abs(new_jointNeckYaw) > abs(self.head_joint_limit_right):
                    new_jointNeckYaw = self.head_joint_limit_right
                self.get_logger().info('    looking more [RIGHT]: ' + str(new_jointNeckYaw))
                
            elif difference_x < 0.0:
                new_jointNeckYaw = self.jointNeckYaw + add_left
                if abs(new_jointNeckYaw) > abs(self.head_joint_limit_left):
                    new_jointNeckYaw = self.head_joint_limit_left
                self.get_logger().info('    looking more [LEFT]: ' + str(new_jointNeckYaw))
                
            else: 
                new_jointNeckYaw = self.jointNeckYaw
                yaw_reached = True
                self.get_logger().info('target is in the middle [yaw]')
                
            #PITCH up and down
            if difference_y < 0.0:
                new_jointNeckPitch = self.jointNeckPitch + add_up
                if abs(new_jointNeckPitch) > abs(self.head_joint_limit_up):
                    new_jointNeckPitch = self.head_joint_limit_up
                self.get_logger().info('    looking more [UP]: ' + str(new_jointNeckPitch))
                
            elif difference_y > 0.0:
                new_jointNeckPitch = self.jointNeckPitch + add_down
                if abs(new_jointNeckPitch) > abs(self.head_joint_limit_down):
                    new_jointNeckPitch = self.head_joint_limit_down
                self.get_logger().info('    looking more [DOWN]: ' + str(new_jointNeckPitch))
                
            else: 
                new_jointNeckPitch = self.jointNeckPitch
                pitch_reached = True
                self.get_logger().info('target is in the middle [pitch]')
                
            #
            if yaw_reached and pitch_reached:
                self.get_logger().info('target reached')
                self.target_reached = True
            
            msg_joints = JointState()    
            msg_joints.name = ['head']
            msg_joints.position = [new_jointNeckYaw, new_jointNeckPitch] 
            self.pubHeadJoints.publish(msg_joints)  
            #self.get_logger().info('publish joints neck: ' + str(msg_joints.position))
        
        else:
            self.get_logger().info("target not seen")            
    #
            
    def cancel_current_timer(self):
        self.get_logger().info('cancel timer')
        if self.temp_timer and not self.temp_timer.is_canceled():
            self.temp_timer.cancel()
            time.sleep(2)
            self.get_logger().info('timer cancelled: ' + str(self.temp_timer.is_canceled()))
        else:
            self.get_logger().info('timer is not active')
        
    def time_out_max_duration(self):
        self.get_logger().info('timer finished')
        self.timer_done = True
        self.action_key = 2 
        self.cancel_current_timer()
        
    #
    def joint_states_callback(self, data):
        current_jointStates: JointState = data
        #self.get_logger().info('current joint states: ' + str(current_jointStates))
        #the JointState msg includes:
        #name: indy1_neck_yaw_joint, indy1_neck_pitch_joint, indy1_body_pitch_joint
        
        j_names = current_jointStates.name
        
        for i in range(len(j_names)):
            if j_names[i] == self.robot_name + '_neck_yaw_joint':      
                self.jointNeckYaw = current_jointStates.position[i] 
                
            if j_names[i] == self.robot_name + '_neck_pitch_joint':
                self.jointNeckPitch = current_jointStates.position[i] 
        
        #self.get_logger().info('yaw and pitch: [' + str(self.jointNeckYaw) + ", " + str(self.jointNeckPitch) + ']')
        
    #
    def camera_info_callback(self, data):
        if not self.camera_info_set:
            self.get_logger().info('camera info set')
            temp_data: CameraInfo = data
            self.center_camera_image.x = temp_data.width / 2
            self.center_camera_image.y = temp_data.height /2
            self.camera_info_set = True
    
    def camera_info_default(self):
        self.get_logger().info('camera info default')
        self.center_camera_image.x = 1280 / 2
        self.center_camera_image.y = 720 / 2
    
    #
    def robot_looking_target_callback(self, data):
        jdata = json.loads(data.data)
        location = jdata['location']
        location_converted = [float(i) for i in location]
        
        t_point = Point()
        t_point.x = location_converted[0]
        t_point.y = location_converted[1]
        t_point.z = location_converted[2] #we do not use this
        
        self.target = t_point     
        
    #
    def target_roi_callback(self, data):
        #self.get_logger().info('target received') #delete this line
        roi_target: RegionOfInterest = data
        t_x_offset = roi_target.x_offset
        t_y_offset = roi_target.y_offset
        height_roi = roi_target.height
        width_roi = roi_target.width
        
        #calculate the target center point [x,y]
        c_height = height_roi / 2
        c_width = width_roi / 2
        t_x = t_x_offset + c_width
        t_y = t_y_offset + c_height       
        
        t_point = Point()
        t_point.x = t_x
        t_point.y = t_y
        t_point.z = 0.0
        
        self.target = t_point
        
    def publish_status(self):
        msg = std_msgs.msg.Bool()
        msg.data = self.active
        self.pubIsActive.publish(msg)
    
    def target_persons_callback(self, data):
        #self.get_logger().info('target received') 
        target_persons: Persons = data
        if not data.persons:
            return
        
        target_person: Person = data.persons[0] #TO-DO select one dynamically
        # image coordinate [x, y, w, h]
        face_location = target_person.face_location 
        t_x_face = face_location[0]
        t_y_face = face_location[1]
        width_face = face_location[2]
        height_face = face_location[3]
        
        #calculate the target center point [x,y]
        c_height = height_face / 2
        c_width = width_face / 2
        t_x = t_x_face + c_width
        t_y = t_y_face + c_height       
        
        t_point = Point()
        t_point.x = t_x
        t_point.y = t_y
        t_point.z = 0.0
        
        self.target = t_point
        
        
    ##Action server
    async def execute_callback(self, goal_handle):
        self.get_logger().info('Executing goal...')
        feedback_msg = TrackingMode.Feedback()
        result = TrackingMode.Result()
        result.succeeded = True
        result.action_id = goal_handle.request.action_id
        #
        self.active = goal_handle.request.activate
        self.action_key = 1
        self.max_duration = goal_handle.request.max_duration
        self.action_id = goal_handle.request.action_id
                
        while self.active:    
            feedback_msg.feedback = 'tracking target available: ' + str(self.target)
            goal_handle.publish_feedback(feedback_msg)
                
            if not goal_handle.is_active:
                # 新しいゴールに置き換えられた場合、新しいゴールのactiveを落とさない
                if self._goal_handle is goal_handle:
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
            if self._goal_handle is goal_handle:
                self.active = False
            result.succeeded = False
            self.get_logger().info('Goal aborted')
            return result
        
        goal_handle.succeed()
        self.get_logger().info('Returning result completed: {0}'.format(result.succeeded))
        self.active = False
        return result
    
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
    
    def goal_callback(self, goal_request):
        self.get_logger().info('Received goal request')
        return GoalResponse.ACCEPT
    
    def handle_accepted_callback(self, goal_handle):
        self.get_logger().info('Goal handler')
        
        with self._goal_lock:
            if self._goal_handle is not None and self._goal_handle.is_active:
                # EXECUTING状態のゴールはcanceled()に遷移できない（例外になる）ため、abort()で終了させる
                # 実行中ループがsucceed()に進まないよう、activeを落とす前にabortする
                self.get_logger().info('Abort previous goal')
                self._goal_handle.abort()
                self.active = False
                self.cancel_current_timer()
                self.get_logger().info('previous goal is active: ' + str(self._goal_handle.is_active))
            self.get_logger().info('Set global goal handle')    
            self._goal_handle = goal_handle
        
        if goal_handle.request.activate == False:
            self.get_logger().info('request deactivate')
            self.active = goal_handle.request.activate
            self.cancel_current_timer()
            self.get_logger().info('handler is active: ' + str(self._goal_handle.is_active))
            
        goal_handle.execute()          
    
    #useful doc in cpp: https://github.com/ros/ros_tutorials/blob/foxy-devel/turtlesim/src/turtle.cpp
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
        node = polling_tracking_mode_action_server(robot_name)
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        time.sleep(1)
        
        try:
            executor.spin()
        
        except KeyboardInterrupt as err:
            executor.shutdown()
            node.destroy_node()
            
    except Exception as err:
        logging.getLogger().error(err)

if __name__ == '__main__':
    main()