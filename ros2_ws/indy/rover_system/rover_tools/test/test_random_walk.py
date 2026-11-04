import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from common_msgs.msg import PoseAngle
from time import sleep
import os
import random
import math

def main():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        return

    # ROS2の初期化
    rclpy.init()

    # ノード作成
    node = Node('ramdom_walk_test')

    # パブリッシャー作成
    move_pub = node.create_publisher(Float32, robot_name+'/rover/move_straight', 10)
    rot_pub = node.create_publisher(Float32, robot_name+'/rover/rotate', 10)
    nav_pub = node.create_publisher(PoseAngle, robot_name+'/rover/navigate', 10)

    # 移動距離を定義
    move_distance = 5.0

    pub_msg = Float32()    
    while rclpy.ok():
        # 直進
        pub_msg.data = move_distance
        move_pub.publish(pub_msg)
        node.get_logger().info(f"move_straight: {move_distance} [m]")
        
        sleep(10.0)
        
        # 回転
        rotate_angle = 2 * math.pi * (random.random() - 0.5)
        pub_msg.data = rotate_angle
        rot_pub.publish(pub_msg)
        node.get_logger().info(f"rotate: {rotate_angle} [rad.]")

        sleep(5.0)


    # ノードの破棄
    node.destroy_node()

if __name__ == '__main__':
    main()
