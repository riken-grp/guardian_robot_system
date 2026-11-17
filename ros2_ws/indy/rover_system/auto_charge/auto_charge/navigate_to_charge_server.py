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
        # None until the first rover/battery message (0.0 would look like charging)
        self.battery_current = None
        self.docking_start_time = None
        # Overall timeout [s] until charging starts (docking took up to 112 s on indy1e)
        self.docking_timeout = self.declare_parameter('docking_timeout', 180.0).value
        # Timeout [s] for the docking process to start (charging station not found)
        self.docking_start_wait_timeout = self.declare_parameter('docking_start_wait_timeout', 10.0).value
        # Charging must continue this long [s] before it counts: the contacts can
        # touch for a moment while auto_charge is still moving (indy1e, 2026-11-16)
        self.charge_confirm_time = self.declare_parameter('charge_confirm_time', 3.0).value
        # After auto_charge has stopped, charging must still continue this long [s]
        self.charge_settle_time = self.declare_parameter('charge_settle_time', 2.0).value
        # Time [s] allowed for auto_charge to stop after dock_cancel
        self.stop_wait_timeout = self.declare_parameter('stop_wait_timeout', 5.0).value
        # Time [s] to check that auto_charge stopped before a goal is aborted or
        # canceled (dock_cancel is sent again meanwhile)
        self.cancel_confirm_timeout = self.declare_parameter('cancel_confirm_timeout', 3.0).value
        self.get_logger().info(
            f'docking_timeout: {self.docking_timeout} s, '
            f'docking_start_wait_timeout: {self.docking_start_wait_timeout} s, '
            f'charge_confirm_time: {self.charge_confirm_time} s, '
            f'charge_settle_time: {self.charge_settle_time} s'
        )

        # Callback groups for concurrent execution
        action_cb_group = MutuallyExclusiveCallbackGroup()
        subscriber_cb_group = MutuallyExclusiveCallbackGroup()

        # Publisher to trigger auto charge
        self.dock_start_pub = self.create_publisher(
            Empty,
            'auto_charge/dock_start',
            10
        )

        # Publisher to abort an ongoing docking process.  Without this the
        # auto_charge node keeps driving after the goal is aborted/canceled.
        self.dock_cancel_pub = self.create_publisher(
            Empty,
            'auto_charge/dock_cancel',
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
        return self.battery_current is not None and self.battery_current <= 0.01

    def cancel_docking(self, reason):
        """Tell the auto_charge node to stop the docking process.

        The node stops the rover and resets its state when it receives this,
        so every failure path must go through here before returning.
        """
        self.get_logger().warn(f'Canceling docking: {reason}')
        self.dock_cancel_pub.publish(Empty())

    def stop_auto_charge(self, reason, elapsed_seconds):
        """Send dock_cancel and check that auto_charge has really stopped.

        dock_cancel is sent again every 0.5 s until in_docking_process becomes
        False (at most cancel_confirm_timeout s). Returns True when it stopped.
        """
        self.get_logger().warn(
            f'Stopping auto_charge: {reason} (elapsed {elapsed_seconds:.1f} s, '
            f'docking_timeout {self.docking_timeout} s)')
        self.cancel_docking(reason)
        # in_docking_process is published every 0.1 s: wait for a fresh value
        time.sleep(0.3)
        start = time.monotonic()
        last_sent = start
        while rclpy.ok() and self.is_docking:
            now = time.monotonic()
            if now - start > self.cancel_confirm_timeout:
                self.get_logger().error(
                    f'auto_charge did not stop {self.cancel_confirm_timeout} s after dock_cancel '
                    '(is the auto_charge node up to date?)')
                return False
            if now - last_sent >= 0.5:
                self.get_logger().warn('auto_charge still docking: sending dock_cancel again')
                self.dock_cancel_pub.publish(Empty())
                last_sent = now
            time.sleep(0.1)
        self.get_logger().info('auto_charge stopped')
        return True

    def fail(self, goal_handle, reason, elapsed_seconds):
        """Stop auto_charge and abort the goal."""
        self.stop_auto_charge(reason, elapsed_seconds)
        goal_handle.abort()
        self.get_logger().error(
            f'Navigate to charge failed: {reason} (elapsed {elapsed_seconds:.1f} s, '
            f'docking_timeout {self.docking_timeout} s, current {self.battery_current})')
        return NavigateToPose.Result()

    def execute_callback(self, goal_handle):
        """Execute the navigate to charge action"""
        self.get_logger().info(
            f'Executing navigate to charge (docking_timeout {self.docking_timeout} s, '
            f'docking_start_wait_timeout {self.docking_start_wait_timeout} s, '
            f'charge_confirm_time {self.charge_confirm_time} s, '
            f'charge_settle_time {self.charge_settle_time} s)')
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
        # Success needs two steps:
        #   'docking':  charging continues for charge_confirm_time
        #               -> stop auto_charge (dock_cancel) if it is still running
        #   'settling': auto_charge has stopped and charging continues for
        #               charge_settle_time -> succeed
        phase = 'docking'
        charging_since = None   # start of the current continuous charging [s]
        settle_start = None     # time the settling phase started [s]
        stopped_since = None    # time auto_charge was seen stopped while settling [s]

        while rclpy.ok():
            loop_count += 1

            # Check timeout
            current_time = self.get_clock().now()
            elapsed_time = current_time - self.docking_start_time
            elapsed_seconds = elapsed_time.nanoseconds / 1e9
            now = current_time.nanoseconds / 1e9

            if goal_handle.is_cancel_requested:
                self.stop_auto_charge('canceled by client', elapsed_seconds)
                goal_handle.canceled()
                self.get_logger().info('Goal canceled')
                return NavigateToPose.Result()

            # Log status every 1 second (10 iterations at 10 Hz)
            if loop_count % 10 == 0:
                self.get_logger().info(
                    f'Monitoring: phase={phase}, is_docking={self.is_docking}, '
                    f'docking_ever_started={docking_ever_started}, '
                    f'is_charging={self.is_charging()}, current={self.battery_current}, '
                    f'elapsed={elapsed_seconds:.1f}s'
                )

            if phase == 'docking':
                # Check if docking has not started within timeout
                if (not docking_ever_started and charging_since is None
                        and elapsed_seconds > self.docking_start_wait_timeout):
                    return self.fail(
                        goal_handle,
                        f'docking did not start within {self.docking_start_wait_timeout} s '
                        '(charging station likely not found)', elapsed_seconds)

                # Check overall timeout
                if elapsed_seconds > self.docking_timeout:
                    return self.fail(goal_handle, 'overall docking timeout', elapsed_seconds)

                # Check if docking started
                if self.is_docking and not previous_docking_state:
                    self.get_logger().info('Docking process started')
                    docking_ever_started = True

                if self.is_charging():
                    # A momentary contact is not a success: charging has to continue
                    if charging_since is None:
                        charging_since = now
                        self.get_logger().info(
                            f'Charging detected (current: {self.battery_current}), '
                            f'confirming for {self.charge_confirm_time} s')
                    elif now - charging_since >= self.charge_confirm_time:
                        self.get_logger().info('Charging continued - stopping auto_charge')
                        if self.is_docking:
                            # auto_charge may keep moving (retry) although the
                            # robot is charging: stop it here
                            self.cancel_docking('charging confirmed')
                        phase = 'settling'
                        settle_start = now
                else:
                    if charging_since is not None:
                        self.get_logger().warn(
                            f'Charging stopped after {now - charging_since:.1f} s '
                            f'(current: {self.battery_current})')
                        charging_since = None
                    # Check if docking process ended without starting charging (failure)
                    # This includes cases where charging station was not found
                    if docking_ever_started and not self.is_docking:
                        return self.fail(
                            goal_handle, 'auto_charge ended without charging', elapsed_seconds)

            else:  # settling
                if not self.is_charging():
                    return self.fail(
                        goal_handle, 'charging stopped after auto_charge stopped', elapsed_seconds)
                if self.is_docking:
                    stopped_since = None
                    if now - settle_start > self.stop_wait_timeout:
                        return self.fail(goal_handle, 'auto_charge did not stop', elapsed_seconds)
                else:
                    if stopped_since is None:
                        stopped_since = now
                    elif now - stopped_since >= self.charge_settle_time:
                        break

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

        if not rclpy.ok():
            return NavigateToPose.Result()

        # Set result - SUCCESS
        goal_handle.succeed()
        self.get_logger().info(
            'Navigate to charge completed successfully - charging continues with auto_charge stopped')
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
