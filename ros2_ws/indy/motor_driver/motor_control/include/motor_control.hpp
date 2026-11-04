#ifndef MOTOR_CONTROL_HPP
#define MOTOR_CONTROL_HPP

// ROS2
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/empty.hpp>
#include <std_msgs/msg/float32_multi_array.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <string>
#include <cstring>
#include <vector>
#include <cmath>
#include <rclcpp/executors/multi_threaded_executor.hpp>

class MotorControl : public rclcpp::Node {
    public:
        MotorControl();  // コンストラクタ
        ~MotorControl();

    private:
        void timer_callback();
        void control_position(const sensor_msgs::msg::JointState::SharedPtr msg);
        void control_speed(const sensor_msgs::msg::JointState::SharedPtr msg);
        void control_enable(const std_msgs::msg::Empty::SharedPtr msg);
        void control_disable(const std_msgs::msg::Empty::SharedPtr msg);

        std::string can_interface_name_;
        std::vector<std::string> joint_name_;
        std::vector<long int> can_id_;
        std::vector<double> default_offset_;
        std::vector<double> max_velocity_;
        std::vector<double> gain_;
        std::vector<double> max_position_;
        std::vector<double> min_position_;
        std::vector<double> default_velocity_;
        Robstride02Driver can_interface_;
        std::vector<double> offset_;
        std::vector<int> error_cnt_;
        std::vector<bool> motors_up_flg_;
        bool can_init_flg_;

        // サブスクライバー
        rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr control_position_sub_;
        rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr control_speed_sub_;
        rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr control_enable_sub_;
        rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr control_disable_sub_;

        // パブリッシャー
        rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr motor_info_pub_;
        rclcpp::Publisher<std_msgs::msg::Float32MultiArray>::SharedPtr temp_pub_;

        // タイマー
        rclcpp::TimerBase::SharedPtr timer_;
};

#endif  // MOTOR_CONTROL_HPP
