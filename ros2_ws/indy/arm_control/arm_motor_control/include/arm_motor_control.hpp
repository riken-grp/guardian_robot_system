#ifndef ARM_MOTOR_CONTROL_HPP
#define ARM_MOTOR_CONTROL_HPP

// ROS2
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <std_msgs/msg/float32_multi_array.hpp>
#include <std_msgs/msg/empty.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <string>
#include <vector>
#include <cmath>
#include <unistd.h>
#include <rclcpp/executors/multi_threaded_executor.hpp>
#include <mutex>
#include <filesystem>
#include <fstream>


class ArmMotorControl : public rclcpp::Node {
    public:
        ArmMotorControl();  // コンストラクタ
        ~ArmMotorControl();
        

    private:
        void timer_callback();
        void control_joints(const trajectory_msgs::msg::JointTrajectory::SharedPtr msg);
        void enable_callback(const std_msgs::msg::Empty::SharedPtr msg);
        void disable_callback(const std_msgs::msg::Empty::SharedPtr msg);
        void control_enable();
        void control_disable();

        void temp_check(const std::vector<float>& temps);

        std::string can_interface_name_;
        std::vector<std::string> joint_names_;
        std::vector<long int> can_id_;
        long int joints_pub_cycle_;
        bool temp_check_;
        double restart_temp_;
        double max_temp_;
        std::vector<double> default_offset_;
        std::vector<double> gain_;
        std::vector<double> default_position_;
        std::vector<double> max_velocity_;
        std::vector<double> max_position_;
        std::vector<double> min_position_;
        std::vector<double> default_velocity_;
        Robstride02Driver can_interface_;
        std::vector<double> offset_;
        std::mutex get_mutex_;
        std::mutex set_mutex_;
        bool set_process_flag_;
        std::vector<int> error_cnt_;
        std::vector<bool> motors_up_flg_;
        bool can_init_flg_;
        bool temp_over_flg_;
        int temp_over_cnt_;
        std::string arm_status_file_;

        // サブスクライバー
        rclcpp::Subscription<trajectory_msgs::msg::JointTrajectory>::SharedPtr joint_trajectory_sub_;
        rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr enable_sub_;
        rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr disable_sub_;

        // パブリッシャー
        rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joints_pub_;
        rclcpp::Publisher<std_msgs::msg::Float32MultiArray>::SharedPtr temp_pub_;

        // タイマー
        rclcpp::TimerBase::SharedPtr timer_;
};

#endif  // ARM_MOTOR_CONTROL_HPP
