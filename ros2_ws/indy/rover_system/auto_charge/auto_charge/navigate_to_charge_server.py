#!/usr/bin/env python3
import os
import time
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, GoalResponse, CancelResponse
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy import qos

from nav2_msgs.action import NavigateToPose
from std_msgs.msg import Empty, Bool
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import PoseStamped
from builtin_interfaces.msg import Duration


class NavigateToChargeServer(Node):
    def __init__(self):
        super().__init__('navigate_to_charge_server')

        self.robot_name = os.getenv("ROBOT_NAME")
        if self.robot_name is None:
            self.get_logger().error("Failed to get robot name")
            return

        # State tracking
        self.is_docking = False
        self.battery_current = 0.0
        self.docking_start_time = None
        self.docking_timeout = 60.0  # Timeout in seconds
        self.docking_start_wait_timeout = 10.0  # Wait timeout for docking to start

        # Callback groups for concurrent execution
        action_cb_group = MutuallyExclusiveCallbackGroup()
        subscriber_cb_group = MutuallyExclusiveCallbackGroup()

        # Publisher to trigger auto charge
        self.dock_start_pub = self.create_publisher(
            Empty,
            'auto_charge/dock_start',
            10
        )

        # Subscriber to monitor docking status
        self.dock_status_sub = self.create_subscription(
            Bool,
            'auto_charge/in_docking_process',
            self.dock_status_callback,
            10,
            callback_group=subscriber_cb_group
        )

        # Subscriber to monitor battery status
        self.battery_sub = self.create_subscription(
            BatteryState,
            'rover/battery',
            self.battery_callback,
            qos.qos_profile_sensor_data,
            callback_group=subscriber_cb_group
        )

        # Action server
        self._action_server = ActionServer(
            self,
            NavigateToPose,
            'navigate_to_charge',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=action_cb_group
        )

        self.get_logger().info('Navigate to charge action server started')

    def dock_status_callback(self, msg):
        """Monitor docking status from auto_charge node"""
        if self.is_docking != msg.data:
            self.get_logger().info(f'Docking status changed: {msg.data}')
        self.is_docking = msg.data

    def battery_callback(self, msg):
        """Monitor battery current to detect charging"""
        self.battery_current = msg.current

    def goal_callback(self, goal_request):
        """Accept or reject a client request to begin an action"""
        self.get_logger().info('Received navigate to charge goal request')
        # Goal pose is ignored - we navigate to the charging station automatically
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        """Accept or reject a client request to cancel an action"""
        self.get_logger().info('Received cancel request')
        return CancelResponse.ACCEPT

    def is_charging(self):
        """Check if robot is charging (current <= 0.01)"""
        return self.battery_current <= 0.01

    def execute_callback(self, goal_handle):
        """Execute the navigate to charge action"""
        self.get_logger().info('Executing navigate to charge...')
        self.get_logger().info('Goal pose is ignored - navigating to charging station automatically')
        self.get_logger().info(f'Initial docking status: {self.is_docking}')

        # Start docking process by publishing to dock_start topic
        self.docking_start_time = self.get_clock().now()
        dock_msg = Empty()
        self.dock_start_pub.publish(dock_msg)
        self.get_logger().info('Published dock_start message')

        # Wait a moment for the auto_charge node to pick up the request
        time.sleep(0.1)

        # Create feedback message
        feedback_msg = NavigateToPose.Feedback()

        # Monitor docking process and send feedback
        feedback_rate = 10.0  # 10 Hz
        sleep_time = 1.0 / feedback_rate
        previous_docking_state = False
        docking_ever_started = False
        loop_count = 0

        while rclpy.ok():
            loop_count += 1

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.get_logger().info('Goal canceled')
                return NavigateToPose.Result()

            # Check timeout
            current_time = self.get_clock().now()
            elapsed_time = current_time - self.docking_start_time
            elapsed_seconds = elapsed_time.nanoseconds / 1e9

            # Log status every 1 second (10 iterations at 10 Hz)
            if loop_count % 10 == 0:
                self.get_logger().info(
                    f'Monitoring: is_docking={self.is_docking}, '
                    f'docking_ever_started={docking_ever_started}, '
                    f'is_charging={self.is_charging()}, '
                    f'elapsed={elapsed_seconds:.1f}s'
                )

            # Check if docking has not started within timeout
            if not docking_ever_started and elapsed_seconds > self.docking_start_wait_timeout:
                goal_handle.abort()
                self.get_logger().error(
                    f'Docking failed to start within {self.docking_start_wait_timeout} seconds - '
                    'charging station likely not found'
                )
                return NavigateToPose.Result()

            # Check overall timeout
            if elapsed_seconds > self.docking_timeout:
                goal_handle.abort()
                self.get_logger().error(f'Docking timeout - failed to start charging after {self.docking_timeout} seconds')
                return NavigateToPose.Result()

            # Check if docking started
            if self.is_docking and not previous_docking_state:
                self.get_logger().info('Docking process started')
                docking_ever_started = True

            # Check if charging started (success condition)
            if self.is_charging():
                self.get_logger().info(f'Charging detected! Battery current: {self.battery_current}')
                break

            # Check if docking process ended without starting charging (failure)
            # This includes cases where charging station was not found
            if docking_ever_started and not self.is_docking and not self.is_charging():
                goal_handle.abort()
                self.get_logger().error('Docking failed - charging station not found or docking unsuccessful')
                return NavigateToPose.Result()

            previous_docking_state = self.is_docking

            # Update and publish feedback
            feedback_msg.current_pose = PoseStamped()
            feedback_msg.current_pose.header.stamp = current_time.to_msg()
            feedback_msg.current_pose.header.frame_id = 'base_link'

            feedback_msg.navigation_time = Duration(
                sec=int(elapsed_seconds),
                nanosec=int((elapsed_seconds % 1) * 1e9)
            )

            # Estimate remaining time (rough estimate)
            feedback_msg.estimated_time_remaining = Duration(
                sec=max(0, int(self.docking_timeout - elapsed_seconds)),
                nanosec=0
            )

            feedback_msg.number_of_recoveries = 0
            feedback_msg.distance_remaining = 0.0

            # Publish feedback
            goal_handle.publish_feedback(feedback_msg)

            # Sleep to maintain rate
            time.sleep(sleep_time)

        # Set result - SUCCESS
        goal_handle.succeed()
        self.get_logger().info('Navigate to charge completed successfully - charging started')
        return NavigateToPose.Result()


def main(args=None):
    rclpy.init(args=args)

    node = NavigateToChargeServer()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
