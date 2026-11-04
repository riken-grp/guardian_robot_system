import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from time import sleep

def main():
    # ROS2の初期化
    rclpy.init()

    # ノード作成
    node = Node('body_test_pub')

    # パブリッシャー作成
    publisher = node.create_publisher(JointState, '/test/motor_control/control_position', 10)

    joint_name = ['neck_yaw_joint', 'neck_pitch_joint', 'body_pitch_joint']

    # シーケンスに沿ってパブリッシュするJointStateデータを定義
    joint_state_sequence = [
        {"name": joint_name, "position": [0.0, 0.0, 0.0], "velocity": [0.3, 0.3, 0.3], "effort": []},       # default_posture
        {"name": joint_name, "position": [-1.0, 0.0, -0.3], "velocity": [0.3, 0.3, 0.3], "effort": []},       # look_right_raise_hand
        {"name": joint_name, "position": [0.0, -0.3, 0.0], "velocity": [0.3, 0.3, 0.3], "effort": []},      # surprise_pose
        {"name": joint_name, "position": [0.0, 0.0, 0.0], "velocity": [0.3, 0.3, 0.3], "effort": []},       # default_posture
    ]

    try:
        for state in joint_state_sequence:
            # JointStateメッセージ作成
            joint_state_msg = JointState()
            joint_state_msg.header.stamp = node.get_clock().now().to_msg()
            joint_state_msg.name = state["name"]
            joint_state_msg.position = state["position"]
            joint_state_msg.velocity = state["velocity"]
            joint_state_msg.effort = state["effort"]

            # メッセージをパブリッシュ
            publisher.publish(joint_state_msg)
            print(f"Published: {joint_state_msg}")

            # 次のステップに進む前に少し待つ
            sleep(8.0)

    except KeyboardInterrupt:
        print("おわり")

    # ノードの破棄とシャットダウン
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
