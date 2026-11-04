import numpy as np

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster

from pyindy.param_manager import ParamManager

def quaternion_from_euler(ai, aj, ak):
    ai /= 2.0
    aj /= 2.0
    ak /= 2.0
    ci = np.cos(ai)
    si = np.sin(ai)
    cj = np.cos(aj)
    sj = np.sin(aj)
    ck = np.cos(ak)
    sk = np.sin(ak)
    cc = ci*ck
    cs = ci*sk
    sc = si*ck
    ss = si*sk

    q = np.empty((4, ))
    q[0] = cj*sc - sj*cs
    q[1] = cj*ss + sj*cc
    q[2] = cj*cs - sj*sc
    q[3] = cj*cc + sj*ss

    return q


class SensorTfPublisher(Node):
    def __init__(self):
        super().__init__('static_sensor_tf2_broadcaster')

        self.my_namespace = str(self.get_namespace()).strip('/')

        self.declare_parameter("mongo_uri", "")
        mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.declare_parameter("mongo_port", 1)
        mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value

        self.tf_static_broadcaster = {}
        
        params = self.get_tf_param(mongo_uri, mongo_port)
        self.publish_tf(params)

    def get_tf_param(self, mongo_uri, mongo_port):
        param_manager = ParamManager(mongo_uri, mongo_port)
        params = param_manager.get_param("sensor_tf")
        return params

    def publish_tf(self, params):
        if params:
            keys = params.keys()
        else:
            self.get_logger().info("No data in sensor_tf param")
            return

        for key in keys:
            self.tf_static_broadcaster[key] = StaticTransformBroadcaster(self)
            transformation = []
            parent_frame = self.my_namespace + "_" + params[key]["parent_frame"]
            child_frame = self.my_namespace + "_" + params[key]["child_frame"]
            transformation.append(parent_frame)
            transformation.append(child_frame)
            transformation.append(params[key]["pos"][0])
            transformation.append(params[key]["pos"][1])
            transformation.append(params[key]["pos"][2])
            transformation.append(params[key]["angle"][0])
            transformation.append(params[key]["angle"][1])
            transformation.append(params[key]["angle"][2])
            self.make_transforms(key, transformation)

    def make_transforms(self, key, transformation):
        t = TransformStamped()

        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = transformation[0]
        t.child_frame_id = transformation[1]

        t.transform.translation.x = float(transformation[2])
        t.transform.translation.y = float(transformation[3])
        t.transform.translation.z = float(transformation[4])
        quat = quaternion_from_euler(
            float(transformation[5]), float(transformation[6]), float(transformation[7]))
        t.transform.rotation.x = quat[0]
        t.transform.rotation.y = quat[1]
        t.transform.rotation.z = quat[2]
        t.transform.rotation.w = quat[3]

        self.tf_static_broadcaster[key].sendTransform(t)


def main():
    rclpy.init()
    node = SensorTfPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    rclpy.shutdown()
