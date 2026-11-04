import numpy as np
import math
import socket
import threading
import collections

import rclpy
from rclpy.time import Duration
from rclpy import qos
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from sensor_msgs.msg import LaserScan
from visualization_msgs.msg import Marker, MarkerArray
from human_tracker_msgs.msg import TrackedPersons, TrackedPerson
from recognition_msgs.msg import Persons
from human_tracker_msgs.msg import AudioInfoList
from human_tracker_msgs.msg import PersonAllInfo, PersonAllInfoList

from pyindy.param_manager import ParamManager
from .tf_transfomer import TFTransformer
from .track_info import (DEFAULT_AUDIO_PORT, INVALID_VALUE, MarkerColor, ObjectPoint, PersonRecogInfo, QueuedObject,
                         TrackInfo, ViewText, build_tcp_record, parse_view_text)

class HumanTracker(Node):

    def __init__(self):
        super().__init__('human_tracker_node')

        name_space = self.get_namespace()
        name_space = name_space.replace("/", "")

        self.declare_parameter('scan_topic_name', '/scan')
        self.declare_parameter('scan_topic_rate', 0.1)
        self.declare_parameter('seperate_acceptable_angle', 5.0)
        self.declare_parameter('seperate_distance', 0.05)
        self.declare_parameter('camera_link', "camera_link")
        self.declare_parameter('robot_link', "robot_link")
        self.declare_parameter('lidar_link', "lidar_link")
        self.declare_parameter('max_recog_range', 5.0)
        self.declare_parameter('upper_recog_angle', 360.0)
        self.declare_parameter('lower_recog_angle', 0.0)
        self.declare_parameter('camera_integration', True)
        self.declare_parameter('camera_associated_topic', "/recog/person/associated")
        self.declare_parameter('camera_topic_hold_time', 10.0)
        self.declare_parameter('camera_obj_distance', 0.3)
        self.declare_parameter('camera_max_fov', 35.0)
        self.declare_parameter('camera_min_fov', -35.0)
        self.declare_parameter('camera_max_range', 5.0)
        self.declare_parameter('max_pixel_height', 100)
        self.declare_parameter('outrange_hold_time', -1.0)
        self.declare_parameter('outrange_hold_range', -1.0)
        self.declare_parameter('fusion_side_arm', False)
        self.declare_parameter('arm_range', 0.3)
        self.declare_parameter('min_object_size', 0.2)
        self.declare_parameter('max_object_size', 0.7)
        self.declare_parameter('too_close_range', 0.2)
        self.declare_parameter('object_queue_size', 10)
        self.declare_parameter('check_linearity', False)
        self.declare_parameter('linearity_limit', 1.0)
        self.declare_parameter('check_rightangle', False)
        self.declare_parameter('min_rightangle_limit', 85.0)
        self.declare_parameter('max_rightangle_limit', 95.0)
        self.declare_parameter('check_dent', False)
        self.declare_parameter('dent_limit', 0.3)
        self.declare_parameter('priority_range', 2.0)
        self.declare_parameter('priority_min_angle', -60.0)
        self.declare_parameter('priority_max_angle', 60.0)
        self.declare_parameter('sep_hold_time', 5.0)
        self.declare_parameter('range_weight', 1.0)
        self.declare_parameter('angle_weight', 1.0)
        self.declare_parameter('face_direction_weight', 1.0)
        self.declare_parameter('prority_sep_num', 2)
        self.declare_parameter('max_sep_id', 7)
        self.declare_parameter('trace_range', 0.2)
        self.declare_parameter('trace_count', 20)
        self.declare_parameter('human_trace_rate', 0.8)
        self.declare_parameter('max_trace_rate', 0.6)
        self.declare_parameter('min_trace_rate', 0.2)
        self.declare_parameter('human_hold_time', 3.0)
        self.declare_parameter('human_center', 0.15)
        self.declare_parameter('client_number', 10)
        self.declare_parameter('rviz_fixed_frame', "")
        self.declare_parameter('rviz_view_text', "")
        self.declare_parameter('multi_lidar', False)

        scan_topic_name = self.get_parameter('scan_topic_name').get_parameter_value().string_value
        self.scan_topic_rate = self.get_parameter('scan_topic_rate').get_parameter_value().double_value
        self.acceptable_angle = self.get_parameter('seperate_acceptable_angle').get_parameter_value().double_value
        self.seperate_distance = self.get_parameter('seperate_distance').get_parameter_value().double_value
        camera_link = self.get_parameter('camera_link').get_parameter_value().string_value
        self.camera_link = name_space + "_" + camera_link
        robot_link = self.get_parameter('robot_link').get_parameter_value().string_value
        self.robot_link = name_space + "_" + robot_link
        lidar_link = self.get_parameter('lidar_link').get_parameter_value().string_value
        self.lidar_link = name_space + "_" + lidar_link
        self.max_recog_range = self.get_parameter('max_recog_range').get_parameter_value().double_value
        upper_recog_angle_deg = self.get_parameter('upper_recog_angle').get_parameter_value().double_value
        lower_recog_angle_deg = self.get_parameter('lower_recog_angle').get_parameter_value().double_value
        self.camera_integration = self.get_parameter('camera_integration').get_parameter_value().bool_value
        camera_associated_topic = self.get_parameter('camera_associated_topic').get_parameter_value().string_value
        self.camera_topic_hold_time = self.get_parameter('camera_topic_hold_time').get_parameter_value().double_value
        self.camera_obj_distance = self.get_parameter('camera_obj_distance').get_parameter_value().double_value
        camera_max_fov_deg = self.get_parameter('camera_max_fov').get_parameter_value().double_value
        camera_min_fov_deg = self.get_parameter('camera_min_fov').get_parameter_value().double_value
        self.outrange_hold_time = self.get_parameter('outrange_hold_time').get_parameter_value().double_value
        self.outrange_hold_range = self.get_parameter('outrange_hold_range').get_parameter_value().double_value
        self.camera_max_range = self.get_parameter('camera_max_range').get_parameter_value().double_value
        self.max_pixel_height = self.get_parameter('max_pixel_height').get_parameter_value().integer_value
        self.fusion_side_arm_flg  = self.get_parameter('fusion_side_arm').get_parameter_value().bool_value
        self.arm_range = self.get_parameter('arm_range').get_parameter_value().double_value
        self.min_object_size = self.get_parameter('min_object_size').get_parameter_value().double_value
        self.max_object_size = self.get_parameter('max_object_size').get_parameter_value().double_value
        self.too_close_range = self.get_parameter('too_close_range').get_parameter_value().double_value
        self.object_queue_size= self.get_parameter('object_queue_size').get_parameter_value().integer_value
        self.check_linearity_flg = self.get_parameter('check_linearity').get_parameter_value().bool_value
        self.linearity_limit = self.get_parameter('linearity_limit').get_parameter_value().double_value
        self.check_rightangle_flg = self.get_parameter('check_rightangle').get_parameter_value().bool_value
        self.min_rightangle_limit = self.get_parameter('min_rightangle_limit').get_parameter_value().double_value
        self.max_rightangle_limit = self.get_parameter('max_rightangle_limit').get_parameter_value().double_value
        self.check_dent_flg = self.get_parameter('check_dent').get_parameter_value().bool_value
        self.dent_limit = self.get_parameter('dent_limit').get_parameter_value().double_value
        self.priority_range = self.get_parameter('priority_range').get_parameter_value().double_value
        priority_min_deg = self.get_parameter('priority_min_angle').get_parameter_value().double_value
        priority_max_deg = self.get_parameter('priority_max_angle').get_parameter_value().double_value
        self.sep_hold_time = self.get_parameter('sep_hold_time').get_parameter_value().double_value
        self.range_weight = self.get_parameter('range_weight').get_parameter_value().double_value
        self.angle_weight = self.get_parameter('angle_weight').get_parameter_value().double_value
        self.face_dir_weight = self.get_parameter('face_direction_weight').get_parameter_value().double_value
        self.prority_sep_num = self.get_parameter('prority_sep_num').get_parameter_value().integer_value
        self.max_sep_id = self.get_parameter('max_sep_id').get_parameter_value().integer_value
        self.trace_range = self.get_parameter('trace_range').get_parameter_value().double_value
        self.trace_count = self.get_parameter('trace_count').get_parameter_value().integer_value
        self.human_trace_rate = self.get_parameter('human_trace_rate').get_parameter_value().double_value
        self.max_trace_rate = self.get_parameter('max_trace_rate').get_parameter_value().double_value
        self.min_trace_rate = self.get_parameter('min_trace_rate').get_parameter_value().double_value
        self.human_hold_time = self.get_parameter('human_hold_time').get_parameter_value().double_value
        self.human_center = self.get_parameter('human_center').get_parameter_value().double_value
        self.client_number = self.get_parameter('client_number').get_parameter_value().integer_value
        rviz_fixed_frame = self.get_parameter('rviz_fixed_frame').get_parameter_value().string_value
        self.rviz_fixed_frame = name_space + "_" + rviz_fixed_frame
        self.rviz_view_text = self.get_parameter('rviz_view_text').get_parameter_value().string_value
        self.multi_lidar = self.get_parameter('multi_lidar').get_parameter_value().bool_value

        self.declare_parameter("mongo_uri", "")
        mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.declare_parameter("mongo_port", 0)
        mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        pm = ParamManager(mongo_uri, mongo_port)
        params = pm.get_param("human_tracker")
        self.tcp_server_port = DEFAULT_AUDIO_PORT
        if params is not None:
            if "audio_port" in params:
                self.tcp_server_port = params["audio_port"]
        else:
            self.get_logger().warn(f"Failed to get parameters from MongoDB (uri:{mongo_uri}, port:{mongo_port}).")

        self.rviz_view_text = parse_view_text(self.rviz_view_text, self.get_logger())

        if not self.multi_lidar:
            self.client_list = []
            thread_accept_tcp = threading.Thread(target=self.accept_tcp)
            thread_accept_tcp.setDaemon(True)
            thread_accept_tcp.start()

        self.id_len = 0

        # human_id -> TrackInfo
        self.info_id_list = []
        self.info_list = {}

        self.marker_array = MarkerArray()
        self.marker_id_list = []
        self.last_human_id = []

        # カメラ認識ID(instance_id) -> PersonRecogInfo
        self.person_recog_id_list = []
        self.person_recog_info = {}

        self.last_person_topic_time = 0.0

        self.camera_max_fov = camera_max_fov_deg * np.pi / 180.0
        self.camera_min_fov = camera_min_fov_deg * np.pi / 180.0
        self.actual_max_fov = 0.0
        self.actual_min_fov = 0.0

        self.upper_recog_angle = upper_recog_angle_deg * np.pi / 180.0
        self.lower_recog_angle = lower_recog_angle_deg * np.pi / 180.0

        if self.outrange_hold_time < 0.0:
            self.outrange_hold_time = np.inf
        if self.outrange_hold_range < 0.0:
            self.outrange_hold_range = np.inf

        self.audio_on_flg = {}
        self.current_audio_info = {}
        self.audio_change_flg = {}
        self.audio_on_cnt = 0
        self.current_audio_id = []
        self.last_id = []

        self.object_queue = {}

        self.priority_min_angle = priority_min_deg * np.pi / 180.0
        self.priority_max_angle = priority_max_deg * np.pi / 180.0

        self.too_close_range *= 1000.0

        self.transformer = TFTransformer(self)

        node_name = self.get_name()
        if node_name[-5:] == "_node":
            node_name = node_name[:-5]
        
        scan_qos = qos.QoSProfile(depth=10)
        scan_qos.reliability = qos.QoSReliabilityPolicy.BEST_EFFORT 

        self.marker_pub = self.create_publisher(MarkerArray, node_name + "/human_pose_marker", 10)
        if self.multi_lidar:
            self.person_all_info_pub = self.create_publisher(PersonAllInfoList, node_name + "/person_all_info", 10)
        else:
            self.human_tracker_result_pub = self.create_publisher(TrackedPersons, "human_tracker/recognition_result", 10)
            self.audio_info_sub = self.create_subscription(AudioInfoList, "human_tracker/audio_info", self.audio_info_cb, 10)

        self.scan_sub = self.create_subscription(LaserScan, scan_topic_name, self.scan_cb, scan_qos)
        if self.camera_integration:
            self.person_associated_sub = self.create_subscription(Persons, camera_associated_topic, self.person_associated_cb, 10)

    def scan_cb(self, image):
        self.get_logger().debug('Receive scan topic')

        scan_time = image.header.stamp.sec + image.header.stamp.nanosec * 1e-9
        raw_data = np.array(image.ranges)
        recog_range = min(image.range_max, self.max_recog_range)
        raw_data = np.where((raw_data < image.range_min) | (raw_data > recog_range), np.nan, raw_data)

        min_theta = image.angle_min
        max_theta = image.angle_max
        theta = np.linspace(min_theta , max_theta , len(raw_data))
        theta[np.where(theta == 0)] = (theta[1] - theta[0]) / 100
        d_theta = theta[1] - theta[0]

        theta = theta[~np.isnan(raw_data)]
        raw_data = raw_data[~np.isnan(raw_data)]
        non_zero_idx = np.where(raw_data != 0.0)
        raw_data = raw_data[non_zero_idx]
        theta = theta[non_zero_idx]

        raw_data, theta = self.remove_radial_lines(raw_data, theta)

        object_index_list = self.seperate_object(raw_data, theta, d_theta)

        raw_data, theta, object_index_list = self.check_back_data(raw_data, theta, object_index_list)

        # object_index_list, lerp_idx_list = self.check_acessory(theta, object_index_list)

        # raw_data, theta = self.lerp_human_object(raw_data, theta, lerp_idx_list)

        x = raw_data * np.cos(theta)
        y = raw_data * np.sin(theta)

        size_object_list = self.check_size(x, y, object_index_list)
        object_list = size_object_list

        if (self.check_linearity_flg):
            linear_idx = self.check_linearity(x, y, object_list)
            object_list = object_list[linear_idx]
            id_list = id_list[linear_idx]

        if (self.check_rightangle_flg):
            rightangle_idx = self.check_rightangle(x, y, object_list)
            object_list = object_list[rightangle_idx]
            id_list = id_list[rightangle_idx]

        if (self.check_dent_flg):
            dent_list = self.check_dent(x, y, object_list)
            object_list = object_list[dent_list]
            id_list = id_list[dent_list]

        lidar_id_list = self.trace_by_lidar_scan(x, y, raw_data, theta, object_list)

        self.set_object_queue(lidar_id_list, scan_time)

        if self.camera_integration:
            self.get_actual_fov()

        id_list = self.check_camera_integrate(lidar_id_list)

        human_id, trace_id_list = self.check_human_rate(id_list, lidar_id_list)

        for i in self.info_id_list:
            if i in human_id:
                self.info_list[i].last_human = True
            else:
                self.info_list[i].last_human = False

        human_pose = self.get_human_pose(raw_data, theta, size_object_list[trace_id_list], human_id)

        for i, id in enumerate(human_id):
            self.info_list[id].human_pose = human_pose[i]

        human_id, human_pose = self.hold_human()

        if self.camera_integration:
            human_id, human_pose = self.non_object_human(human_id, human_pose)
            self.set_human_rpy(human_id)
            human_id, human_pose = self.remove_non_human_obj(human_id, human_pose)

        human_id, human_pose = self.remove_too_close_person(human_id, human_pose)
        human_id, human_pose = self.remove_outrange_person(human_id, human_pose)

        human_pose = self.trans_pose_from_robot(human_id, human_pose)

        self.reg_sep_id(human_id, human_pose)

        self.marker_publisher(human_id, human_pose)

        if self.multi_lidar:
            self.all_info_publisher(human_id, human_pose)
        else:
            self.result_publisher(human_id, human_pose)
            self.send_tcp(human_id, human_pose)        
       
        self.get_logger().debug('scan_cb end')

    def person_associated_cb(self, msg):
        self.get_logger().debug('Receive person_associated topic')
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        persons = msg.persons
        self.last_person_topic_time = cur_time
        for person in persons:
            recog_time = person.header.stamp.sec + person.header.stamp.nanosec * 1e-9
            recog_id = person.instance_id
            class_id = person.class_id
            pixel_height = person.body_location[3]
            if pixel_height < self.max_pixel_height: continue
            rot = person.face_orientation
            loc = self.location_from_pose_sensor(person)
            if (len(loc)) != 3:
                continue
            loc = [loc[2], -loc[0], -loc[1]]
            if (loc[0] == 0.0 and loc[1] == 0.0 and loc[2] == 0.0):
                if recog_id in self.person_recog_id_list:
                    self.person_recog_info[recog_id].stamp_time = recog_time
                continue
            if len(rot) == 3:
                face_rot = [-rot[2], -rot[1], -rot[0]]
                face_angle = self.calc_face_angle(face_rot)
                face_vec = self.transformer.get_rpy_on_camera(loc, face_rot)
                face_vec_on_robot = self.transformer.transform_angle(face_vec, self.camera_link, self.robot_link)
            else:
                face_angle = 0.0
                face_vec_on_robot = []
            pose_list = self.transformer.transform_position(loc, self.camera_link, self.lidar_link)
            x_pose = pose_list[0]
            y_pose = pose_list[1]
            z_pose = pose_list[2]
            person_range = math.sqrt(math.pow(x_pose, 2) + math.pow(y_pose, 2))
            person_angle = math.atan2(y_pose, x_pose)
            if person_range > self.camera_max_range:
                continue
            if recog_id not in self.person_recog_id_list:
                self.person_recog_id_list.append(recog_id)
            if recog_id not in self.person_recog_info.keys():
                self.person_recog_info[recog_id] = PersonRecogInfo()
            self.person_recog_info[recog_id].face_angle = face_angle
            self.person_recog_info[recog_id].stamp_time = recog_time
            self.person_recog_info[recog_id].pose = [x_pose, y_pose, z_pose]
            self.person_recog_info[recog_id].rpy = face_vec_on_robot
            self.person_recog_info[recog_id].distance = person_range
            self.person_recog_info[recog_id].theta = person_angle
            self.person_recog_info[recog_id].name = person.name
            self.person_recog_info[recog_id].class_id = class_id
            self.person_recog_info[recog_id].recv_time = cur_time

    def audio_info_cb(self, audio_list):
        audio_on_cnt = 0
        for audio_info in audio_list.info:
            human_id = audio_info.human_id
            if (audio_info.vad >= 0):
                self.audio_on_flg[human_id] = True
                audio_on_cnt += 1
            else:
                self.audio_on_flg[human_id] = False

            if human_id not in self.current_audio_info.keys():
                self.audio_change_flg[human_id] = False
                self.current_audio_info[human_id] = audio_info.vad

            check_change = self.current_audio_info[human_id] * audio_info.vad
            if (check_change <= 0):
                self.audio_change_flg[human_id] = True
            self.audio_on_cnt = audio_on_cnt
            self.current_audio_info[human_id] = audio_info.vad
            if human_id not in self.current_audio_id:
                self.current_audio_id.append(human_id)

    def accept_tcp(self):
        self.get_logger().debug("accept_tcp start")
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.bind(("", self.tcp_server_port))
        tcp_server.listen(self.client_number)
        while rclpy.ok():
            client, address = tcp_server.accept()
            self.get_logger().info(f'connected to {address}')
            self.client_list.append(client)

    def calc_face_angle(self, face_rot):
        yaw = face_rot[2] * np.pi / 180.0
        pitch = face_rot[1] * np.pi / 180.0
        vec_a = np.array([0, 0, -1])
        vec_b = np.array([1, np.tan(yaw), 1.0 / np.tan(pitch)])
        len_vec_a = np.linalg.norm(vec_a)
        len_vec_b = np.linalg.norm(vec_b)
        inner_pro = np.inner(vec_a, vec_b)
        cos = inner_pro / (len_vec_a * len_vec_b)
        angle = np.arccos(cos)
        if angle > np.pi / 2.0:
            angle = np.pi - angle
        return angle
    
    def location_from_pose_sensor(self, person):
        pose = person.pose_sensor
        state = pose.confidences
        key_point = pose.keypoints
        face_loc = person.face_location_sensor
        if len(state) != 17:
            return person.body_location_sensor
        
        loc_state = []
        if state[0] != 0.0:
            loc_state.append(0)
        elif ((state[1] != 0.0) and (state[2] != 0.0)):
            loc_state.append(1)
            loc_state.append(2)
        elif ((state[5] != 0.0) and (state[6] != 0.0)):
            loc_state.append(5)
            loc_state.append(6)
        elif ((state[11] != 0.0) and (state[12] != 0.0)):
            loc_state.append(11)
            loc_state.append(12)
        else:
            if len(face_loc) == 3:
                return face_loc
            else:
                return person.body_location_sensor

        x_loc = 0.0
        y_loc = 0.0
        z_loc = 0.0
        for i in loc_state:
            x_loc += key_point[3 * i]
            y_loc += key_point[3 * i + 1]
            z_loc += key_point[3 * i + 2]
        x_loc /= len(loc_state)
        y_loc /= len(loc_state)
        z_loc /= len(loc_state)

        return [x_loc, y_loc, z_loc]

    def remove_radial_lines(self, data, theta):
        radial_cnt = 5
        remove_idx = []
        x = data * np.cos(theta)
        y = data * np.sin(theta)
        for i in range(len(x) - 4):
            x_range = x[i: i + radial_cnt]
            y_range = y[i: i + radial_cnt]
            a = ((np.dot(x_range, y_range) - y_range.sum() * x_range.sum() / radial_cnt) /
                ((x_range ** 2).sum() - x_range.sum() ** 2 / radial_cnt))
            b = (y_range.sum() - a * x_range.sum()) / radial_cnt
            distance = abs(b) / math.sqrt(math.pow(a, 2) + 1)
            if distance < 0.01:
                for k in range(radial_cnt):
                    if (i + k) not in remove_idx:
                        remove_idx.append(i + k)

        new_data = np.delete(data, remove_idx)
        new_theta = np.delete(theta, remove_idx)
        return new_data, new_theta

    def seperate_object(self, data, theta, d_theta):
        lam = self.acceptable_angle * (np.pi / 180.0)
        last_group_flg = False
        start_index_list = []
        end_index_list = []
        for i in range(len(data) - 1):
                last_d_theta = theta[i+1] - theta[i]
                if (lam == d_theta):
                    lam = d_theta + d_theta / 100
                adaptive = min(data[i], data[i+1]) / 10 * math.sin(d_theta) / math.sin(lam - d_theta)
                d_2 = math.pow(data[i], 2) + math.pow(data[i+1], 2) - 2 * data[i] * data[i+1] * math.cos(last_d_theta)
                if d_2 >= 0:
                    d = math.sqrt(d_2)
                else:
                    if last_group_flg == True:
                        end_index_list.append(i)
                        last_group_flg = False
                    continue

                if (d < abs(adaptive) or d < self.seperate_distance):
                    if last_group_flg == False:
                        start_index_list.append(i)
                        last_group_flg = True
                else:
                    if last_group_flg == True:
                        end_index_list.append(i)
                        last_group_flg = False
        if (last_group_flg):
            end_index_list.append(len(data) - 1)
        start_index_list = np.array(start_index_list)
        end_index_list = np.array(end_index_list)
        object_index_list = np.vstack([start_index_list, end_index_list])
        return object_index_list.T
    
    def check_back_data(self, data, theta, object_index_list):
        new_index_list = object_index_list
        if (len(object_index_list) != 0):
            if ((theta[object_index_list[0][0]] < -3.0) and (theta[object_index_list[-1][1]] > 3.0)):
                data = np.append(data, data[:object_index_list[0][1]])
                theta = np.append(theta, theta[:object_index_list[0][1]] + 2 * np.pi)
                new_index_list[-1][1] = new_index_list[-1][1] + object_index_list[0][1]
                new_index_list = np.delete(new_index_list, 0, 0)
        return data, theta, new_index_list

    def check_acessory(self, theta, object_index_list):
        limit_theta = 3 * (np.pi / 180.0)
        lerp_idx_list = []
        for i in self.info_id_list:
            self.info_list[i].with_accessory = False
            if (len(self.info_list[i].human_cnt) > 3):
                if (self.info_list[i].human_cnt[-4: -1] == [1, 1, 1] and self.info_list[i].last_human):
                    self.get_logger().debug('check_acessory')
                    near_point_flg = [False, False]
                    near_point_idx = [0, 0]
                    for j, object_index in enumerate(object_index_list):
                        start_diff = abs(self.info_list[i].edge_theta[0] - theta[object_index[0]])
                        end_diff = abs(self.info_list[i].edge_theta[1] - theta[object_index[1]])
                        if  (start_diff < limit_theta and not near_point_flg[0]):
                            near_point_idx[0] = j
                            near_point_flg[0] = True
                        if  (end_diff < limit_theta and near_point_flg[0]):
                            near_point_idx[1] = j
                            near_point_flg[1] = True
                    if (all(flg for flg in near_point_flg)):
                        if ((near_point_idx[1] - near_point_idx[0]) >= 2):
                            self.info_list[i].with_accessory = True
                            # lerp_idx_list.append([object_index_list[near_point_idx[0]][1], object_index_list[near_point_idx[1]][0]])
                        object_index_list[near_point_idx[0]][1] = object_index_list[near_point_idx[1]][1]
                        object_index_list = np.delete(object_index_list, slice((near_point_idx[0] + 1), (near_point_idx[1] + 1)), 0)
        return object_index_list, lerp_idx_list

    def lerp_human_object(self, raw_data, theta, lerp_idx_list):
        for lerp_idx in lerp_idx_list:
            lerp_len = int(lerp_idx[1]) - int(lerp_idx[0])
            d_data = (raw_data[lerp_idx[1]] - raw_data[lerp_idx[0]]) / lerp_len
            d_theta = (theta[lerp_idx[1]] - theta[lerp_idx[0]]) / lerp_len
            for i in range(lerp_len - 1):
                raw_data[lerp_idx[0] + i] = raw_data[lerp_idx[0]] + d_data * i
                theta[lerp_idx[0] + i] = theta[lerp_idx[0]] + d_theta * i
        return raw_data, theta
    
    def camera_check_time(self, time_diff):
        return_flg = True
        if (time_diff > 0.2):
            return_flg = False
        return return_flg

    def calc_near_id(self, obj_point, human_pose):
        ret = False
        if (len(human_pose) == 0):
            return ret
        near_range = self.camera_obj_distance
        if (obj_point.theta > self.actual_max_fov or obj_point.theta < self.actual_min_fov):
            return ret
        p_range = math.sqrt(math.pow((obj_point.x - human_pose[0]), 2) + math.pow((obj_point.y - human_pose[1]), 2))
        if p_range < near_range:
            ret = True
        return ret

    def check_size(self, x, y, object_index_list):
        size_idx_list = []
        min_idx_list = []
        size_idx = 0
        for i, object_index in enumerate(object_index_list):
            x_i = x[object_index[0]: object_index[1]]
            y_i = y[object_index[0]: object_index[1]]
            length = math.sqrt(math.pow((x_i[0] - x_i[-1]), 2) + math.pow((y_i[0] - y_i[-1]), 2))
            if (length > self.min_object_size) and (length < self.max_object_size):
                size_idx_list.append(i)
                size_idx += 1
            elif (length < self.min_object_size):
                min_idx_list.append(i)
        if (self.fusion_side_arm_flg):
            return self.fusion_side_arm(x, y, object_index_list, size_idx_list, min_idx_list)
        else:
            return object_index_list[size_idx_list]
        
    def fusion_side_arm(self, x, y, object_index_list, size_idx_list, min_idx_list):
        child_flg = [False] * len(min_idx_list)
        new_start_index_list = []
        new_end_index_list = []
        for i in size_idx_list:
            for idx, j in enumerate(min_idx_list):
                if ((1 == abs(i - j)) and not child_flg[idx]):
                    if (i > j):
                        x_diff = x[object_index_list[i][0]] - x[object_index_list[j][1]]
                        y_diff = y[object_index_list[i][0]] - y[object_index_list[j][1]]
                        obj_idx_min = object_index_list[j][0]
                        obj_idx_max = object_index_list[i][1]
                    else:
                        x_diff = x[object_index_list[i][1]] - x[object_index_list[j][0]]
                        y_diff = y[object_index_list[i][1]] - y[object_index_list[j][0]]
                        obj_idx_min = object_index_list[i][0]
                        obj_idx_max = object_index_list[j][1]
                    obj_len = math.sqrt(math.pow(x_diff, 2) + math.pow(y_diff, 2))
                    if (obj_len <= 0.3):
                        object_index_list[i][0] = obj_idx_min
                        object_index_list[i][1] = obj_idx_max
                        child_flg[idx] = True
            new_start_index_list.append(object_index_list[i][0])
            new_end_index_list.append(object_index_list[i][1])
        new_start_index_list = np.array(new_start_index_list)
        new_end_index_list = np.array(new_end_index_list)
        new_object_list = np.vstack([new_start_index_list, new_end_index_list])
        return new_object_list.T
    
    def trace_by_lidar_scan(self, x, y, data, theta, object_index_list):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        exist_id_list = []
        for i, object_index in enumerate(object_index_list):
            self.get_center_point(data[object_index[0]: object_index[1]])
            theta_ave = self.get_center_point(theta[object_index[0]: object_index[1]])
            range_ave = self.get_center_point(data[object_index[0]: object_index[1]])
            x_ave = (range_ave) * math.cos(theta_ave)
            y_ave = (range_ave) * math.sin(theta_ave)
            human_trace_id = self.check_human_trace(range_ave, theta_ave, exist_id_list)
            if human_trace_id in exist_id_list: human_trace_id = -1
            if (human_trace_id != -1):
                human_id = human_trace_id
                self.info_list[human_id].last_theta = theta_ave
                self.info_list[human_id].last_range = range_ave
                self.info_list[human_id].last_time = cur_time
            else:
                human_id = self.id_len
                self.set_info_list(human_id, theta_ave, range_ave, cur_time)
                self.info_id_list.append(human_id)
                self.id_len += 1
            
            theta_mid = self.get_center_point(theta[object_index[0]: object_index[1]])
            range_mid = self.get_center_point(data[object_index[0]: object_index[1]])
            x_mid = (range_mid) * math.cos(theta_mid)
            y_mid = (range_mid) * math.sin(theta_mid)
            mid_pose = [x_mid, y_mid]
            min_edge_pose = [x[object_index[0]], y[object_index[0]]]
            max_edge_pose = [x[object_index[1]], y[object_index[1]]]
            self.info_list[human_id].obj_pose = [mid_pose, min_edge_pose, max_edge_pose]
            self.info_list[human_id].edge_theta = [theta[object_index[0]], theta[object_index[1]]]
            if self.info_list[human_id].has_topic_id():
                time_diff = cur_time - self.info_list[human_id].last_topic_time
                if (time_diff > self.outrange_hold_time or 
                    range_ave > self.outrange_hold_range):
                    self.info_list[human_id].topic_flg = False
                    self.info_list[human_id].topic_id = np.nan
                    self.info_list[human_id].non_human_flg = False
            self.info_list[human_id].obj_flg = True
            self.info_list[human_id].current_topic_flg = False
            self.info_list[human_id].object_id = i
            self.info_list[human_id].face_angle = 0.0
            exist_id_list.append(human_id)
        return np.array(exist_id_list)
    
    def get_actual_fov(self):
        base_pose = [1.0, 0.0, 0.0]
        pose_list = self.transformer.transform_position(base_pose, self.lidar_link, self.camera_link)
        cur_camera_angle = math.atan2(pose_list[1], pose_list[0])
        self.actual_max_fov = self.camera_max_fov - cur_camera_angle
        self.actual_min_fov = self.camera_min_fov - cur_camera_angle
    
    def check_camera_integrate(self, lidar_id_list):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        exist_id_list = lidar_id_list
        time_list = self.object_queue.keys()
        for recog_id in self.person_recog_id_list:
            time_diff = cur_time - self.person_recog_info[recog_id].recv_time
            if not self.camera_check_time(time_diff):
                del self.person_recog_info[recog_id]
                self.person_recog_id_list.remove(recog_id)
                for h_id in self.info_list:
                    if self.info_list[h_id].has_topic_id():
                        self.info_list[h_id].topic_id = np.nan
        for recog_id in self.person_recog_id_list:
            camera_match_flg = False
            for scan_time in time_list:
                time_diff = abs(scan_time - self.person_recog_info[recog_id].stamp_time)
                min_time = self.scan_topic_rate
                if time_diff < min_time:
                    min_time = time_diff
                    recog_human_pose = self.person_recog_info[recog_id].pose
                    for obj in self.object_queue[scan_time]:
                        if any(self.calc_near_id(point, recog_human_pose) for point in obj.points()):
                            self.registor_camera_info(obj.human_id, recog_id)
                            human_id = obj.human_id
                            camera_match_flg = True
            if not camera_match_flg:
                x = self.person_recog_info[recog_id].pose[0]
                y = self.person_recog_info[recog_id].pose[1]
                range_ave = math.sqrt(x ** 2 + y ** 2)
                theta_ave = self.person_recog_info[recog_id].theta
                human_trace_id = self.check_human_trace(range_ave, theta_ave, exist_id_list)
                if (human_trace_id == -1):
                    human_id = self.id_len
                    self.set_info_list(human_id, theta_ave, range_ave, cur_time)
                    self.info_id_list.append(human_id)
                    self.id_len += 1
                else:
                    human_id = human_trace_id
                    self.info_list[human_id].last_theta = theta_ave
                    self.info_list[human_id].last_range = range_ave
                    self.info_list[human_id].last_time = cur_time
                    self.info_list[human_id].obj_flg = False
            self.person_recog_info[recog_id].human_id = human_id
            self.info_list[human_id].face_angle = self.person_recog_info[recog_id].face_angle
            self.info_list[human_id].last_topic_time = cur_time
            self.info_list[human_id].topic_flg = True
            self.info_list[human_id].current_topic_flg = True
            self.info_list[human_id].topic_id = recog_id
            self.info_list[human_id].non_human_flg = False
            if not self.info_list[human_id].obj_flg:
                exist_id_list = np.append(exist_id_list, human_id)

        delete_id = []
        for i in self.info_id_list:
            if ((cur_time - self.info_list[i].last_time) > self.human_hold_time):
                delete_id.append(i)
        for i in sorted(delete_id, reverse=True):
            del self.info_list[i]
            self.info_id_list.remove(i)
            if i in self.current_audio_id:
                self.current_audio_id.remove(i)
                del self.audio_on_flg[i]
                del self.current_audio_info[i]
                del self.audio_change_flg[i]
        return exist_id_list

    def registor_camera_info(self, human_id, recog_id):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        if self.person_recog_info[recog_id].human_id is not None:
            if self.person_recog_info[recog_id].human_id != human_id:
                last_h_id = self.person_recog_info[recog_id].human_id
                self.info_list[last_h_id].topic_id = np.nan
                self.info_list[last_h_id].topic_flg = False
        self.info_list[human_id].topic_id = recog_id
        self.person_recog_info[recog_id].human_id = human_id
        self.info_list[human_id].last_topic_time = cur_time
        self.info_list[human_id].current_topic_flg = True
        self.info_list[human_id].face_angle = self.person_recog_info[recog_id].face_angle
        self.info_list[human_id].non_human_flg = False

    def check_human_trace(self, range_ave, theta_ave, exist_id_list):
        human_id = -1
        move_distance = 10000.0
        if (range_ave <= 0.2):
                theta_lim = np.pi / 4.0
        else:
            theta_lim = math.asin(np.clip((self.trace_range / range_ave), -1.0, 1.0))
            theta_lim = max(theta_lim, np.pi * 5.0/180.0)
        x = (range_ave) * math.cos(theta_ave)
        y = (range_ave) * math.sin(theta_ave)
        for k in self.info_id_list:
            if self.info_list[k].human_pose is not None:
                x_diff = self.info_list[k].human_pose[0] / 1000.0 - x
                y_diff = self.info_list[k].human_pose[1] / 1000.0 - y
                pose_distance = np.sqrt(math.pow(x_diff, 2) + math.pow(y_diff, 2))
            else:
                x_diff = x
                y_diff = y
                pose_distance = np.sqrt(math.pow(x_diff, 2) + math.pow(y_diff, 2))
            theta_diff = abs(self.info_list[k].last_theta - theta_ave)
            theta_diff = min(theta_diff, abs(theta_diff - 2 * np.pi))
            # if (pose_distance < 0.5 and
            if (theta_diff < theta_lim and
                abs(self.info_list[k].last_range - range_ave) < 0.3 and
                k not in exist_id_list):
                if move_distance > pose_distance:
                    human_id = k
                    move_distance = pose_distance
                    continue
        return human_id

    def set_info_list(self, id, theta_ave, range_ave, cur_time):
        self.get_logger().debug("set_info_list: %d" % id)
        self.info_list[id] = TrackInfo(last_theta=theta_ave, last_range=range_ave, last_time=cur_time)

    def check_human_rate(self, all_id_list, id_list):
        human_id = []
        new_id_list = []
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        for id in self.info_id_list:
            if (len(self.info_list[id].human_cnt) == self.trace_count):
                self.info_list[id].human_cnt.pop(0)

            if not self.info_list[id].obj_flg:
                continue

            if (self.info_list[id].with_accessory):
                self.info_list[id].human_cnt.append(1)
                self.info_list[id].human_rate = self.calc_human_rate(id)
                self.info_list[id].human_time = cur_time
                continue

            if (id not in all_id_list):
                if self.info_list[id].current_topic_flg:
                    self.info_list[id].human_cnt.append(1)
                else:
                    self.info_list[id].human_cnt.append(0)
                self.info_list[id].human_rate = self.calc_human_rate(id)
                continue

            if (self.info_list[id].trace_human):
                human_id.append(id)
                new_id_list.append(self.info_list[id].object_id)
                self.info_list[id].human_time = cur_time
                self.info_list[id].human_cnt.append(1)
                self.info_list[id].human_rate = self.calc_human_rate(id)
                continue

            if (id in id_list):
                self.info_list[id].human_cnt.append(1)
            else:
                self.info_list[id].human_cnt.append(0)

            human_rate = self.calc_human_rate(id)
            if (human_rate >= self.human_trace_rate and len(self.info_list[id].human_cnt) == self.trace_count):
                human_id.append(id)
                new_id_list.append(self.info_list[id].object_id)
                self.info_list[id].human_rate = 1.0
                self.info_list[id].trace_human = True
            elif (human_rate >= self.max_trace_rate):
                human_id.append(id)
                new_id_list.append(self.info_list[id].object_id)
            elif (human_rate >= self.min_trace_rate and human_rate < self.max_trace_rate):
                if (id in id_list):
                    human_id.append(id)
                    new_id_list.append(self.info_list[id].object_id)
            self.info_list[id].human_rate = human_rate
            self.info_list[id].human_time = cur_time
        return human_id, new_id_list

    def calc_human_rate(self, id):
        human_rate = np.sum(self.info_list[id].human_cnt) / len(self.info_list[id].human_cnt)
        return human_rate

    def hold_human(self):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        new_human_id = []
        new_human_pose = []
        for i in self.info_id_list:
            if (self.info_list[i].last_range > 4.0 and
                not self.info_list[i].topic_flg and
                not self.info_list[i].obj_flg):
                continue
            if (self.info_list[i].human_pose is not None):
                a = 1.0 / (1.0 - self.min_trace_rate)
                b = -self.max_trace_rate * a
                remain_sec = self.info_list[i].human_rate * a + b
                remain_sec *= len(self.info_list[i].human_cnt) / self.trace_count
                
                if (remain_sec > (cur_time - self.info_list[i].human_time)):
                    new_human_id.append(i)
                    new_human_pose.append(self.info_list[i].human_pose)
        return new_human_id, new_human_pose

    def get_human_pose(self, data, theta, object_index_list, human_id):
        human_pose = []
        for  i, object_index in enumerate(object_index_list):
            theta_mid = self.get_center_point(theta[object_index[0]: object_index[1]])
            if not self.info_list[human_id[i]].obj_flg:
            # if self.info_list[human_id[i]].topic_flg:
                instance_id = self.info_list[human_id[i]].topic_id
                x_pose = self.person_recog_info[instance_id].pose[0] * 1000
                y_pose = self.person_recog_info[instance_id].pose[1] * 1000
                z_pose = self.person_recog_info[instance_id].pose[2] * 1000
            else:
                human_range = self.info_list[human_id[i]].last_range + self.human_center
                x_pose = (human_range) * math.cos(self.info_list[human_id[i]].last_theta) * 1000
                y_pose = (human_range) * math.sin(self.info_list[human_id[i]].last_theta) * 1000
                z_pose = 0.0
            human_pose.append([x_pose, y_pose, z_pose])
        return human_pose

    def get_center_point(self, data):
        off = len(data) // 2
        return (data[off] + data[-(off + 1)]) / 2

    def non_object_human(self, human_id, human_pose):
        for recog_id in self.person_recog_id_list:
            if self.person_recog_info[recog_id].human_id is not None:
                h_id = self.person_recog_info[recog_id].human_id
            if (not self.info_list[h_id].obj_flg and
                self.person_recog_info[recog_id].theta < self.actual_max_fov and
                self.person_recog_info[recog_id].theta > self.actual_min_fov):
                x_pose = self.person_recog_info[recog_id].pose[0] * 1000
                y_pose = self.person_recog_info[recog_id].pose[1] * 1000
                z_pose = self.person_recog_info[recog_id].pose[2] * 1000
                person_id = self.person_recog_info[recog_id].human_id
                self.info_list[person_id].topic_id = recog_id
                human_pose.append([x_pose, y_pose, z_pose])
                human_id.append(person_id)
        return  human_id, human_pose
    
    def set_human_rpy(self, human_id):
        for id in human_id:
            instance_id = self.info_list[id].topic_id
            if instance_id in self.person_recog_info:
                self.info_list[id].human_rpy = self.person_recog_info[instance_id].rpy
            else:
                self.info_list[id].human_rpy = []

    def reg_sep_id(self, human_id, human_pose):
        calc_sep_flg = False
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        for audio_id in self.current_audio_id:
            if self.audio_change_flg[audio_id]:
                calc_sep_flg = True
                self.audio_change_flg[audio_id] = False
        for h_id in human_id:
            if h_id not in self.last_id:
                calc_sep_flg = True
        self.last_id = human_id
        if calc_sep_flg:
            sort_data = []
            priority_flg_list = []
            weight_list = []
            priority_cnt = 0
            for (id, pose) in zip(human_id, human_pose):
                data = {}
                data["human_id"] = id
                cur_range = math.sqrt(pose[0] ** 2 + pose[1] ** 2)
                cur_angle = math.atan2(pose[1], pose[0])
                if (cur_range < self.priority_range * 1000 and
                    cur_angle > self.priority_min_angle and
                    cur_angle < self.priority_max_angle):
                    data["priority_flg"] = True
                    priority_flg_list.append(True)
                    priority_cnt += 1
                else:
                    data["priority_flg"] = False
                    priority_flg_list.append(False)
                d_range = cur_range / 1000.0
                d_angle = abs(cur_angle) / np.pi
                d_face_dir = abs(self.info_list[id].face_angle) / np.pi
                weight = self.range_weight * d_range + self.angle_weight * d_angle + self.face_dir_weight * d_face_dir
                weight_list.append(-weight)
                data["weight"] = -weight
                if id in self.audio_on_flg:
                    data["audio_flg"] = True
                else:
                    data["audio_flg"] = False
                sort_data.append(data)

            sorted_data = sorted(sort_data, key=lambda x: (x["priority_flg"], x["audio_flg"], x["weight"]), reverse=True)

            if priority_cnt < self.prority_sep_num:
                cnt_offset = self.prority_sep_num - priority_cnt
            else:
                cnt_offset = 0
            sep_cnt = 0
            id_start = 2
            for i in range(len(sorted_data)):
                id_cnt = sep_cnt + id_start
                if (id_cnt + cnt_offset) > self.max_sep_id:
                    sorted_data[i]["sep_id"] = INVALID_VALUE
                    continue
                if i < priority_cnt:
                    sorted_data[i]["sep_id"] = id_cnt
                else:
                    sorted_data[i]["sep_id"] = id_cnt + cnt_offset
                sep_cnt += 1

            for i in range(self.prority_sep_num - cnt_offset):
                if i > sep_cnt:
                    continue
                human_id = sorted_data[i]["human_id"]
                if self.info_list[human_id].sep_id is not None:
                    last_sep = self.info_list[human_id].sep_id
                    if last_sep == INVALID_VALUE: continue
                    if (last_sep < self.prority_sep_num + 1 and 
                        last_sep != sorted_data[i]["sep_id"] and
                        last_sep <= priority_cnt):
                        l_sep = [d.get("sep_id") for d in sorted_data[:self.prority_sep_num]]
                        if last_sep in l_sep:
                            idx = l_sep.index(last_sep)
                            sorted_data[idx]["sep_id"] = sorted_data[i]["sep_id"]
                            sorted_data[i]["sep_id"] = last_sep
                        else:
                            sorted_data[i]["sep_id"] = last_sep
            for i in range(sep_cnt - priority_cnt):
                if i >= sep_cnt:
                    continue
                human_id = sorted_data[i + priority_cnt]["human_id"]
                if self.info_list[human_id].sep_id is not None:
                    last_sep = self.info_list[human_id].sep_id
                    if last_sep == INVALID_VALUE: continue
                    if (last_sep > priority_cnt + cnt_offset + 1 and 
                        last_sep != sorted_data[i + priority_cnt]["sep_id"] and
                        last_sep <= sep_cnt + cnt_offset and
                        sep_cnt != priority_cnt):
                        l_sep = [d.get("sep_id") for d in sorted_data[priority_cnt:]]
                        if last_sep in l_sep:
                            idx = l_sep.index(last_sep)
                            sorted_data[idx + priority_cnt]["sep_id"] = sorted_data[i + priority_cnt]["sep_id"]
                            sorted_data[i + priority_cnt]["sep_id"] = last_sep
                        else:
                            sorted_data[i + priority_cnt]["sep_id"] = last_sep
            for i in range(len(sorted_data)):
                self.info_list[sorted_data[i]["human_id"]].sep_id = sorted_data[i]["sep_id"]

    def check_linearity(self, x, y, object_index_list):
        linear_idx = []
        for i, object_index in enumerate(object_index_list):
            x_i = x[object_index[0]: object_index[1]]
            y_i = y[object_index[0]: object_index[1]]
            mape, pred, x_axis = self.calc_mape(x_i, y_i)
            if (mape > self.linearity_limit):
                linear_idx.append(i)
        return linear_idx

    def check_rightangle(self, x, y, object_index_list):
        rightangle_idx = []
        for i, object_index in enumerate(object_index_list):
            x_i = x[object_index[0]: object_index[1]]
            y_i = y[object_index[0]: object_index[1]]
            last_index = [0, len(x_i) - 1]
            linear_flg = False
            while not (linear_flg):
                linear_flg = True
                new_index = []
                for j in range(len(last_index) - 1):
                    new_index.append(last_index[j])
                    max_l = 0
                    max_index = 0
                    for k in range(last_index[j], last_index[j + 1]):
                        u = np.array([x_i[last_index[j + 1]] - x_i[last_index[j]], y_i[last_index[j + 1]] - y_i[last_index[j]]])
                        v = np.array([x_i[k] - x_i[last_index[j]], y_i[k] - y_i[last_index[j]]])
                        if (max_l != max(max_l, abs(np.cross(u, v) / np.linalg.norm(u)))):
                            max_l = abs(np.cross(u, v) / np.linalg.norm(u))
                            max_index = k

                    if (max_l != 0):
                        x_sep_1 = x_i[last_index[j]: max_index]
                        y_sep_1 = y_i[last_index[j]: max_index]
                        if (len(x_sep_1) > 2):
                            mape_sep_1, pred_1, x_axis_1 = self.calc_mape(x_sep_1, y_sep_1)
                            if (mape_sep_1 > self.linearity_limit):
                                linear_flg = False
                        x_sep_2 = x_i[max_index: last_index[j + 1]]
                        y_sep_2 = y_i[max_index: last_index[j + 1]]
                        if (len(x_sep_2) > 2):
                            mape_sep_2, pred_2, x_axis_2 = self.calc_mape(x_sep_2, y_sep_2)
                            if (mape_sep_2 > self.linearity_limit):
                                linear_flg = False
                        new_index.append(max_index)

                new_index.append(last_index[-1])
                last_index = new_index
            rightangle_flg = False
            for len_idx in range(len(last_index) - 2):
                vec1 = [x_i[last_index[len_idx]] - x_i[last_index[len_idx + 1]], 
                        y_i[last_index[len_idx]] - y_i[last_index[len_idx + 1]]]
                vec2 = [x_i[last_index[len_idx + 2]] - x_i[last_index[len_idx + 1]], 
                        y_i[last_index[len_idx + 2]] - y_i[last_index[len_idx + 1]]]
                absvec1 = np.linalg.norm(vec1)
                absvec2 = np.linalg.norm(vec2)
                inner = np.inner(vec1, vec2)
                cos_theta = inner / (absvec1 * absvec2)
                theta_corner = math.degrees(math.acos(np.clip(cos_theta, -1.0, 1.0)))
                if (theta_corner < self.max_rightangle_limit) and (theta_corner > self.min_rightangle_limit):
                    rightangle_flg = True
                    break
            if not (rightangle_flg):
                rightangle_idx.append(i)
        return rightangle_idx

    def calc_mape(self, x, y):
        if len(x) == 0:
            return 0, 0, False
        x_diff = np.max(x) - np.min(x)
        y_diff = np.max(y) - np.min(y)
        if (x_diff < y_diff):
            coef_y = np.polyfit(y, x, 1)
            pred = coef_y[0] * y + coef_y[1]
            non_zero_idx = np.where(x != 0)
            diff = (pred[non_zero_idx] - x[non_zero_idx]) / x[non_zero_idx]
            mape = np.mean(np.abs(diff)) * 100
            x_axis = True
        else:
            coef_x = np.polyfit(x, y, 1)
            pred = coef_x[0] * x + coef_x[1]
            non_zero_idx = np.where(y != 0)
            diff = (pred[non_zero_idx] - y[non_zero_idx]) / y[non_zero_idx]
            mape = np.mean(np.abs(diff)) * 100
            x_axis = False

        return mape, pred, x_axis

    def check_dent(self, x, y, object_index_list):
        dent_idx = []
        for i, object_index in enumerate(object_index_list):
            x_i = x[object_index[0]: object_index[1]]
            y_i = y[object_index[0]: object_index[1]]
            x_diff = np.max(x_i) - np.min(x_i)
            y_diff = np.max(y_i) - np.min(y_i)
            if (x_diff > y_diff):
                long_axis = x_i
                short_axis = y_i
            else:
                long_axis = y_i
                short_axis = x_i
            a = (short_axis[-1] - short_axis[0]) / (long_axis[-1] - long_axis[0])
            b = short_axis[0] - a * long_axis[0]
            integral = 0
            for j in range(len(x_i)):
                integral += short_axis[j] - (a * long_axis[j] + b)
            if (abs(integral) > self.dent_limit):
                dent_idx.append(i)
        return dent_idx
    
    def remove_non_human_obj(self, human_id, human_pose):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        pop_list = []
        for i, h_id in enumerate(human_id):
            if (self.info_list[h_id].topic_flg and
                cur_time - self.info_list[h_id].last_topic_time > 3.0):
                if (self.info_list[h_id].last_theta < self.actual_max_fov and
                    self.info_list[h_id].last_theta > self.actual_min_fov):
                    self.info_list[h_id].topic_flg = False
                    self.info_list[h_id].non_human_flg = True
                    pop_list.append(i)
                    continue
            if self.info_list[h_id].edge_theta is not None:
                if ((cur_time - self.last_person_topic_time) < self.camera_topic_hold_time and
                    not self.info_list[h_id].topic_flg):
                    if (self.info_list[h_id].edge_theta[1] < self.actual_max_fov and
                        self.info_list[h_id].edge_theta[0] > self.actual_min_fov):
                        self.info_list[h_id].non_human_flg = True
                        pop_list.append(i)
                        continue
                if (self.info_list[h_id].non_human_flg and
                    self.info_list[h_id].edge_theta[0] > self.actual_max_fov and
                    self.info_list[h_id].edge_theta[1] < self.actual_min_fov):
                    pop_list.append(i)
        for pop_num in sorted(pop_list, reverse=True):
            human_id.pop(pop_num)
            human_pose.pop(pop_num)
        return human_id, human_pose
    
    def remove_too_close_person(self, human_id, human_pose):
        pop_list = []
        def_human_id = human_id
        def_human_pose = human_pose
        for i in range(len(human_id)):
            if i in pop_list:
                continue
            base_id = human_id[i]
            base_pose = human_pose[i]
            base_topic_flg = self.info_list[base_id].topic_flg
            for j in range(i + 1, len(human_id)):
                if j in pop_list:
                    continue
                comp_id = human_id[j]
                comp_pose = human_pose[j]
                comp_topic_flg = self.info_list[comp_id].topic_flg
                x_range = abs(base_pose[0] - comp_pose[0])
                y_range = abs(base_pose[1] - comp_pose[1])
                if (x_range <= self.too_close_range and y_range <= self.too_close_range):
                    if base_topic_flg != comp_topic_flg:
                        if base_topic_flg:
                            if not self.check_rate(comp_id):
                                pop_list.append(j)
                        else:
                            if not self.check_rate(base_id):
                                pop_list.append(i)
                    else:
                        if base_id <= comp_id:
                            pop_list.append(j)
                        else:
                            pop_list.append(i)
        for pop_num in sorted(pop_list, reverse=True):
            try:
                human_id.pop(pop_num)
                human_pose.pop(pop_num)
            except:
                self.get_logger().debug('too_close pop error. def_len:%d, len:%d, idx:%d' % (len(def_human_id), len(human_id), pop_num))
                if len(human_id) != len(human_pose):
                    human_id = def_human_id
                    human_pose = def_human_pose
        return human_id, human_pose
    
    def remove_outrange_person(self, human_id, human_pose):
        pop_list = []
        for i, h_id in enumerate(human_id):
            if self.info_list[h_id].last_theta > np.pi:
                self.info_list[h_id].last_theta -= 2 * np.pi
            if (self.info_list[h_id].last_theta > self.upper_recog_angle or
                self.info_list[h_id].last_theta < self.lower_recog_angle):
                pop_list.append(i)
            self.get_logger().debug("angle: %f, %f, %f" % (self.info_list[h_id].last_theta, self.upper_recog_angle, self.lower_recog_angle))
        for pop_num in sorted(pop_list, reverse=True):
            human_id.pop(pop_num)
            human_pose.pop(pop_num)
        return human_id, human_pose


    def check_rate(self, human_id):
        if (len(self.info_list[human_id].human_cnt) > self.trace_count / 2 and
            self.info_list[human_id].human_rate > 0.5):
            return True
        else:
            return False

    def trans_pose_from_robot(self, human_id, human_pose):
        new_human_pose = []
        for (h_id, pose) in zip(human_id, human_pose):
            pose_from_robot = self.transformer.transform_position([x / 1000 for x in pose], self.lidar_link, self.robot_link)
            if not self.info_list[h_id].current_topic_flg:
                pose_from_robot[2] = 0.0
            new_human_pose.append([x * 1000 for x in pose_from_robot])
        return new_human_pose

    def result_publisher(self, human_id, human_pose):
        result_data = TrackedPersons()
        time_stamp = self.get_clock().now().to_msg()
        result_data.header.stamp = time_stamp
        for (h_id, pose) in zip(human_id, human_pose):
            person_data = TrackedPerson()
            person_data.time_stamp = time_stamp
            person_data.human_id = int(h_id)
            person_data.sep_id = int(self.info_list[h_id].sep_id)
            person_data.xyz = pose
            person_data.face_direction = self.info_list[h_id].human_rpy
            result_data.persons.append(person_data)
        self.human_tracker_result_pub.publish(result_data)

    def marker_publisher(self, human_id, human_pose):
        current_human_id = []
        time_stamp = self.get_clock().now().to_msg()
        for (h_id, pose) in zip(human_id, human_pose):
            if h_id not in self.marker_id_list:
                marker = Marker()
                marker_name = Marker()
            else:
                idx = self.marker_id_list.index(int(h_id))
                marker = self.marker_array.markers[idx * 2]
                marker_name = self.marker_array.markers[idx * 2 + 1]

            marker.header.frame_id = self.rviz_fixed_frame
            marker.header.stamp = time_stamp
            marker.ns = 'human_pose'
            marker.id = int(h_id) * 2
            marker.lifetime = Duration(seconds=1.0).to_msg()
            current_human_id.append(h_id)

            if (h_id in self.last_human_id):
                self.last_human_id.remove(h_id)

            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            marker.scale.x = 0.15
            marker.scale.y = 0.15
            marker.scale.z = 0.15
            marker.pose.position.x = pose[0] / 1000
            marker.pose.position.y = pose[1] / 1000
            marker.pose.position.z = 0.0

            audio_on = False
            if (h_id in self.current_audio_id):
                if self.audio_on_flg[h_id]:
                    audio_on = True

            if audio_on:
                MarkerColor.AUDIO_ON.apply(marker)
            elif (not self.info_list[h_id].current_topic_flg):
                MarkerColor.LIDAR_ONLY.apply(marker)
            elif (self.info_list[h_id].obj_flg):
                MarkerColor.FUSED.apply(marker)
            else:
                MarkerColor.CAMERA_ONLY.apply(marker)

            marker_name.header.frame_id = self.rviz_fixed_frame
            marker_name.header.stamp = time_stamp
            marker_name.ns = 'human_pose'
            marker_name.id = int(h_id) * 2 + 1
            marker_name.lifetime = Duration(seconds=1.0).to_msg()

            marker_name.type = Marker.TEXT_VIEW_FACING
            marker_name.action = marker_name.ADD
            marker_name.pose.position.x = pose[0] / 1000
            marker_name.pose.position.y = pose[1] / 1000
            marker_name.pose.position.z = 0.2
            marker_name.scale.x = 0.15
            marker_name.scale.y = 0.15
            marker_name.scale.z = 0.15

            if (self.rviz_view_text == ViewText.NAME):
                if (not self.info_list[h_id].has_topic_id() and
                    self.info_list[h_id].obj_flg):
                    MarkerColor.TRANSPARENT.apply(marker_name)
                    marker_name.text = ""
                else:
                    MarkerColor.TEXT.apply(marker_name)
                    i_id = self.info_list[h_id].topic_id
                    marker_name.text = self.person_recog_info[i_id].name
            elif (self.rviz_view_text == ViewText.SEP_ID):
                MarkerColor.TEXT.apply(marker_name)
                marker_name.text = str(self.info_list[h_id].sep_id)
            elif (self.rviz_view_text == ViewText.HUMAN_ID):
                MarkerColor.TEXT.apply(marker_name)
                marker_name.text = str(h_id)

            if h_id not in self.marker_id_list:
                self.marker_array.markers.append(marker)
                self.marker_array.markers.append(marker_name)
                self.marker_id_list.append(h_id)

        for delete_id in self.last_human_id:
            if not delete_id in self.marker_id_list:
                continue
            idx = self.marker_id_list.index(delete_id)

            delete_marker = self.marker_array.markers[idx * 2]
            delete_marker.header.frame_id = self.rviz_fixed_frame
            delete_marker.ns = 'human_pose'
            delete_marker.id = int(delete_id) * 2
            delete_marker.action = Marker.DELETE

            delete_marker_name = self.marker_array.markers[idx * 2 + 1]
            delete_marker_name.header.frame_id = self.rviz_fixed_frame
            delete_marker_name.ns = 'human_pose'
            delete_marker_name.id = int(delete_id) * 2 + 1
            delete_marker_name.action = Marker.DELETE

        self.marker_pub.publish(self.marker_array)

        for delete_id in sorted(self.last_human_id, reverse=True):
            for i, marker in enumerate(self.marker_array.markers):
                if (marker.id == delete_id * 2):
                    self.marker_array.markers.pop(i)
                    self.marker_array.markers.pop(i)
                    self.marker_id_list.remove(delete_id)
        self.last_human_id = current_human_id

    def get_recog_identity(self, h_id):
        """対応するカメラ認識結果の (class_id, instance_id, name) を返す"""
        info = self.info_list[h_id]
        if not info.has_topic_id():
            return INVALID_VALUE, INVALID_VALUE, ""
        recog_info = self.person_recog_info[info.topic_id]
        return recog_info.class_id, info.topic_id, recog_info.name

    def send_tcp(self, human_id, human_pose):
        time = self.get_clock().now().seconds_nanoseconds()
        sec = float(time[0])
        msec = float(time[1]) * 1e-6
        send_msg = ""
        for (h_id, pose) in zip(human_id, human_pose):
            class_id, instance_id, person_name = self.get_recog_identity(h_id)
            send_msg += build_tcp_record(sec, msec, h_id, pose, self.info_list[h_id].sep_id,
                                         class_id, instance_id, person_name)
        send_msg = send_msg.encode('shift_jis')

        for client in self.client_list:
            try:
                client.send(send_msg)
            except socket.error:
                self.get_logger().debug('close tcp connection')
                self.client_list.remove(client)
                client.close()
                continue

    def all_info_publisher(self, human_id, human_pose):
        pub_data = PersonAllInfoList()
        time_stamp = self.get_clock().now().to_msg()
        pub_data.header.stamp = time_stamp
        for (h_id, pose) in zip(human_id, human_pose):
            class_id, instance_id, person_name = self.get_recog_identity(h_id)
            all_info_data = PersonAllInfo()
            all_info_data.human_id = int(h_id)
            all_info_data.sep_id = int(self.info_list[h_id].sep_id)
            all_info_data.xyz = pose
            all_info_data.face_direction = self.info_list[h_id].human_rpy
            all_info_data.face_angle = self.info_list[h_id].face_angle
            all_info_data.class_id = class_id
            all_info_data.instance_id = instance_id
            all_info_data.name = person_name
            all_info_data.camera_info_exist = self.info_list[h_id].current_topic_flg
            all_info_data.lidar_info_exist = self.info_list[h_id].obj_flg
            pub_data.all_info.append(all_info_data)
        self.person_all_info_pub.publish(pub_data)

    def set_object_queue(self, lidar_id_list, scan_time):
        self.object_queue[scan_time] = []
        for h_id in lidar_id_list:
            info = self.info_list[h_id]
            mid_pose, min_edge_pose, max_edge_pose = info.obj_pose
            self.object_queue[scan_time].append(QueuedObject(
                human_id=h_id,
                mid=ObjectPoint(mid_pose[0], mid_pose[1], info.last_theta),
                min_edge=ObjectPoint(min_edge_pose[0], min_edge_pose[1], info.edge_theta[0]),
                max_edge=ObjectPoint(max_edge_pose[0], max_edge_pose[1], info.edge_theta[1])))
        time_list = self.object_queue.keys()
        if len(time_list) > self.object_queue_size:
            earliest_time = min(time_list)
            del self.object_queue[earliest_time]


def main():
    rclpy.init()
    node = HumanTracker()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
