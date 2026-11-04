import threading
import rclpy
import numpy as np
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String, Float32
from sensor_msgs.msg import JointState
from keigan_grp_msgs.msg import JointData
from rclpy.callback_groups import ReentrantCallbackGroup
import logging

from .pykeigan import usbcontroller

class KeiganMotor(Node):
    def __init__(self):
        super().__init__('keigan_motor_node')
        self.get_logger().debug("init in")
        self.my_nodename = str(self.get_name()).strip('/')
        self.my_namespace = str(self.get_namespace()).strip('/')

        self.lock = threading.Lock()

        self.declare_parameter('joint_name', [""])
        self.declare_parameter('joint_port', [""])
        self.declare_parameter('max_velocity', [0.0])
        self.declare_parameter('default_velocity', [0.0])
        self.declare_parameter('default_acceleration', [0.0])
        self.declare_parameter('default_torque', [0.0])
        self.declare_parameter('report_hz', 100.0)
        self.declare_parameter('nearly_zero_vel', 0.15)
        self.declare_parameter('nearly_target_pose', 0.1)
        self.declare_parameter('max_duration', 15.0)

        joint_name_list = self.get_parameter('joint_name').get_parameter_value().string_array_value
        joint_port_list = self.get_parameter('joint_port').get_parameter_value().string_array_value
        max_velocity = self.get_parameter('max_velocity').get_parameter_value().double_array_value
        default_velocity = self.get_parameter('default_velocity').get_parameter_value().double_array_value
        self.target_acceleration = self.get_parameter('default_acceleration').get_parameter_value().double_array_value
        max_torque = self.get_parameter('default_torque').get_parameter_value().double_array_value
        report_hz = self.get_parameter('report_hz').get_parameter_value().double_value
        self.nearly_zero_vel = self.get_parameter('nearly_zero_vel').get_parameter_value().double_value
        self.nearly_target_pose = self.get_parameter('nearly_target_pose').get_parameter_value().double_value
        self.max_duration = self.get_parameter('max_duration').get_parameter_value().double_value

        self.joint_name_list = []
        for joint_name in joint_name_list:
            self.joint_name_list.append(self.my_namespace + "_" + joint_name)

        self.check_param_size(joint_port_list, "joint_port")
        self.check_param_size(max_velocity, "max_velocity")
        self.check_param_size(default_velocity, "default_velocity")
        self.check_param_size(self.target_acceleration, "default_acceleration")
        self.check_param_size(max_torque, "default_torque")

        self.target_velocity = min(max_velocity, default_velocity)

        self.device_list = []
        if not self.register_device(joint_port_list, max_velocity, max_torque):
            self.destroy_node()

        self.rate = self.create_rate(report_hz)         # メソッド内のループの周期設定
        self.stop_the_topic = False

        callback_group = ReentrantCallbackGroup()       # ReentrantCallbackGroupの作成

        ##############################
        # Register 'Timer' callbacks #
        ##############################
        timer_period = 1 / report_hz   # Hz -> sec
        self.timer = self.create_timer(timer_period, self.timer_callback, callback_group=callback_group)

        ###############################
        # Register 'Topic' publishers #
        ###############################
        self.state_pub = self.create_publisher(JointState, topic='keigan_motor/joints', qos_profile=10)

        ##############################
        # Register 'Topic' callbacks #
        ##############################
        self.create_subscription(msg_type=JointState, topic='keigan_motor/relative_goal_pose',
                                 callback=self.relative_goal_pose_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointState, topic='keigan_motor/goal_pose',
                                 callback=self.goal_pose_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointState, topic='keigan_motor/target_velocity',
                                 callback=self.target_velocity_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointData, topic='keigan_motor/set_velocity',
                                 callback=self.set_velocity_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointData, topic='keigan_motor/set_acceleration',
                                 callback=self.set_acceleration_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointData, topic='keigan_motor/set_torque',
                                 callback=self.set_torque_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=String, topic='keigan_motor/stop_move',
                                 callback=self.stop_move_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=String, topic='keigan_motor/reset_offset',
                                 callback=self.reset_offset_callback, qos_profile=10, callback_group=callback_group)
        self.create_subscription(msg_type=JointState, topic='keigan_motor/target_vel_pose',
                                 callback=self.target_vel_pose_callback, qos_profile=10, callback_group=callback_group)

    def register_device(self, joint_port_list, max_velocity, max_torque):
        for i, port_id in enumerate(joint_port_list):
            try:
                device = usbcontroller.USBController(port_id)
                device.set_max_speed(max_velocity[i])
                device.set_max_torque(max_torque[i])
                device.set_acc(self.target_acceleration[i])
                device.enable_action()
                device.preset_position(0.0)
                self.device_list.append(device)
                self.get_logger().info("connect to '%s' as '%s'" % (port_id, self.joint_name_list[i]))
            except:
                self.get_logger().warn("port:'%s' is not exist." % port_id)
                return False
        return True

    def timer_callback(self):
        self.get_logger().debug("timer in")
        current_state = JointState()
        current_state.header.stamp = self.get_clock().now().to_msg()
        for dev in self.device_list:
            all_status = dev.read_motor_measurement()
            current_state.position.append(all_status["position"])
            current_state.velocity.append(all_status["velocity"])
            current_state.effort.append(all_status["torque"])
        for name in self.joint_name_list:
            current_state.name.append(name)
        self.position = np.array(current_state.position)      # 現在角度の情報をクラス変数に保存
        self.velocity = np.array(current_state.velocity)      # 現在速度の情報をクラス変数に保存
        self.state_pub.publish(current_state)

    def relative_goal_pose_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("relative_goal_pose in.")

        with self.lock:

            dev_idx_list = []
            target_joint_name = msg.name
            target_pose = msg.position
            target_velocity = msg.velocity
        
            if not self.check_topic_field_length(target_joint_name, target_pose, "position"):
                return
            if len(target_velocity) != 0:
                if not self.check_topic_field_length(target_joint_name, target_velocity, "velocity"):
                    return
        
            for name in target_joint_name:
                if not self.check_joint_name(name):
                    return
                dev_idx_list.append(self.joint_name_list.index(name))

            for i, idx in enumerate(dev_idx_list):
                if len(target_velocity) == 0:
                    vel = self.target_velocity[idx]
                else:
                    vel = target_velocity[i]
                self.device_list[idx].move_by_dist(target_pose[i], vel)

        self.stop_the_topic = False

    def goal_pose_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("goal_pose in.")

        with self.lock:
            
            dev_idx_list = []
            target_joint_name = msg.name
            target_pose = msg.position
            target_velocity = msg.velocity

            if not self.check_topic_field_length(target_joint_name, target_pose, "position"):
                return
            if len(target_velocity) != 0:
                if not self.check_topic_field_length(target_joint_name, target_velocity, "velocity"):
                    return
        
            for name in target_joint_name:
                if not self.check_joint_name(name):
                    return
                dev_idx_list.append(self.joint_name_list.index(name))

            for i, idx in enumerate(dev_idx_list):
                if len(target_velocity) == 0:
                    vel = self.target_velocity[idx]
                else:
                    vel = target_velocity[i]
                self.device_list[idx].move_to_pos(target_pose[i], vel)

        self.get_logger().debug("goal_pose out.")
        self.stop_the_topic = False

    def target_velocity_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("target_velocity in.")

        with self.lock:

            dev_idx_list = []
            target_joint_name = msg.name
            target_velocity = msg.velocity
        
            if not self.check_topic_field_length(target_joint_name, target_velocity, "velocity"):
                return
        
            for name in target_joint_name:
                if not self.check_joint_name(name):
                    return
                dev_idx_list.append(self.joint_name_list.index(name))

            for i, idx in enumerate(dev_idx_list):
                vel = target_velocity[i]
                self.device_list[idx].run_at_velocity(vel)

        self.stop_the_topic = False

    def set_velocity_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("set_velocity in")
        with self.lock:
            if not self.check_joint_name(msg.joint_name):
                return
            dev_idx = self.joint_name_list.index(msg.joint_name)
            self.target_velocity[dev_idx] = msg.data
        self.stop_the_topic = False

    def set_acceleration_callback(self, msg):
        self.stop_the_topic = True
        with self.lock:
            if not self.check_joint_name(msg.joint_name):
                return
            dev_idx = self.joint_name_list.index(msg.joint_name)
            self.device_list[dev_idx].set_acc(msg.data)
        self.stop_the_topic = False

    def set_torque_callback(self, msg):
        self.stop_the_topic = True
        with self.lock:
            if not self.check_joint_name(msg.joint_name):
                return
            dev_idx = self.joint_name_list.index(msg.joint_name)
            self.device_list[dev_idx].set_max_torque(msg.data)
        self.stop_the_topic = False

    def stop_move_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("stop_move in.")
        with self.lock:
            joint_name = msg.data
            if not self.check_joint_name(joint_name):
                return
            idx = self.joint_name_list.index(joint_name)
            self.device_list[idx].stop_motor()
        self.stop_the_topic = False

    def reset_offset_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("reset_offset in.")
        with self.lock:
            joint_name = msg.data
            if not self.check_joint_name(joint_name):
                return
            idx = self.joint_name_list.index(joint_name)
            self.device_list[idx].preset_position(0.0)
        self.stop_the_topic = False

    def target_vel_pose_callback(self, msg):
        self.stop_the_topic = True
        self.get_logger().debug("target_vel_pose in.")

        with self.lock:
            dev_idx_list = []
            rot_dir = []
            finish = []
            time = 0.0
            target_joint_name = msg.name
            target_pose = msg.position


            if not self.check_topic_field_length(target_joint_name, target_pose, "position"):
                return    
            for name in target_joint_name:
                if not self.check_joint_name(name):
                    return
                dev_idx_list.append(self.joint_name_list.index(name))
                rot_dir.append(True)
                finish.append(False)

            self.stop_the_topic = False                         # 他トピックの割込みに対する本トピックの停止フラグ

            for i, idx in enumerate(dev_idx_list):
                if target_pose[i] < self.position[idx]:
                    rot_dir[i] = False
            
            starttime = self.get_clock().now().nanoseconds
            
            # 目標位置から角速度を設定するループ
            while rclpy.ok() and not self.stop_the_topic:
                target_velocity = 3 * [float(x) for x in self.limit11(2 * (target_pose - self.position[dev_idx_list]))]
                time = self.get_clock().now().nanoseconds - starttime

                for i, idx in enumerate(dev_idx_list):

                    # 目標値に達したモータを空ループさせる
                    if finish[i]:
                       continue 

                    # 目標値を通り過ぎた場合
                    if (rot_dir[i] == True and target_pose[i] <= self.position[idx]) or (rot_dir[i] == False and target_pose[i] >= self.position[idx]):
                        target_pose[i] = self.position[idx]
                        vel = 0
                        finish[i] = True
                    # 現在の速度が0に近く、目標位置に十分近い場合
                    elif abs(self.velocity[i]) < self.nearly_zero_vel and abs(target_pose[i] - self.position[idx]) < self.nearly_target_pose:
                        vel = 0
                        finish[i] = True
                    # 時間がかかりすぎた場合
                    elif time > self.max_duration * 10**9:
                        vel = 0
                        finish[i] = True
                        self.get_logger().debug("time out.")
                    else:
                        vel = target_velocity[i]
                        
                    self.device_list[idx].run_at_velocity(vel)
                
                    # すべてのモータが目標値に達したらループを脱する
                    if all(finish):
                        break
                
                if all(finish):
                    self.get_logger().debug("target_vel_pose out.")
                    break

                self.rate.sleep()

    def limit11(self, x):
        x[np.where(x > 1.0)] = 1.0
        x[np.where(x < -1.0)] = -1.0
        return x

    def check_param_size(self, param, param_name):
        if len(self.joint_name_list) != len(param):
            self.get_logger().error("Size of joint_name and %s is different." % param_name)
            self.destroy_node()

    def check_topic_field_length(self, base_field, target_field, field_name):
        if len(base_field) != len(target_field):
            self.get_logger().warn("length of name and %s is different." % field_name)
            return False
        return True
    
    def check_joint_name(self, name):
        if not name in self.joint_name_list:
            self.get_logger().warn("joint_name: %s is not registed." % name)
            return False
        return True

    def torque_free(self):
        for device in self.device_list:
            device.run_at_velocity(0.0)
            device.set_max_torque(0)

def main():
    rclpy.init()
    try:
        node = KeiganMotor()
        executor = MultiThreadedExecutor()
        executor.add_node(node)
        executor.spin()
    except Exception as err:
        logging.getLogger().error(err)
    finally:
        node.torque_free()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
