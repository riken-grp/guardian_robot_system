import os
import math
import json
import time
import threading
import numpy as np

import rclpy
from rclpy.time import Time
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy import qos
import rclpy.time
import tf2_ros

from std_msgs.msg import Float32, UInt8, Empty
from geometry_msgs.msg import PoseStamped, Twist, Quaternion, PoseWithCovarianceStamped
from common_msgs.msg import StringStamped, PoseAngle

from nav2_msgs.action import NavigateToPose

class RoverWrapper(Node):
    def __init__(self):
        super().__init__('rover_wrapper_node')

        self.declare_parameter('report_rate', 0.1)
        self.declare_parameter('rotate_speed', 0.1)
        self.declare_parameter('move_speed', 0.1)
        self.declare_parameter('motor_release_time', 10.0)

        timer_period = self.get_parameter('report_rate').get_parameter_value().double_value
        self.rotate_speed = self.get_parameter('rotate_speed').get_parameter_value().double_value
        self.move_speed = self.get_parameter('move_speed').get_parameter_value().double_value
        self.motor_release_limit = self.get_parameter('motor_release_time').get_parameter_value().double_value
        
        self.goal_handle = None
        self.continue_flg = True

        self.robot_name = os.getenv("ROBOT_NAME")
        if self.robot_name is None:
            self.get_logger().error("failed to get robot name")
            return

        self.rover_state = {}
        self.rover_pose = PoseStamped()
        self.rover_state["mode"] = "idle"
        self.rover_state["destination"] = [0,0]
        self.rover_state["arrived"] = True
        self.rover_state["error_code"] = -1
        self.rover_state["error_description"] = ""
        self.rover_state["error_source"] = ""  # "nav": nav2の失敗結果 / "firm": ファームウェア異常

        self.motor_lock = False
        self.motor_release_time = 0.0
        self.arm_disabled_by_bumper = False
        
        rover_pose_dir = os.path.expanduser("~/config")
        self.rover_pose_path = os.path.expanduser("~/config/rover_pose.txt")
        if not os.path.exists(rover_pose_dir):
            os.makedirs(rover_pose_dir)
            print(f"'{rover_pose_dir}' を作成しました。")
        
        if not os.path.exists(self.rover_pose_path):
            with open(self.rover_pose_path, 'w') as file:
                file.write(','.join(map(str, [0.0,0.0,0.0])))
            print(f"ファイル '{self.rover_pose_path}' を作成しました。")

        self.tf_buffer = tf2_ros.buffer.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        
        stop_cb_group = MutuallyExclusiveCallbackGroup()
        subscriber_cb_group = MutuallyExclusiveCallbackGroup()
        timer_cb_group = MutuallyExclusiveCallbackGroup()

        self.pose_pub = self.create_publisher(PoseStamped, "rover/pose", 10)
        self.butukusa_pub = self.create_publisher(StringStamped, "rover/butukusa", 10)
        self.cmd_vel_pub = self.create_publisher(Twist, 'rover/cmd_vel', 10)
        self.ini_pose_pub = self.create_publisher(PoseWithCovarianceStamped, 'rover/initialpose', 10)
        self.bumper_clear_pub = self.create_publisher(UInt8, 'rover/bumper_clear', 10)
        self.motor_release_pub = self.create_publisher(UInt8, 'rover/motor_release', 10)
        self.right_arm_disable_pub = self.create_publisher(Empty, 'right_arm/disable', 10)
        self.left_arm_disable_pub = self.create_publisher(Empty, 'left_arm/disable', 10)
        self.right_arm_enable_pub = self.create_publisher(Empty, 'right_arm/enable', 10)
        self.left_arm_enable_pub = self.create_publisher(Empty, 'left_arm/enable', 10)

        self.rotate_sub = self.create_subscription(Float32, 'rover/rotate', self.rotate_cb, 10, callback_group=subscriber_cb_group)
        self.move_sub = self.create_subscription(Float32, 'rover/move_straight', self.move_cb, 10, callback_group=subscriber_cb_group)
        self.navigate_sub = self.create_subscription(PoseAngle, 'rover/navigate', self.navigate_cb, 10, callback_group=subscriber_cb_group)
        self.stop_sub = self.create_subscription(Empty, 'rover/stop', self.stop_cb, 10, callback_group=stop_cb_group)
        self.ini_pose_sub = self.create_subscription(PoseAngle, "rover/set_initialpose", self.ini_pose_cb, 10, callback_group=subscriber_cb_group)
        self.bumper_state_sub = self.create_subscription(UInt8, "rover/bumper", self.bumper_state_cb, 10, callback_group=subscriber_cb_group)

        self.firm_state_sub = self.create_subscription(UInt8, "rover/firm_state", self.firm_cb, qos.qos_profile_sensor_data, callback_group=subscriber_cb_group)

        self.pose_action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self.timer = self.create_timer(timer_period, self.timer_callback, callback_group=timer_cb_group)

    def move_cb(self, msg):
        self.bumper_release()
        self.continue_flg = True
        self.clear_nav_error()

        target_dist = msg.data
        move_time = (abs(target_dist) / self.move_speed -1) * 1e+9
        if move_time <= 0:
            move_speed = target_dist
        else:
            move_speed = self.move_speed * target_dist / abs(target_dist)

        send_msg = Twist()
        send_msg.linear.x = move_speed

        start_time = self.get_clock().now().nanoseconds
        while rclpy.ok() and self.continue_flg:
            self.cmd_vel_pub.publish(send_msg)
            time_from_start = self.get_clock().now().nanoseconds - start_time
            if move_time <= time_from_start:
                break
            time.sleep(0.1)

    def rotate_cb(self, msg):
        self.bumper_release()
        self.continue_flg = True
        self.clear_nav_error()

        target_angle = msg.data
        rotate_time = (abs(target_angle) / self.rotate_speed -1) * 1e+9
        if rotate_time <= 0:
            rotate_speed = target_angle
        else:
            rotate_speed = self.rotate_speed * target_angle / abs(target_angle)

        send_msg = Twist()
        send_msg.angular.z = rotate_speed

        start_time = self.get_clock().now().nanoseconds
        while rclpy.ok() and self.continue_flg:
            self.cmd_vel_pub.publish(send_msg)
            time_from_start = self.get_clock().now().nanoseconds - start_time
            if rotate_time <= time_from_start:
                break
            time.sleep(0.1)

    def navigate_cb(self, msg):
        self.bumper_release()
        self.continue_flg = True
        self.clear_nav_error()  # errorからの復帰（次のナビゲーション開始時にクリア）
        self.rover_state["arrived"] = False
        self.rover_state["destination"] = [msg.position.x, msg.position.y]

        target_pose = PoseStamped()
        target_pose.header.frame_id = "map"
        target_pose.pose.position = msg.position
        target_pose.pose.orientation = self.quaternion_from_euler(0, 0, msg.angle)

        future = self.send_goal(target_pose)
        future.add_done_callback(self.goal_response_callback)

    def stop_cb(self, msg):
        self.get_logger().debug("cancel in")
        self.continue_flg = False
        if self.goal_handle:
            future = self.goal_handle.cancel_goal_async()
            self.get_logger().debug("cancel action")

    def ini_pose_cb(self, msg):
        initial_pose = PoseWithCovarianceStamped()
        initial_pose.header.frame_id = "map"
        initial_pose.pose.pose.position = msg.position
        initial_pose.pose.pose.orientation = self.quaternion_from_euler(0, 0, msg.angle)
        self.ini_pose_pub.publish(initial_pose)

    def firm_cb(self, msg):
        status = msg.data
        prev_mode = self.rover_state["mode"]
        if status == 0 or status == 2 or status == 3:
            # nav2の失敗結果は上書きしない（reset_errorでidleに戻す）。ファームウェア異常は復帰時にidleに戻す
            if not (prev_mode == "error" and self.rover_state["error_source"] == "nav"):
                self.rover_state["mode"] = "idle"
                if self.rover_state["error_source"] == "firm":
                    self.set_error_state("", -1, "")
        elif status == 1:
            self.rover_state["mode"] = "executing"
        else:
            self.rover_state["mode"] = "error"
            self.set_error_state("firm", status, f"firmware error (firm_state={status})")

    def set_error_state(self, source, code, description):
        self.rover_state["error_source"] = source
        self.rover_state["error_code"] = code
        self.rover_state["error_description"] = description

    def clear_nav_error(self):
        # nav2の失敗結果をクリアしてidleに戻す（ファームウェア異常はファームウェア復帰時にクリア）
        if self.rover_state["error_source"] == "nav":
            if self.rover_state["mode"] == "error":
                self.rover_state["mode"] = "idle"
            self.set_error_state("", -1, "")
    
    def bumper_state_cb(self, msg):
        state = msg.data
        if state > 0:
            if self.motor_lock:
                pub_msg = UInt8()
                pub_msg.data = 1
                self.motor_release_pub.publish(pub_msg)
                self.motor_lock = False

                arm_disable_msg = Empty()
                self.right_arm_disable_pub.publish(arm_disable_msg)
                self.left_arm_disable_pub.publish(arm_disable_msg)
                self.arm_disabled_by_bumper = True
            self.motor_release_time = self.get_clock().now().nanoseconds * 1e-9
        else:
            if not self.motor_lock:
                current_time = self.get_clock().now().nanoseconds * 1e-9
                if current_time - self.motor_release_time > self.motor_release_limit:
                    pub_msg = UInt8()
                    pub_msg.data = 0
                    self.motor_release_pub.publish(pub_msg)
                    self.motor_lock = True

                    # バンパー接触で無効化したアームだけ再度有効化する（起動直後などは有効化しない）
                    if self.arm_disabled_by_bumper:
                        arm_enable_msg = Empty()
                        self.right_arm_enable_pub.publish(arm_enable_msg)
                        self.left_arm_enable_pub.publish(arm_enable_msg)
                        self.arm_disabled_by_bumper = False

    def bumper_release(self):
        send_msg = UInt8()
        send_msg.data = 1
        self.bumper_clear_pub.publish(send_msg)

    def send_goal(self, goal_pose):
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose

        self.pose_action_client.wait_for_server()
        return self.pose_action_client.send_goal_async(goal_msg)

    def goal_response_callback(self, future):
        self.goal_handle = future.result()
        if not self.goal_handle.accepted:
            self.get_logger().warn('Goal rejected :(')
            return

        self.get_logger().debug('Goal accepted.')

        self._get_result_future = self.goal_handle.get_result_async()
        self.get_logger().debug('result wait.')
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result()
        # Nav2 GoalStatus: 4=SUCCEEDED, 5=CANCELED, 6=ABORTED
        if result.status == 4:  # SUCCEEDED
            self.rover_state["arrived"] = True
            self.rover_state["destination"] = [0, 0]
        else:  # ABORTED or CANCELED
            self.rover_state["mode"] = "error"
            self.set_error_state("nav", result.status, f"navigation aborted (nav2_status={result.status})")
            # rosNAV_smrがerrorを検知してfailed記録するのに十分な時間待ってからidleに戻す
            # （butukusaトピック経由でerrorを配信し続けるとrosNAV_smrがidle戻しを上書きしてしまうため）
            def reset_error():
                time.sleep(1.0)
                self.clear_nav_error()
            threading.Thread(target=reset_error, daemon=True).start()

    def timer_callback(self):
        self.get_logger().debug("timer in")
        state_msg = StringStamped()
        state_msg.header.stamp = self.get_clock().now().to_msg()
        state_msg.header.frame_id = "map"
        state_msg.data = json.dumps(self.rover_state)
        self.butukusa_pub.publish(state_msg)

        rover_pose = self.get_rover_pose()
        if rover_pose:
            pose_msg = PoseStamped()
            pose_msg.header.stamp = self.get_clock().now().to_msg()
            pose_msg.header.frame_id = "map"
            pose_msg.pose.position.x = rover_pose.transform.translation.x
            pose_msg.pose.position.y = rover_pose.transform.translation.y
            pose_msg.pose.position.z = rover_pose.transform.translation.z
            pose_msg.pose.orientation = rover_pose.transform.rotation
            self.pose_pub.publish(pose_msg)

            angle = 2*np.arctan2(rover_pose.transform.rotation.z,rover_pose.transform.rotation.w)
            pose = [rover_pose.transform.translation.x,
                    rover_pose.transform.translation.y,
                    angle]
            with open(self.rover_pose_path, 'w') as file:
                file.write(','.join(map(str, pose)))

    def get_rover_pose(self):
        try:
            transform_stamped = self.tf_buffer.lookup_transform("map", self.robot_name+"_base_footprint", rclpy.time.Time())
        except:
            transform_stamped = None
            self.get_logger().debug("fail to get tf")
        return transform_stamped

    def quaternion_from_euler(self, roll, pitch, yaw):
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)

        quat = Quaternion()
        quat.w = cy * cp * cr + sy * sp * sr
        quat.x = cy * cp * sr - sy * sp * cr
        quat.y = sy * cp * sr + cy * sp * cr
        quat.z = sy * cp * cr - cy * sp * sr

        return quat

def main():
    rclpy.init()
    node = RoverWrapper()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
