#pragma once

#include <chrono>
#include <math.h>
#include <memory>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2_ros/static_transform_broadcaster.h"

#include "rcl_interfaces/msg/parameter_descriptor.hpp"
#include "rcl_interfaces/msg/floating_point_range.hpp"
#include "rcl_interfaces/msg/set_parameters_result.hpp"

using namespace std::chrono_literals;

class TransformTFBroadcaster : public rclcpp::Node {
    public:
        TransformTFBroadcaster();
        
        ~TransformTFBroadcaster();

    private:
        void setDoubleParamSlider(std::string param_name, float& param, double max_range, double min_range);

        void makeTransforms();
        rcl_interfaces::msg::SetParametersResult updateParamCallback(const std::vector<rclcpp::Parameter>& params);

        std::shared_ptr<tf2_ros::StaticTransformBroadcaster> tf_static_broadcaster_;
        rclcpp::TimerBase::SharedPtr broadcaster_timer_;
        OnSetParametersCallbackHandle::SharedPtr update_param_handler_;

        std::string parent_frame_;
        std::string child_frame_;
        float transform_x_;
        float transform_y_;
        float transform_z_;
        float transform_roll_;
        float transform_pitch_;
        float transform_yaw_;
};