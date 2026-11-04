import os
import sys
import threading
from time import sleep
import rclpy
from scipy.spatial.transform import Rotation
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.clock import Clock
from common_msgs.msg import StringStamped                       # Common msg
from std_msgs.msg import String                       
from std_msgs.msg import Empty                       
import logging
import traceback
import inspect
import serial


"""
eye_display (for ROS2)
"""


class EyeDisplay(Node):

    timer_times = 0

    def __init__(self):
        super().__init__(node_name='eye_display_node')
        self.my_nodename = str(self.get_name())
        self.my_namespace = str(self.get_namespace())

        ####################
        # Get 'ROS Params' #
        ####################
        self.declare_parameter(name='serial_port', value='/dev/ttyUSB0')
        self.declare_parameter(name='node_id', value='not_set')
        self.declare_parameter(name='default_target_file', value='')
        self.declare_parameter(name='report_hz', value=100)
        self.declare_parameter(name='baudrate', value=115200)
        self.serial_port = self.get_parameter(name='serial_port').get_parameter_value().string_value
        self.node_id = self.get_parameter(name='node_id').get_parameter_value().string_value
        default_target_file = self.get_parameter(name='default_target_file').get_parameter_value().string_value
        self.report_hz = self.get_parameter(name='report_hz').get_parameter_value().integer_value
        self.baudrate = self.get_parameter(name='baudrate').get_parameter_value().integer_value

        self.get_logger().debug(message=f'({self.node_id}): {inspect.stack()[0].function} in')
        self.get_logger().info(message=f'({self.node_id}): {sys.argv}')

        ##################################################
        # Create connection                              #
        ##################################################
        try:
            self.get_logger().info(message=f'({self.node_id}): open serial port [{self.serial_port}]')
            self.ser = serial.Serial(self.serial_port, self.baudrate)
        except Exception:
            self.get_logger().error(message=f'({self.node_id}): open serial port error.')
            exc, mes, tra = sys.exc_info()
            self.get_logger().error(message=f'({self.node_id}): {exc}')
            self.get_logger().error(message=f'({self.node_id}): {mes}')
            self.get_logger().error(message=f'({self.node_id}): {traceback.print_tb(tra)}')

        self.get_logger().debug(message=f'({self.node_id}): Register Timer callbacks')
        ##############################
        # Register 'Timer' callbacks #
        ##############################
        timer_period = 1 / self.report_hz   # Hz -> sec
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().debug(message=f'({self.node_id}): Register Topic publishers')

        ###############################
        # Register 'Topic' publishers #
        ###############################
        self.file_pub = self.create_publisher(String, f'{self.my_nodename}/{self.node_id}/displayed_file', 1)
        self.log_pub = self.create_publisher(StringStamped, f'{self.my_nodename}/{self.node_id}/butukusa', 1)

        self.get_logger().debug(message=f'({self.node_id}): Register Topic callbacks')

        ##############################
        # Register 'Topic' callbacks #
        ##############################
        self.create_subscription(msg_type=String, topic=f'{self.my_nodename}/{self.node_id}/target_file',
                                 callback=self.target_file_callback, qos_profile=1)
        self.create_subscription(msg_type=Empty, topic=f'{self.my_nodename}/{self.node_id}/clear_display',
                                 callback=self.clear_display_callback, qos_profile=1)

        self.pub_count = 0
        
        file_path = os.path.join('/', default_target_file)
        self.ser.write(str(file_path+'\n').encode('utf-8'))
        self.target_file_name = default_target_file

    def debug_report(self, data):
        self.get_logger().debug(message=f'({self.node_id}): {data}')
        # self.report_pub(data)

    def info_report(self, data):
        self.get_logger().info(message=f'({self.node_id}): {data}')
        self.report_pub(data)

    def error_report(self, data):
        self.get_logger().error(message=f'({self.node_id}): {data}')
        self.report_pub(data)

    def warn_report(self, data):
        self.get_logger().warn(message=f'({self.node_id}): {data}')
        self.report_pub(data)

    def report_pub(self, data):
        msg = StringStamped()
        msg.header.stamp = Clock().now().to_msg()
        msg.header.frame_id = '{0}'.format(self.pub_count)
        msg.data = f'({self.node_id}): {data}'
        self.get_logger().debug(message=f'({self.node_id}): publish /butukusa')
        self.log_pub.publish(msg=msg)
        self.pub_count += 1

    ###################
    # Timer callbacks #
    ###################
    def timer_callback(self):
        self.repo = f'{inspect.stack()[0].function} in'
        # self.debug_report(self.repo)
        msg = String()
        msg.data = str(self.target_file_name)
        self.file_pub.publish(msg)
        self.timer_times += 1

    ###################
    # Topic callbacks #
    ###################
    def target_file_callback(self, msg):
        self.target_file_name = msg.data
        self.file_path = os.path.join('/', self.target_file_name)
        self.repo = f'receive target file : {self.file_path}'
        self.get_logger().info(message=f'({self.node_id}): {self.repo}')
        self.info_report(self.repo)
        self.ser.write(str(self.file_path+'\n').encode('utf-8'))
        self.get_logger().info(str(self.file_path+"\n'"))

    def clear_display_callback(self, msg):
        self.repo = f'receive clear display'
        self.get_logger().info(message=f'({self.node_id}): {self.repo}')
        self.info_report(self.repo)
        self.ser.write("/\n'".encode('utf-8'))


def main(args=None):
    rclpy.init(args=args)
    try:
        logging.getLogger().info(msg=f'{inspect.stack()[0].function}: node start')
        eye_node = EyeDisplay()
        thread_exe = SingleThreadedExecutor()
        thread_exe.add_node(node=eye_node)
        thread_exe.spin()
    except Exception:
        logging.getLogger().error(f'{inspect.stack()[0].function}: Caught exception')
        traceback.print_exc()
        eye_node.ser.close()
    finally:
        logging.getLogger().debug(f'{inspect.stack()[0].function}: process end')
        eye_node.destroy_node()
        rclpy.shutdown()
        sys.exit


if __name__ == '__main__':
    main()
