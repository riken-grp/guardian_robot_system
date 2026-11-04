import rclpy
from sensor_msgs.msg import JointState
from time import sleep
import os

def main():
    robot_name = os.getenv("ROBOT_NAME")
    if robot_name is None:
        print ("error: failed to get robot name")
        robot_name = ""

    # ROS2の初期化
    rclpy.init()

    # ノード作成
    node = rclpy.create_node('right_arm_test_pub')

    # パブリッシャー作成
    publisher = node.create_publisher(JointState, '/'+robot_name+'/right_arm/goal_joints', 10)

    joint_name = ['bracket_arm_a_joint', 'bracket_arm_b_joint', 'bracket_arm_c_joint', 'bracket_arm_d_joint']

    # シーケンスに沿ってパブリッシュするJointStateデータを定義
    joint_state_sequence = [
        {"name": joint_name, "position": [0.0, 1.5, 0.0, 0.0], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # default_posture
        {"name": joint_name, "position": [-1.0, 1.2, 0.0, -1.0], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # look_right_raise_hand
        {"name": joint_name, "position": [-1.5, 1.2, 1.0, -1.5], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # surprise_pose
        {"name": joint_name, "position": [0.0, 1.5, 0.0, 0.0], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # default_posture
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
            sleep(10.0)

    except KeyboardInterrupt:
        print("おわり")

    # ノードの破棄とシャットダウン
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
