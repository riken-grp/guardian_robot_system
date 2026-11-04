#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit/planning_scene_interface/planning_scene_interface.h>
#include <rclcpp/rclcpp.hpp>

#include "flamingo_grp_msgs/msg/euler_pose_stamped.hpp"
#include "flamingo_grp_msgs/msg/euler_way_end_pose_stamped.hpp"
#include <geometry_msgs/msg/pose.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/empty.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>

class ArmMoveitDriver : public rclcpp::Node
{
public:
  ArmMoveitDriver() : Node("arm_moveit_driver")
  {
    RCLCPP_INFO(this->get_logger(),"constructor start");

    // 目標関節角
    subscription_goal_joints_ = this->create_subscription<sensor_msgs::msg::JointState>("goal_joints", 1,
      std::bind(&ArmMoveitDriver::goalJointsCallback, this, std::placeholders::_1));

    subscription_pose_ = this->create_subscription<geometry_msgs::msg::Pose>("goal_pose", 1,
      std::bind(&ArmMoveitDriver::goalPoseCallback, this, std::placeholders::_1));
    
    // 目標euler_goal_pose
    subscription_euler_goal_pose_ = this->create_subscription<flamingo_grp_msgs::msg::EulerPoseStamped>("euler_goal_pose", 1,
      std::bind(&ArmMoveitDriver::eulerGoalPoseCallback, this, std::placeholders::_1));
    
    // 目標euler_way_and_end_pose
    subscription_euler_way_and_end_pose_ = this->create_subscription<flamingo_grp_msgs::msg::EulerWayEndPoseStamped>("euler_way_and_end_pose", 1,
      std::bind(&ArmMoveitDriver::eulerWayAndEndPoseCallback, this, std::placeholders::_1));

    // publisher
    publisher_joint_trajectory_ = this->create_publisher<trajectory_msgs::msg::JointTrajectory>("joint_trajectory", 1);
    RCLCPP_INFO(this->get_logger(),"constructor end");
  }

  void init() {
    // constructor外で行う
    RCLCPP_INFO(this->get_logger(),"init start");
    rclcpp::Node::SharedPtr node_shared_ptr = this->shared_from_this();

    this->declare_parameter<std::string>("move_group_namespace", "");
    this->declare_parameter<std::string>("group_name", "");

    std::string move_group_namespace;
    this->get_parameter("move_group_namespace", move_group_namespace);
    this->get_parameter("group_name", group_name_);
    
    moveit::planning_interface::MoveGroupInterface::Options options(group_name_, "robot_description", move_group_namespace);
    move_group_ = std::make_shared<moveit::planning_interface::MoveGroupInterface>(this->shared_from_this(), options);

    move_group_->startStateMonitor();
    move_group_->setPlanningTime(10.0);
    RCLCPP_INFO(this->get_logger(),"init end");
  }
 
private:
  void setPose(const geometry_msgs::msg::Point &point, const geometry_msgs::msg::Vector3 &vector3, geometry_msgs::msg::Pose &target_pose) {
    target_pose.position.x = point.x;
    target_pose.position.y = point.y;
    target_pose.position.z = point.z;
    // euler to quaternion
    tf2::Quaternion quaternion;
    quaternion.setRPY(vector3.x, vector3.y, vector3.z); // roll, pitch, yaw
    target_pose.orientation.x = quaternion.x();
    target_pose.orientation.y = quaternion.y();
    target_pose.orientation.z = quaternion.z();
    target_pose.orientation.w = quaternion.w();
    normalizePoseOrientation(target_pose);
  }    

  void normalizePoseOrientation(geometry_msgs::msg::Pose &target) {
    double norm = sqrt(target.orientation.x*target.orientation.x + target.orientation.y * target.orientation.y + target.orientation.z * target.orientation.z + target.orientation.w * target.orientation.w);
    target.orientation.x /= norm;
    target.orientation.y /= norm;
    target.orientation.z /= norm;
    target.orientation.w /= norm;
  }

  void moveToPose(const geometry_msgs::msg::Pose &target_pose)
  {
    moveit::core::RobotStatePtr current_state = move_group_->getCurrentState(5);
    move_group_->setPlanningTime(10.0);
    move_group_->setPoseTarget(target_pose);
    moveit::planning_interface::MoveGroupInterface::Plan my_plan;
    bool success = (move_group_->plan(my_plan) == moveit::core::MoveItErrorCode::SUCCESS);

    if (success == moveit::core::MoveItErrorCode::SUCCESS)
    {
      RCLCPP_INFO(this->get_logger(), "Movement succeeded");
      publisher_joint_trajectory_->publish(my_plan.trajectory_.joint_trajectory);
      // move_group_->execute(my_plan);
    }
    else
    {
      RCLCPP_ERROR(this->get_logger(), "Movement failed");
    }
  }

  void moveToJoint(const std::vector<double>& goal_joints)
  {
    moveit::planning_interface::MoveGroupInterface::Plan my_plan;

    move_group_->setJointValueTarget(goal_joints);
    bool success = (move_group_->plan(my_plan) == moveit::core::MoveItErrorCode::SUCCESS);

    if (success == moveit::core::MoveItErrorCode::SUCCESS)
    {
      RCLCPP_INFO(this->get_logger(), "Arm movement succeeded");
      publisher_joint_trajectory_->publish(my_plan.trajectory_.joint_trajectory);
      // move_group_->execute(my_plan);
    }
    else
    {
      RCLCPP_ERROR(this->get_logger(), "Arm movement failed");
    }    
  }

  void goalJointsCallback(const sensor_msgs::msg::JointState::SharedPtr msg) {
    moveToJoint(msg->position);
  }

  void goalPoseCallback(const geometry_msgs::msg::Pose msg) {
    geometry_msgs::msg::Pose target = msg;
    normalizePoseOrientation(target);
    moveToPose(target);
  }

  void eulerGoalPoseCallback(const flamingo_grp_msgs::msg::EulerPoseStamped msg) {
    // movetoPoseを利用
    geometry_msgs::msg::Pose target_pose;
    setPose(msg.point, msg.vector, target_pose);
    moveToPose(target_pose);
  }

  void eulerWayAndEndPoseCallback(const flamingo_grp_msgs::msg::EulerWayEndPoseStamped msg) {
    geometry_msgs::msg::Pose way_pose;
    setPose(msg.way_point, msg.way_vector, way_pose);
    moveToPose(way_pose);

    geometry_msgs::msg::Pose end_pose;
    setPose(msg.end_point, msg.end_vector, end_pose);
    moveToPose(end_pose);
  }

  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr subscription_;
  std::shared_ptr<moveit::planning_interface::MoveGroupInterface> move_group_;

  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr subscription_goal_joints_;
  rclcpp::Subscription<geometry_msgs::msg::Pose>::SharedPtr subscription_pose_;
  rclcpp::Subscription<flamingo_grp_msgs::msg::EulerPoseStamped>::SharedPtr subscription_euler_goal_pose_;
  rclcpp::Subscription<flamingo_grp_msgs::msg::EulerWayEndPoseStamped>::SharedPtr subscription_euler_way_and_end_pose_;

  rclcpp::Publisher<trajectory_msgs::msg::JointTrajectory>::SharedPtr publisher_joint_trajectory_;
  std::string group_name_;
};


int main(int argc, char **argv)
{
  rclcpp::init(argc, argv);

  auto node = std::make_shared<ArmMoveitDriver>();
  node->init();

  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  executor.spin();

  rclcpp::shutdown();
  return 0;
}
