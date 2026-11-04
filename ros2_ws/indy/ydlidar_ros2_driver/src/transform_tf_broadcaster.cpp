#include <transform_tf_broadcaster.hpp>

TransformTFBroadcaster::TransformTFBroadcaster() : Node("transform_tf_broadcaster") {
    RCLCPP_DEBUG(this->get_logger(), "in constractor");
    tf_static_broadcaster_ = std::make_shared<tf2_ros::StaticTransformBroadcaster>(this);

    declare_parameter("parent_frame", "");
    parent_frame_ = this->get_parameter("parent_frame").as_string();

    declare_parameter("child_frame", "");
    child_frame_ = this->get_parameter("child_frame").as_string();

    double pi = 3.14;
    setDoubleParamSlider("transform_pose_x", transform_x_, 10.0, -10.0);
    setDoubleParamSlider("transform_pose_y", transform_y_, 10.0, -10.0);
    setDoubleParamSlider("transform_pose_z", transform_z_, 10.0, -10.0);
    setDoubleParamSlider("transform_rot_roll", transform_roll_, pi, -pi);
    setDoubleParamSlider("transform_rot_pitch", transform_pitch_, pi, -pi);
    setDoubleParamSlider("transform_rot_yaw", transform_yaw_, pi, -pi);

    update_param_handler_ = this->add_on_set_parameters_callback(
        std::bind(&TransformTFBroadcaster::updateParamCallback, this, std::placeholders::_1));

    broadcaster_timer_ =
        this->create_wall_timer(100ms, std::bind(&TransformTFBroadcaster::makeTransforms, this));
}

TransformTFBroadcaster::~TransformTFBroadcaster() {}

void TransformTFBroadcaster::setDoubleParamSlider(std::string param_name, float& param, double max_range, double min_range) {
    rcl_interfaces::msg::ParameterDescriptor descriptor;
    rcl_interfaces::msg::FloatingPointRange range;
    range.set__from_value(min_range).set__to_value(max_range).set__step(0.0001);
    descriptor.floating_point_range = {range};
    declare_parameter(param_name, 0.0, descriptor);
    param = this->get_parameter(param_name).as_double();
}

void TransformTFBroadcaster::makeTransforms() {
    geometry_msgs::msg::TransformStamped t;

    t.header.stamp = this->get_clock()->now();
    t.header.frame_id = parent_frame_;
    t.child_frame_id = child_frame_;

    t.transform.translation.x = transform_x_;
    t.transform.translation.y = transform_y_;
    t.transform.translation.z = transform_z_;
    tf2::Quaternion q;
    q.setRPY(transform_roll_, transform_pitch_, transform_yaw_);
    t.transform.rotation.x = q.x();
    t.transform.rotation.y = q.y();
    t.transform.rotation.z = q.z();
    t.transform.rotation.w = q.w();

    tf_static_broadcaster_->sendTransform(t);
}

rcl_interfaces::msg::SetParametersResult TransformTFBroadcaster::updateParamCallback(const std::vector<rclcpp::Parameter>& params) {
    RCLCPP_DEBUG(this->get_logger(), "update parameter");
    auto results = std::make_shared<rcl_interfaces::msg::SetParametersResult>();
    results->successful = true;

    for(auto&&param : params) {
        if(param.get_name() == "transform_pose_x") {
            RCLCPP_DEBUG(this->get_logger(), "x:%f", param.as_double());
            transform_x_ = param.as_double();
        }
        else if(param.get_name() == "transform_pose_y") {
            RCLCPP_DEBUG(this->get_logger(), "y:%f", param.as_double());
            transform_y_ = param.as_double();
        }
        else if(param.get_name() == "transform_pose_z") {
            RCLCPP_DEBUG(this->get_logger(), "z:%f", param.as_double());
            transform_z_ = param.as_double();
        }
        else if(param.get_name() == "transform_rot_roll") {
            RCLCPP_DEBUG(this->get_logger(), "r:%f", param.as_double());
            transform_roll_ = param.as_double();
        }
        else if(param.get_name() == "transform_rot_pitch") {
            RCLCPP_DEBUG(this->get_logger(), "p:%f", param.as_double());
            transform_pitch_ = param.as_double();
        }
        else if(param.get_name() == "transform_rot_yaw") {
            RCLCPP_DEBUG(this->get_logger(), "y:%f", param.as_double());
            transform_yaw_ = param.as_double();
        }
        else if(param.get_name() == "parent_frame") {
            RCLCPP_DEBUG(this->get_logger(), "parent:%s", param.as_string().c_str());
            parent_frame_ = param.as_string();
        }
        else if(param.get_name() == "child_frame") {
            RCLCPP_DEBUG(this->get_logger(), "child:%s", param.as_string().c_str());
            child_frame_ = param.as_string();
        }
    }

    return *results;
}

int main(int argc, char* argv[]) {
    // Pass parameters and initialize node
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<TransformTFBroadcaster>());
    rclcpp::shutdown();
    return 0;
}