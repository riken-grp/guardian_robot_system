import socket
import struct
import threading

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import Int16MultiArray

from pyindy.param_manager import ParamManager

class MicInfo(Node):
    def __init__(self):
        super().__init__('mic_info_node')

        self.declare_parameter("mongo_uri", "")
        mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.declare_parameter("mongo_port", 0)
        mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value

        pm = ParamManager(mongo_uri, mongo_port)
        params = pm.get_param("ros_audio_tracker")
        if params is not None:
            if "audio_ip" in params:
                self.tcp_server_ip = params["audio_ip"]
            else:
                self.tcp_server_ip = ""

        self.declare_parameter('receive_port', 5661)
        self.declare_parameter('client_number', 10)
        self.declare_parameter('msg_size', 8192)

        self.tcp_server_port = self.get_parameter('receive_port').get_parameter_value().integer_value
        self.client_number = self.get_parameter('client_number').get_parameter_value().integer_value
        self.msg_size = self.get_parameter('msg_size').get_parameter_value().integer_value

        self.mic_info_pub = self.create_publisher(Int16MultiArray, "audio", 10)

        self.accept_tcp()

    def accept_tcp(self):
        self.get_logger().debug("accept_tcp start")
        tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind(("", self.tcp_server_port))
        tcp_server.listen(self.client_number)
        while rclpy.ok():
            client, address = tcp_server.accept()
            self.get_logger().debug('connected')
            thread_accept_tcp = threading.Thread(target=self.recv_loop, args=(client, ))
            thread_accept_tcp.setDaemon(True)
            thread_accept_tcp.start()

    def recv_loop(self, client):
        pub_msg = Int16MultiArray()
        while rclpy.ok():
            try:
                recv_msg = client.recv(self.msg_size)
                if not recv_msg:
                    break
                if len(recv_msg) % 2 != 0:
                    break
            except socket.error:
                break
            for i in range(0, len(recv_msg), 2):
                short_value = struct.unpack("<h", recv_msg[i:i+2])[0]
                pub_msg.data.append(short_value)
            self.mic_info_pub.publish(pub_msg)
        return


def main():
    rclpy.init()
    node = MicInfo()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
