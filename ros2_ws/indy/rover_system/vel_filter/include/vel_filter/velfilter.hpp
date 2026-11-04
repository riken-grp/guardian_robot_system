#ifndef VEL_FILTER__VELFILTER_HPP_
#define VEL_FILTER__VELFILTER_HPP_

#include <memory>
#include <string>
#include <cstdlib>
#include <vector>
#include <algorithm>
#include <cmath>
#include <tuple>
#include <std_msgs/msg/float64.hpp>

#include "rclcpp/rclcpp.hpp"
#include "geometry_msgs/msg/vector3.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "tf2_ros/buffer.h"
#include "tf2_ros/transform_listener.h"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2/LinearMath/Matrix3x3.h"
#include "tf2_geometry_msgs/tf2_geometry_msgs.hpp"

#include <pcl_conversions/pcl_conversions.h>

namespace vel_filter
{

class VelFilter : public rclcpp::Node
{
public:
  VelFilter();

private:
  // Callback functions
  void vel_cmd_callback(const geometry_msgs::msg::Twist::SharedPtr msg);
  void max_vel_cmd_callback(const std_msgs::msg::Float64::SharedPtr msg);
  void bu_image_callback(const sensor_msgs::msg::Image::SharedPtr msg);
  void td_image_callback(const sensor_msgs::msg::Image::SharedPtr msg);
  void bu_camera_info_callback(const sensor_msgs::msg::CameraInfo::SharedPtr msg);
  void td_camera_info_callback(const sensor_msgs::msg::CameraInfo::SharedPtr msg);
  void scan_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg);

  // Utility functions
  std::tuple<double, double> calc_slow_twist();
  double calc_filtered_velocity(double target_vel);
  std::tuple<float, float, float> calc_range_from_image(const sensor_msgs::msg::Image::SharedPtr& img_msg, const std::vector<double>& camera_info, const tf2::Transform& tf);

  std::string robot_name_;
  double robot_height_;
  double robot_width_;
  double max_velocity_;
  double min_back_velocity_;
  double max_recog_range_;
  double min_obstacle_range_;
  double max_obstacle_range_;
  double max_scan_obstacle_range_;
  double min_cliff_range_;
  double max_cliff_range_;
  double filtering_factor_;
  std::vector<double> bu_camera_info_;
  std::vector<double> td_camera_info_;

  double min_x_bu_;
  double min_x_td_;
  double min_y_bu_;
  double min_y_td_;
  double min_range_bu_;
  double min_range_td_;

  double front_min_x_scan_;
  double front_min_y_scan_;
  double front_min_range_scan_;
  double back_min_x_scan_;
  double back_min_y_scan_;
  double back_min_range_scan_;
  
  double default_max_velocity_;

  // TF2
  std::unique_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
  tf2::Transform td_tf_;
  tf2::Transform bu_tf_;
  bool td_transform_inited_;
  bool bu_transform_inited_;

  // Publishers and Subscribers
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr filtered_vel_pub_;
  rclcpp::Publisher<geometry_msgs::msg::Vector3>::SharedPtr nearest_camera_point_pub_;
  rclcpp::Publisher<geometry_msgs::msg::Vector3>::SharedPtr nearest_scan_point_pub_;

  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr vel_cmd_sub_;
  rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr max_vel_cmd_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr camera_bu_raw_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr camera_td_raw_sub_;
  rclcpp::Subscription<sensor_msgs::msg::CameraInfo>::SharedPtr camera_bu_info_sub_;
  rclcpp::Subscription<sensor_msgs::msg::CameraInfo>::SharedPtr camera_td_info_sub_;
  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr scan_sub_;

  // Callback groups
  rclcpp::CallbackGroup::SharedPtr velocity_cb_group_;
  rclcpp::CallbackGroup::SharedPtr camera_bu_cb_group_;
  rclcpp::CallbackGroup::SharedPtr camera_td_cb_group_;
  rclcpp::CallbackGroup::SharedPtr scan_cb_group_;

  // timer
  rclcpp::TimerBase::SharedPtr timer_main_;
  void timer_callback();

  int last_twist_cnt_;
  double last_target_vel_;
  double last_target_angle_;
  std::chrono::system_clock::time_point last_vel_time_;
  std::chrono::system_clock::time_point last_max_vel_time_;
  std::chrono::system_clock::time_point last_camera_time_;
};

}  // namespace vel_filter

#endif  // VEL_FILTER__VELFILTER_HPP_
