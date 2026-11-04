import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy import qos
from rclpy.time import Duration, Time
from rclpy.callback_groups import ReentrantCallbackGroup

import math
import numpy as np
import threading
import socket
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

from visualization_msgs.msg import Marker, MarkerArray
from human_tracker_msgs.msg import TrackedPersons, TrackedPerson, PersonAllInfoList
from human_tracker_msgs.msg import AudioInfoList

from pyindy.param_manager import ParamManager
from .track_info import (DEFAULT_AUDIO_PORT, INVALID_VALUE, IntegratedPerson, LidarPerson, MarkerColor, TrackingInfo,
                         ViewText, build_tcp_record, parse_view_text)

class HumanTrackerIntegration(Node):
    def __init__(self):
        super().__init__('human_tracker_integration_node')

        self.robot_name = self.get_namespace()

        self.declare_parameter('right_node_name', "")
        self.declare_parameter('left_node_name', "")
        self.declare_parameter('integrate_angle', 20.0)
        self.declare_parameter('matching_range', 0.2)
        self.declare_parameter('trace_range', 0.4)
        self.declare_parameter('priority_range', 2.0)
        self.declare_parameter('too_close_range', 0.2)
        self.declare_parameter('priority_min_angle', -60.0)
        self.declare_parameter('priority_max_angle', 60.0)
        self.declare_parameter('range_weight', 1.0)
        self.declare_parameter('angle_weight', 1.0)
        self.declare_parameter('face_direction_weight', 1.0)
        self.declare_parameter('prority_sep_num', 2)
        self.declare_parameter('max_sep_id', 7)
        self.declare_parameter('save_db', True)
        self.declare_parameter('rviz_fixed_frame', "")
        self.declare_parameter('rviz_view_text', "")
        self.declare_parameter('client_number', 10)

        right_node_name = self.get_parameter('right_node_name').get_parameter_value().string_value
        left_node_name = self.get_parameter('left_node_name').get_parameter_value().string_value
        integrate_angle_deg = self.get_parameter('integrate_angle').get_parameter_value().double_value
        matching_range = self.get_parameter('matching_range').get_parameter_value().double_value
        trace_range = self.get_parameter('trace_range').get_parameter_value().double_value
        too_close_range = self.get_parameter('too_close_range').get_parameter_value().double_value
        self.priority_range = self.get_parameter('priority_range').get_parameter_value().double_value
        priority_min_deg = self.get_parameter('priority_min_angle').get_parameter_value().double_value
        priority_max_deg = self.get_parameter('priority_max_angle').get_parameter_value().double_value
        self.range_weight = self.get_parameter('range_weight').get_parameter_value().double_value
        self.angle_weight = self.get_parameter('angle_weight').get_parameter_value().double_value
        self.face_dir_weight = self.get_parameter('face_direction_weight').get_parameter_value().double_value
        self.prority_sep_num = self.get_parameter('prority_sep_num').get_parameter_value().integer_value
        self.max_sep_id = self.get_parameter('max_sep_id').get_parameter_value().integer_value
        self.save_db = self.get_parameter('save_db').get_parameter_value().bool_value
        rviz_fixed_frame = self.get_parameter('rviz_fixed_frame').get_parameter_value().string_value
        self.rviz_view_text = self.get_parameter('rviz_view_text').get_parameter_value().string_value
        self.client_number = self.get_parameter('client_number').get_parameter_value().integer_value

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

        # 結果保存先DBのホストは上で取得したmongo_uriを使う
        self.declare_parameter('env_mongo_port', 3000)
        mongo_port = self.get_parameter('env_mongo_port').get_parameter_value().integer_value

        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        self.module_result_db = mongo_client["log"]
        self.human_tracker_collection = self.module_result_db["result_human_tracker"]

        self.rviz_fixed_frame = self.robot_name + "_" + rviz_fixed_frame

        self.rviz_view_text = parse_view_text(self.rviz_view_text, self.get_logger())

        self.integrate_angle = integrate_angle_deg * (np.pi / 180.0)
        self.matching_range = matching_range * 1000.0
        self.trace_range = matching_range * 1000.0
        self.too_close_range = too_close_range * 1000.0
        self.priority_min_angle = priority_min_deg * np.pi / 180.0
        self.priority_max_angle = priority_max_deg * np.pi / 180.0

        if right_node_name[-5:] == "_node":
            right_node_name = right_node_name[:-5]
        right_topic_name = right_node_name + "/person_all_info"
        if left_node_name[-5:] == "_node":
            left_node_name = left_node_name[:-5]
        left_topic_name = left_node_name + "/person_all_info"

        self.right_result = PersonAllInfoList()
        self.left_result = PersonAllInfoList()

        # human_id -> TrackingInfo
        self.tracking_info_dict = {}
        self.human_id_list = []
        self.audio_time = {}
        self.current_audio_id = []
        self.audio_on_flg = {}

        self.right_time = 0.0
        self.left_time = 0.0
        self.human_id_cnt = 1

        self.last_human_id = []

        self.marker_array = MarkerArray()
        self.marker_id_list = []

        self.client_list = []
        thread_accept_tcp = threading.Thread(target=self.accept_tcp)
        thread_accept_tcp.setDaemon(True)
        thread_accept_tcp.start()

        self.human_tracker_result_pub = self.create_publisher(TrackedPersons, "human_tracker/recognition_result", 10)
        self.marker_pub = self.create_publisher(MarkerArray, "human_tracker/human_pose_marker", 10)

        right_callback_group = None
        left_callback_group = None
        scan_qos = qos.QoSProfile(depth=10)
        scan_qos.reliability = qos.QoSReliabilityPolicy.BEST_EFFORT 
        self.right_human_info_sub = self.create_subscription(PersonAllInfoList, right_topic_name, self.right_human_cb, 10, callback_group=right_callback_group)
        self.left_human_info_sub = self.create_subscription(PersonAllInfoList, left_topic_name, self.left_human_cb, 10, callback_group=left_callback_group)
        self.audio_info_sub = self.create_subscription(AudioInfoList, "human_tracker/audio_info", self.audio_info_cb, 10)

        timer_cb_group = None
        self.call_timer = self.create_timer(0.1, self.integrate_loop, callback_group=timer_cb_group)

    def right_human_cb(self, right_result):
        self.get_logger().debug('right receive')
        self.right_result = right_result
        self.right_time = right_result.header.stamp.sec + right_result.header.stamp.nanosec * 1e-9
        return

    def left_human_cb(self, left_result):
        self.get_logger().debug('left receive')
        self.left_result = left_result
        self.left_time = left_result.header.stamp.sec + left_result.header.stamp.nanosec * 1e-9
        return

    def audio_info_cb(self, audio_list):
        for audio_info in audio_list.info:
            human_id = audio_info.human_id
            if human_id == -1:
                continue
            self.audio_time[human_id] = audio_info.timestamp_sec + audio_info.timestamp_msec * 10e-3
            if (audio_info.vad > 0):
                self.audio_on_flg[human_id] = True
            else:
                self.audio_on_flg[human_id] = False

            if human_id not in self.current_audio_id:
                self.current_audio_id.append(human_id)
            elif audio_info.vad == -1:
                self.current_audio_id.remove(human_id)

    def accept_tcp(self):
        self.get_logger().debug("accept_tcp start")
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind(("", self.tcp_server_port))
        tcp_server.listen(self.client_number)
        while rclpy.ok():
            client, address = tcp_server.accept()
            self.get_logger().debug('connected')
            self.client_list.append(client)

    def integrate_loop(self):
        cur_time = self.get_clock().now().nanoseconds * 1e-9

        self.check_topic_time(cur_time)
        self.check_audio_time(cur_time)
        if (cur_time - self.right_time) > 1.0:
            right_result = PersonAllInfoList()
        else:
            right_result = self.right_result
        if (cur_time - self.left_time) > 1.0:
            left_result = PersonAllInfoList()
        else:
            left_result = self.left_result
        right_info = self.get_human_info(right_result, -np.pi / 2.0)
        left_info = self.get_human_info(left_result, np.pi / 2.0)

        integrated_info = self.check_integration(right_info, left_info)

        integrated_info, human_id_list = self.tracking_id(integrated_info)

        self.get_sep_id(integrated_info, human_id_list)

        self.result_publisher(integrated_info, human_id_list)
        self.marker_publisher(integrated_info, human_id_list)
        self.send_tcp(human_id_list)
        if self.save_db:
            self.save_result_db(human_id_list)

    def check_topic_time(self, cur_time):
        right_ros_time = self.right_result.header.stamp
        right_time = right_ros_time.sec + right_ros_time.nanosec * 1e-9
        if (cur_time - right_time) > 1.0:
            self.right_result = PersonAllInfoList()
        left_ros_time = self.left_result.header.stamp
        left_time = left_ros_time.sec + left_ros_time.nanosec * 1e-9
        if (cur_time - left_time) > 1.0:
            self.left_result = PersonAllInfoList()

    def check_audio_time(self, cur_time):
        for h_id in self.current_audio_id:
            if (cur_time - self.audio_time[h_id]) < 0.5:
                self.current_audio_id.remove(h_id)
                del self.audio_on_flg[h_id]
                del self.audio_time[h_id]

    def get_human_info(self, human_result, lidar_angle):
        person_info = []
        for person in human_result.all_info:
            angle = math.atan2(person.xyz[1], person.xyz[0])
            angle_from_lidar = angle - lidar_angle
            if (angle_from_lidar > np.pi):
                angle_from_lidar -= 2 * np.pi
            elif (angle_from_lidar < -np.pi):
                angle_from_lidar += 2 * np.pi
            # 左右LiDARの担当範囲外の人情報を除去
            if abs(angle_from_lidar) < np.pi / 2.0 + self.integrate_angle:
                person_info.append(LidarPerson(person, angle_from_lidar))
        return person_info
    
    def check_integration(self, right_info, left_info):
        integrated_info = []
        linfo_integrated_flg = []
        for rinfo in right_info:
            rinfo_integrated_flg = False
            rinfo_pose = rinfo.person.xyz
            min_distance = 1000.0
            for linfo in left_info:
                linfo_pose = linfo.person.xyz
                d_x = linfo_pose[0] - rinfo_pose[0]
                d_y = linfo_pose[1] - rinfo_pose[1]
                distance = math.sqrt(d_x * d_x + d_y * d_y)
                if (distance < self.matching_range and
                    distance < min_distance):
                # if (distance < self.matching_range or
                #     ((rinfo.person.instance_id == linfo.person.instance_id) and
                #     rinfo.person.instance_id != INVALID_VALUE)):
                    if(abs(rinfo.angle) <= abs(linfo.angle)):
                        weight = abs(np.pi / 2.0 - abs(rinfo.angle))
                        r_weight = min((weight / self.integrate_angle) / 2.0 + 0.5, 1.0)
                        l_weight = 1.0 - r_weight
                    else:
                        weight = abs(np.pi / 2.0 - abs(linfo.angle))
                        l_weight = min((weight / self.integrate_angle) / 2.0 + 0.5, 1.0)
                        r_weight = 1.0 - l_weight
                    x = r_weight * rinfo_pose[0] + l_weight * linfo_pose[0]
                    y = r_weight * rinfo_pose[1] + l_weight * linfo_pose[1]
                    if y >= 0.0:
                        person_result = linfo.person
                        primary_idx = 1
                    else:
                        person_result = rinfo.person
                        primary_idx = 0
                    person_result.xyz[0] = x
                    person_result.xyz[1] = y
                    rinfo_integrated_flg = True
                    min_distance = distance
                    integrated_left = linfo.person
            if rinfo_integrated_flg:
                integrated_info.append(IntegratedPerson(rinfo.person.human_id, integrated_left.human_id, person_result, primary_idx))
                linfo_integrated_flg.append(integrated_left)
            else:
                integrated_info.append(IntegratedPerson(rinfo.person.human_id, -1, rinfo.person, 0))
        for linfo in left_info:
            if not linfo.person in linfo_integrated_flg:
                integrated_info.append(IntegratedPerson(-1, linfo.person.human_id, linfo.person, 1))
        return integrated_info

    def tracking_id(self, integrated_info):
        cur_time = self.get_clock().now().nanoseconds * 1e-9
        new_human_id_list = []
        new_integrated_info = []
        instance_dict = {}
        pose_list = []
        for i, tracking_id in enumerate(self.tracking_info_dict.keys()):
            instance_dict[i] = [tracking_id, self.tracking_info_dict[tracking_id].instance_id]

        for info in integrated_info:
            trace_flg = False
            min_range = 1000.0
            for tracking_id in self.tracking_info_dict.keys():
                x_move = info.person.xyz[0] - self.tracking_info_dict[tracking_id].pose[0]
                y_move = info.person.xyz[1] - self.tracking_info_dict[tracking_id].pose[1]
                move_range = np.sqrt(math.pow(x_move, 2) + math.pow(y_move, 2))
                if (move_range < self.trace_range and
                    move_range < min_range):
                    trace_flg = True
                    last_h_id = tracking_id
                    min_range = move_range
                    break

            instance_match_flg = False
            # for instance_key in instance_dict.keys():
            #     if info.person.instance_id == instance_dict[instance_key][1] and info.person.instance_id != INVALID_VALUE:
            #         instance_match_flg = True
            #         last_h_id = instance_dict[instance_key][0]
            #         break

            if (trace_flg or instance_match_flg) and last_h_id not in new_human_id_list:
                cur_id = last_h_id
                if info.person.instance_id != INVALID_VALUE:
                    self.tracking_info_dict[cur_id].instance_id = info.person.instance_id
                    self.tracking_info_dict[cur_id].class_id = info.person.class_id
                    self.tracking_info_dict[cur_id].name = info.person.name
            else:
                cur_id = self.human_id_cnt
                self.tracking_info_dict[cur_id] = TrackingInfo(
                    pose=info.person.xyz,
                    last_detect_time=cur_time,
                    instance_id=info.person.instance_id,
                    class_id=info.person.class_id,
                    name=info.person.name)
                self.human_id_list.append(cur_id)
                self.human_id_cnt += 1
            self.tracking_info_dict[cur_id].pose = info.person.xyz

            too_close_flg = False
            for pose in pose_list:
                d_x = info.person.xyz[0] - pose[0]
                d_y = info.person.xyz[1] - pose[1]
                d_range = np.sqrt(math.pow(d_x, 2) + math.pow(d_y, 2))
                if d_range < self.too_close_range:
                    too_close_flg = True
                    break
            if not too_close_flg:
                pose_list.append(info.person.xyz)
                new_integrated_info.append(info)
                new_human_id_list.append(cur_id)
            self.tracking_info_dict[cur_id].last_detect_time = cur_time

        delete_id = []
        for h_id in self.human_id_list:
            if (cur_time - self.tracking_info_dict[h_id].last_detect_time) > 5.0:
                del self.tracking_info_dict[h_id]
                delete_id.append(h_id)
        for id in sorted(delete_id, reverse=True):
            self.human_id_list.remove(id)
            if id in self.tracking_info_dict.keys():
                del self.tracking_info_dict[id]

        return new_integrated_info, new_human_id_list

    def get_sep_id(self, integrated_info, human_id_list):
        sort_data = []
        priority_cnt = 0
        for i, info in enumerate(integrated_info):
            data = {}

            audio_on = False
            if (human_id_list[i] in self.current_audio_id):
                if self.audio_on_flg[human_id_list[i]]:
                    audio_on = True

            x = info.person.xyz[0]
            y = info.person.xyz[1]
            angle = math.atan2(y, x)
            distance = math.sqrt(x * x + y * y)
            if (distance <= self.priority_range * 1000  and
                angle >= self.priority_min_angle and
                angle <= self.priority_max_angle):
                priority_state = True
                priority_cnt += 1
            else:
                priority_state = False
            weight = self.range_weight * distance / 1000.0 + self.angle_weight * abs(angle) / np.pi + self.face_dir_weight * info.person.face_angle / np.pi
            data["area_flg"] = priority_state
            data["audio_flg"] = audio_on
            data["weight"] = -weight
            data["index"] = i
            data["human_id"] = human_id_list[i]
            sort_data.append(data)

        sorted_data = sorted(sort_data, key=lambda x: (x["area_flg"], x["audio_flg"], x["weight"]), reverse=True)

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
            if i >= sep_cnt:
                continue
            h_id = sorted_data[i]["human_id"]
            if self.tracking_info_dict[h_id].sep_id is not None:
                last_sep = self.tracking_info_dict[h_id].sep_id
                self.get_logger().debug("sep check: %d, %d, %d" % (h_id, last_sep, sorted_data[i]["sep_id"]))
                if last_sep == INVALID_VALUE: continue
                if (last_sep < self.prority_sep_num + id_start and 
                    last_sep != sorted_data[i]["sep_id"] and
                    last_sep <= self.prority_sep_num + 1):
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
            h_id = sorted_data[i + priority_cnt]["human_id"]
            if self.tracking_info_dict[h_id].sep_id is not None:
                last_sep = self.tracking_info_dict[h_id].sep_id
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
            self.tracking_info_dict[sorted_data[i]["human_id"]].sep_id = sorted_data[i]["sep_id"]

    def result_publisher(self, integrated_info, human_id_list):
        result_data = TrackedPersons()
        time_stamp = self.get_clock().now().to_msg()
        result_data.header.stamp = time_stamp
        for (info, h_id) in zip(integrated_info, human_id_list):
            person_data = TrackedPerson()
            person_data.time_stamp = time_stamp
            person_data.human_id = h_id
            person_data.sep_id = self.tracking_info_dict[h_id].sep_id
            pose = [info.person.xyz[0], info.person.xyz[1], info.person.xyz[2]]
            person_data.xyz = pose
            person_data.face_direction = info.person.face_direction
            result_data.persons.append(person_data)
        self.human_tracker_result_pub.publish(result_data)

    def marker_publisher(self, integrated_info, human_id_list):
        current_human_id = []
        time_stamp = self.get_clock().now().to_msg()
        for (info, h_id) in zip(integrated_info, human_id_list):
            pose = [info.person.xyz[0], info.person.xyz[1], info.person.xyz[2]]
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
            elif (not info.person.camera_info_exist):
                MarkerColor.LIDAR_ONLY.apply(marker)
            elif (info.person.lidar_info_exist):
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
                if (info.person.lidar_info_exist):
                    MarkerColor.TRANSPARENT.apply(marker_name)
                    marker_name.text = ""
                else:
                    MarkerColor.TEXT.apply(marker_name)
                    marker_name.text = info.person.name
            elif (self.rviz_view_text == ViewText.SEP_ID):
                MarkerColor.TEXT.apply(marker_name)
                marker_name.text = str(self.tracking_info_dict[h_id].sep_id)
            elif (self.rviz_view_text == ViewText.HUMAN_ID):
                MarkerColor.TEXT.apply(marker_name)
                marker_name.text = str(h_id)
            elif (self.rviz_view_text == ViewText.DEBUG):
                MarkerColor.TEXT.apply(marker_name)
                marker_name.text = str(h_id) + "," + str(self.tracking_info_dict[h_id].sep_id)

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

    def send_tcp(self, human_id_list):
        time = self.get_clock().now().seconds_nanoseconds()
        sec = float(time[0])
        msec = float(time[1]) * 1e-6
        send_msg = ""
        for h_id in human_id_list:
            info = self.tracking_info_dict[h_id]
            send_msg += build_tcp_record(sec, msec, h_id, info.pose, info.sep_id,
                                         info.class_id, info.instance_id, info.name)
        send_msg = send_msg.encode('shift_jis')

        for client in self.client_list:
            try:
                client.send(send_msg)
            except socket.error:
                self.get_logger().debug('close tcp connection')
                self.client_list.remove(client)
                client.close()
                continue

    def save_result_db(self, human_id_list):
        insert_list = []
        date_time = self.to_datetime(self.get_clock().now())
        for h_id in human_id_list:
            obj = {}
            obj["time"] = date_time
            obj["robot_name"] = self.robot_name
            obj["human_id"] = h_id
            obj["sep_id"] = self.tracking_info_dict[h_id].sep_id
            obj["class_id"] = self.tracking_info_dict[h_id].class_id
            obj["instance_id"] = self.tracking_info_dict[h_id].instance_id
            obj["person_name"] = self.tracking_info_dict[h_id].name
            obj["pose"] = self.tracking_info_dict[h_id].pose
            insert_list.append(obj)
        if len(insert_list) != 0:
            self.human_tracker_collection.insert_many(insert_list)

    def to_datetime(self, t):
        s, n = t.seconds_nanoseconds()
        sn = s + n / (10 ** 9)
        dt = datetime.fromtimestamp(sn, tz=timezone(timedelta(hours=9)))
        return dt.strftime("%Y/%m/%d %H:%M:%S.%f")


def main():
    rclpy.init()
    node = HumanTrackerIntegration()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
