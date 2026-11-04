import rclpy
from rclpy.node import Node
from std_msgs.msg import String
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
    node = Node('eye_test_pub')

    # パブリッシャー作成
    right_eye_pub = node.create_publisher(String, robot_name+'/eye_control/right/target_file', 10)
    left_eye_pub = node.create_publisher(String, robot_name+'/eye_control/left/target_file', 10)

    # 移動距離を定義
    eye_sequence = [
        {"right": "neutral2.jpg", "left": "neutral2.jpg"},
        {"right": "sadR.jpg", "left": "sadL.jpg"},
        {"right": "smileR.jpg", "left": "smileL.jpg"},
        {"right": "neutral1.jpg", "left": "neutral1.jpg"}
    ]
    for state in eye_sequence:
        right_pub_msg = String()
        right_pub_msg.data = state["right"]
        left_pub_msg = String()
        left_pub_msg.data = state["left"]
        right_eye_pub.publish(right_pub_msg)
        left_eye_pub.publish(left_pub_msg)
        print(f"Published: right:{right_pub_msg}, left:{left_pub_msg}")
        sleep(3.0)

    # ノードの破棄
    node.destroy_node()

if __name__ == '__main__':
    main()
