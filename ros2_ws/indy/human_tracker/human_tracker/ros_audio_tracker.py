import socket
import time
import threading

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from human_tracker_msgs.msg import AudioInfo, AudioInfoList
from .tf_transfomer import TFTransformer

from pyindy.param_manager import ParamManager

class RosAudioTracker(Node):
    def __init__(self):
        super().__init__('ros_audio_tracker_node')

        self.declare_parameter("mongo_uri", "")
        mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.declare_parameter("mongo_port", 1)
        mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        
        self.declare_parameter("audio_ip", "")
        self.tcp_server_ip = self.get_parameter_or("audio_ip", "").get_parameter_value().string_value
        self.declare_parameter("audio_port", 1)
        self.tcp_server_port = self.get_parameter_or("audio_port", 1).get_parameter_value().integer_value

        if self.tcp_server_ip == "" and self.tcp_server_port == 1:
            pm = ParamManager(mongo_uri, mongo_port)
            params = pm.get_param("ros_audio_tracker")
            if params is not None:
                if "audio_ip" in params:
                    self.tcp_server_ip = params["audio_ip"]
                if "audio_port" in params:
                    self.tcp_server_port = params["audio_port"]

        self.declare_parameter('client_number', 10)
        self.declare_parameter('msg_size', 4096)
        self.declare_parameter('socket_length', 18)
        self.declare_parameter('need_transform', False)

        self.client_number = self.get_parameter('client_number').get_parameter_value().integer_value
        self.msg_size = self.get_parameter('msg_size').get_parameter_value().integer_value
        self.socket_length = self.get_parameter('socket_length').get_parameter_value().integer_value
        self.need_transform = self.get_parameter('need_transform').get_parameter_value().bool_value

        if self.need_transform:
            self.transformer = TFTransformer(self)

            self.declare_parameter('robot_link', "")
            self.declare_parameter('camera_link', "")
            self.robot_link = self.get_parameter('robot_link').get_parameter_value().string_value
            self.camera_link = self.get_parameter('camera_link').get_parameter_value().string_value

        self.audio_info_pub = self.create_publisher(AudioInfoList, "human_tracker/audio_info", 10)

        thread_connect_tcp = threading.Thread(target=self.connect_tcp)
        thread_connect_tcp.setDaemon(True)
        thread_connect_tcp.start()

    def connect_tcp(self):
        self.get_logger().info(f"Try to connect to audio server: {self.tcp_server_ip}:{self.tcp_server_port}")
        tcp_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        connect_wait_time = 1.0
        while rclpy.ok():
            try:
                tcp_client.connect((self.tcp_server_ip, self.tcp_server_port))
                self.get_logger().info(f"Success to connect to audio server: {self.tcp_server_ip}:{self.tcp_server_port}")
                break
            except socket.error:
                time.sleep(connect_wait_time)

        self.accept_loop(tcp_client)

    def accept_loop(self, client):
        pub_msg = AudioInfoList()
        while rclpy.ok():
            data_all = []
            pub_msg.info = []
            try:
                recv_msg = client.recv(self.msg_size)
                if not recv_msg:
                    self.reconnect_tcp(client)
                    break
            except:
                self.reconnect_tcp(client)
                break
            try:
                recv_msg = recv_msg.decode("sjis")
            except:
                continue
            data_list = recv_msg.split("\n")
            pub_msg.header.stamp = self.get_clock().now().to_msg()
            for audio_data in data_list:
                audio_info = AudioInfo()
                if (audio_data == ""):
                    continue
                data = [d for d in audio_data.split(",")]
                data_all.extend(data)
                if (len(data_all) < self.socket_length):
                    continue
                elif (len(data_all) == self.socket_length):
                    if (data_all[0] =="" or
                        data_all[1] =="" or
                        data_all[2] =="" or
                        data_all[3] =="" or
                        data_all[4] =="" or
                        data_all[5] =="" or
                        data_all[6] =="" or
                        data_all[7] =="" or
                        data_all[8] =="" or
                        data_all[9] =="" or
                        data_all[10] =="" or
                        data_all[11] ==""):
                        continue
                    if int(data_all[6]) == -10000:
                        data_all[6] = 1500
                    pose = [int(data_all[4])/1000.0, int(data_all[5])/1000.0, 0.0]
                    if self.need_transform:
                        pose = self.transformer.transform_position(pose, self.camera_link, self.robot_link)
                        pose = [-pose[1], pose[0], pose[2]]
                    audio_info.timestamp_sec = int(data_all[0])
                    audio_info.timestamp_msec = int(data_all[1])
                    audio_info.human_id = int(data_all[2])
                    audio_info.vad = int(data_all[3])
                    audio_info.x = round(pose[0]*1000)
                    audio_info.y = round(pose[1]*1000)
                    audio_info.z = int(data_all[6])
                    audio_info.power = int(data_all[7])
                    audio_info.sep_id = int(data_all[8])
                    audio_info.port = int(data_all[9])
                    audio_info.class_id = int(data_all[10])
                    audio_info.instance_id = int(data_all[11])
                    audio_info.person_name = data_all[12]
                    pub_msg.info.append(audio_info)
                    data_all = []
                else:
                    self.get_logger().debug("audio_info size is wrong: %d" % len(data))
                    data_all = []
                    continue
            self.audio_info_pub.publish(pub_msg)
        return

    def reconnect_tcp(self, client):
        self.get_logger().warn('Close connection to audio server')
        client.close()
        thread_connect_tcp = threading.Thread(target=self.connect_tcp)
        thread_connect_tcp.setDaemon(True)
        thread_connect_tcp.start()

def main():
    rclpy.init()
    node = RosAudioTracker()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
