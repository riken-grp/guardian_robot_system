import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
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
    node = Node('rover_test_pub')

    # パブリッシャー作成
    move_pub = node.create_publisher(Float32, robot_name+'/rover/move_straight', 10)
    rot_pub = node.create_publisher(Float32, robot_name+'/rover/rotate', 10)
    nav_pub = node.create_publisher(PoseAngle, robot_name+'/rover/navigate', 10)

    # 移動距離を定義
    move_sequence = [
        {"data": 0.2},
        {"data": -0.2},
        {"data": 0.5},
        {"data": -0.5}
    ]
    for state in move_sequence:
        pub_msg = Float32()
        pub_msg.data = state["data"]
        move_pub.publish(pub_msg)
        print(f"Published: {pub_msg}")
        sleep(4.0)
    
    # 回転角度を定義
    rotate_sequence = [
        {"data": 0.3},
        {"data": -0.3},
        {"data": 1.0},
        {"data": -1.0}
    ]
    for seq in rotate_sequence:
        pub_msg = Float32()
        pub_msg.data = seq["data"]
        rot_pub.publish(pub_msg)
        print(f"Published: {pub_msg}")
        sleep(4.0)
    
    # 目的地を定義
    #nav_sequence = [
    #    {"x": 0.3, "y": 0.5, "angle": 1.57},
    #    {"x": 0.3, "y": 0.5, "angle": 3.14},
    #    {"x": 0.3, "y": 0.5, "angle": 0.0}
    #]
    #for seq in nav_sequence:
    #    pub_msg = PoseAngle()
    #    pub_msg.position.x = seq["x"]
    #    pub_msg.position.x = seq["y"]
    #    pub_msg.angle = seq["angle"]
    #    nav_pub.publish(pub_msg)
    #    print(f"Published: {pub_msg}")
    #    sleep(10.0)

    # ノードの破棄
    node.destroy_node()

if __name__ == '__main__':
    main()
