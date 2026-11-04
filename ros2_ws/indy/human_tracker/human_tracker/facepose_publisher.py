import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy import qos

import math
import numpy as np

import tf2_ros
import tf2_geometry_msgs

from human_tracker_msgs.msg import FacePoses, FacePose
from human_tracker_msgs.msg import TrackedPersons
from tf2_geometry_msgs import PointStamped, PoseStamped, Vector3Stamped,TransformStamped

from .tf_transfomer import TFTransformer

class FacePosePublisher(Node):
    def __init__(self):
        super().__init__('facepose_publisher_node')

        name_space = self.get_namespace()

        self.declare_parameter('world_frame', "")
        self.declare_parameter('robot_frame', "")

        self.world_frame = self.get_parameter('world_frame').get_parameter_value().string_value
        robot_frame = self.get_parameter('robot_frame').get_parameter_value().string_value
        self.robot_frame = name_space + "_" + robot_frame

        self.transformer = TFTransformer(self)

        self.world_facepose_pub = self.create_publisher(FacePoses, "human_tracker/facepose_on_world", 10)

        scan_qos = qos.QoSProfile(depth=10)
        scan_qos.reliability = qos.QoSReliabilityPolicy.BEST_EFFORT 
        self.human_info_sub = self.create_subscription(TrackedPersons, "human_tracker/recognition_result", self.human_info_cb, scan_qos)

    def human_info_cb(self, human_info):
        robot_face_poses = FacePoses()
        world_face_poses = FacePoses()
        robot_face_poses.header = human_info.header
        world_face_poses.header = human_info.header
        for info in human_info.persons:
            pose_on_robot = info.xyz
            dir_on_robot = info.face_direction
            if (len(dir_on_robot) != 3):
                continue

            pose_on_world = self.transformer.transform_position(pose_on_robot, self.robot_frame, self.world_frame)
            dir_on_world = self.transformer.transform_angle(dir_on_robot, self.robot_frame, self.world_frame)
            if (pose_on_world != pose_on_robot or dir_on_world != dir_on_world):
                world_face_pose = FacePose()
                world_face_pose.human_id = info.human_id
                world_face_pose.xyz = pose_on_world
                world_face_pose.direction = dir_on_world
                world_face_poses.poses.append(world_face_pose)
                self.world_facepose_pub.publish(world_face_poses)

def main():
    rclpy.init()
    node = FacePosePublisher()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()