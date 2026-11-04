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
    node = rclpy.create_node('arms_move_test_pub')

    # パブリッシャー作成
    right_publisher = node.create_publisher(JointState, '/'+robot_name+'/right_arm/goal_joints', 10)
    left_publisher = node.create_publisher(JointState, '/'+robot_name+'/left_arm/goal_joints', 10)

    joint_name = ['bracket_arm_a_joint', 'bracket_arm_b_joint', 'bracket_arm_c_joint', 'bracket_arm_d_joint']

    # シーケンスに沿ってパブリッシュするJointStateデータを定義
    joint_state_sequence = [
        {"name": joint_name, "position": [0.0, -1.4, 1.3, -0.3], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # default_posture
        {"name": joint_name, "position": [-1.5, -1.4, 1.0, -1.5], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # surprise_pose
        {"name": joint_name, "position": [0.0, -1.4, 1.3, -0.3], "velocity": [0.3, 0.3, 0.3, 0.3], "effort": []},       # default_posture
    ]

    try:
        for state in joint_state_sequence:
            # JointStateメッセージ作成
            right_joint_state_msg = JointState()
            right_joint_state_msg.header.stamp = node.get_clock().now().to_msg()
            right_joint_state_msg.name = state["name"]
            right_joint_state_msg.position = state["position"]
            right_joint_state_msg.velocity = state["velocity"]
            right_joint_state_msg.effort = state["effort"]

            left_joint_state_msg = JointState()
            left_joint_state_msg.header.stamp = node.get_clock().now().to_msg()
            left_joint_state_msg.name = state["name"]
            left_joint_state_msg.position = [-p for p in state["position"]]
            left_joint_state_msg.velocity = state["velocity"]
            left_joint_state_msg.effort = state["effort"]

            # メッセージをパブリッシュ
            right_publisher.publish(right_joint_state_msg)
            node.get_logger().info(f"Published right: {right_joint_state_msg}")
            left_publisher.publish(left_joint_state_msg)
            node.get_logger().info(f"Published left: {left_joint_state_msg}")

            # 次のステップに進む前に少し待つ
            sleep(10.0)

    except KeyboardInterrupt:
        node.get_logger().info("end")

    # ノードの破棄とシャットダウン
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
