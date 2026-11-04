import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from sensor_msgs.msg import JointState
from common_msgs.msg import PoseAngle
from time import sleep
import os

def main():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    # ROS2の初期化
    rclpy.init()

    # ノード作成
    node = Node('scene_pub')

    # パブリッシャー作成
    move_pub = node.create_publisher(Float32, robot_name+'/rover/move_straight', 10)
    rot_pub = node.create_publisher(Float32, robot_name+'/rover/rotate', 10)
    right_arm_pub = node.create_publisher(JointState, robot_name+'/right_arm/goal_joints', 10)
    left_arm_pub = node.create_publisher(JointState, robot_name+'/left_arm/goal_joints', 10)
    
    sleep(0.1)

    joint_state_msg = JointState()
    joint_state_msg.position = [0.0,-1.4,1.3,-0.3]
    right_arm_pub.publish(joint_state_msg)

    joint_state_msg = JointState()
    joint_state_msg.position = [0.0,1.4,-1.3,0.3]
    left_arm_pub.publish(joint_state_msg)

    input("Move straight 1.1m")

    pub_msg = Float32()
    pub_msg.data = 1.1
    move_pub.publish(pub_msg)
    print(f"Published: {pub_msg}")


    input("Right hand over")

    joint_state_msg = JointState()
    joint_state_msg.header.stamp = node.get_clock().now().to_msg()
    joint_state_msg.position = [1.2,-1.2,2.87,0.0]
    right_arm_pub.publish(joint_state_msg)
    print(f"Published: {joint_state_msg}")


    input("Right hand down")

    joint_state_msg = JointState()
    joint_state_msg.header.stamp = node.get_clock().now().to_msg()
    joint_state_msg.position = [0.0,-1.4,1.3,-0.3]
    right_arm_pub.publish(joint_state_msg)
    print(f"Published: {joint_state_msg}")


    input("Rotate to TV")
    
    pub_msg = Float32()
    pub_msg.data = -2.0
    rot_pub.publish(pub_msg)
    print(f"Published: {pub_msg}")

    # ノードの破棄
    node.destroy_node()

if __name__ == '__main__':
    main()
