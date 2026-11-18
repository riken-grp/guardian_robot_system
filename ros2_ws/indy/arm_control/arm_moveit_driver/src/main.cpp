#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit/planning_scene/planning_scene.h>
#include <moveit/planning_scene_interface/planning_scene_interface.h>
#include <moveit/robot_state/robot_state.h>
#include <rclcpp/rclcpp.hpp>

#include "flamingo_grp_msgs/msg/euler_pose_stamped.hpp"
#include "flamingo_grp_msgs/msg/euler_way_end_pose_stamped.hpp"
#include <geometry_msgs/msg/point.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include <moveit_msgs/msg/collision_object.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <shape_msgs/msg/solid_primitive.hpp>
#include <std_msgs/msg/empty.hpp>
#include <trajectory_msgs/msg/joint_trajectory.hpp>

#include <Eigen/Geometry>
#include <limits>
#include <mutex>
#include <random>

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

    // 手先位置制御: KDL は宣言済みのパラメータしか読まないため、IK ソルバを読み込む MoveGroupInterface の生成前に宣言する
    // （値は launch で渡す kinematics_pose_ik.yaml の "<group>.position_only_ik"。move_group には影響しない）
    this->declare_parameter<bool>(group_name_ + ".position_only_ik", false);

    moveit::planning_interface::MoveGroupInterface::Options options(group_name_, "robot_description", move_group_namespace);
    move_group_ = std::make_shared<moveit::planning_interface::MoveGroupInterface>(this->shared_from_this(), options);

    move_group_->startStateMonitor();
    move_group_->setPlanningTime(10.0);

    initPoseControl();
    RCLCPP_INFO(this->get_logger(),"init end");
  }

private:
  // ===== 手先位置制御 =====
  // 腕は 4 軸のため、手先は位置（3 自由度）のみを指定できる。姿勢成分は無視する。
  // 本ノード内で IK・関節制限・胴体干渉を判定し、得た関節角を既存の moveToJoint に渡す。
  // move_group の設定（URDF/SRDF/kinematics/joint_limits）は一切変えないため、goal_joints の挙動は従来どおり。
  //
  // 関節角の表現は 2 種類ある:
  //   指令値  : goal_joints / joints / joint_trajectory で使う値（従来の関節角）
  //   実角度  : URDF 上の角度。arm_motor_control の gain のうち大きさ分を意図的に動きの大きさの変更に使っているため
  //             実角度 = |gain| × 指令値（符号は回転の向きの補正）
  void initPoseControl()
  {
    this->declare_parameter<std::vector<std::string>>("motor_joint_names", std::vector<std::string>());
    this->declare_parameter<std::vector<double>>("motor_gain", std::vector<double>());
    this->declare_parameter<std::vector<double>>("motor_default_offset", std::vector<double>());
    this->declare_parameter<std::vector<double>>("motor_min_position", std::vector<double>());
    this->declare_parameter<std::vector<double>>("motor_max_position", std::vector<double>());
    this->declare_parameter<double>("limit_margin", 0.05);              // [rad] 指令値側の可動範囲の内側余裕
    this->declare_parameter<double>("ik_timeout", 0.05);                // [s] IK 1 回あたり
    this->declare_parameter<int>("ik_attempts", 20);                    // IK の試行回数（最も現在角に近い解を採用）
    this->declare_parameter<double>("ik_position_tolerance", 0.005);   // [m] 解の手先位置の許容誤差
    this->declare_parameter<std::string>("mount_parent_frame", "");
    this->declare_parameter<std::vector<double>>("mount_xyz", std::vector<double>());
    this->declare_parameter<std::vector<double>>("mount_rpy", std::vector<double>());
    this->declare_parameter<std::vector<std::string>>("collision_box_names", std::vector<std::string>());
    this->declare_parameter<std::vector<double>>("collision_box_sizes", std::vector<double>());
    this->declare_parameter<std::vector<double>>("collision_box_poses", std::vector<double>());
    this->declare_parameter<double>("collision_padding", 0.0);
    this->declare_parameter<std::vector<std::string>>("collision_allowed_links", std::vector<std::string>());

    pose_enabled_ = false;

    std::vector<std::string> motor_joint_names;
    std::vector<double> gain, default_offset, motor_min, motor_max;
    this->get_parameter("motor_joint_names", motor_joint_names);
    this->get_parameter("motor_gain", gain);
    this->get_parameter("motor_default_offset", default_offset);
    this->get_parameter("motor_min_position", motor_min);
    this->get_parameter("motor_max_position", motor_max);
    this->get_parameter("limit_margin", limit_margin_);
    this->get_parameter("ik_timeout", ik_timeout_);
    this->get_parameter("ik_attempts", ik_attempts_);
    this->get_parameter("ik_position_tolerance", ik_position_tolerance_);

    robot_model_ = move_group_->getRobotModel();
    if (!robot_model_) {
      RCLCPP_ERROR(this->get_logger(), "手先制御無効: robot model を取得できない");
      return;
    }
    jmg_ = robot_model_->getJointModelGroup(group_name_);
    if (!jmg_ || !jmg_->getSolverInstance()) {
      RCLCPP_ERROR(this->get_logger(), "手先制御無効: group '%s' の IK ソルバを読み込めない（robot_description_kinematics を確認）",
                   group_name_.c_str());
      return;
    }
    const auto& tips = jmg_->getSolverInstance()->getTipFrames();
    if (tips.empty()) {
      RCLCPP_ERROR(this->get_logger(), "手先制御無効: IK ソルバの tip frame がない");
      return;
    }
    tip_link_ = tips.front();

    // arm_motor_control.yaml の値を関節名で対応付ける（既定値では動かさない）
    const size_t n = motor_joint_names.size();
    if (n == 0 || gain.size() != n || default_offset.size() != n || motor_min.size() != n || motor_max.size() != n) {
      RCLCPP_ERROR(this->get_logger(), "手先制御無効: arm_motor_control のパラメータ（gain/offset/可動範囲）を取得できない");
      return;
    }
    const auto& group_joints = jmg_->getActiveJointModelNames();
    scale_.assign(group_joints.size(), 0.0);
    cmd_min_.assign(group_joints.size(), 0.0);
    cmd_max_.assign(group_joints.size(), 0.0);
    for (size_t i = 0; i < group_joints.size(); i++) {
      auto it = std::find(motor_joint_names.begin(), motor_joint_names.end(), group_joints[i]);
      if (it == motor_joint_names.end()) {
        RCLCPP_ERROR(this->get_logger(), "手先制御無効: 関節 %s が arm_motor_control のパラメータにない", group_joints[i].c_str());
        return;
      }
      const size_t k = std::distance(motor_joint_names.begin(), it);
      if (gain[k] == 0.0) {
        RCLCPP_ERROR(this->get_logger(), "手先制御無効: 関節 %s の gain が 0", group_joints[i].c_str());
        return;
      }
      scale_[i] = std::abs(gain[k]);
      // arm_motor_control と同じ式でモータ側の可動範囲を指令値側に換算し、内側に余裕をとる
      double a = (motor_min[k] - default_offset[k]) / gain[k];
      double b = (motor_max[k] - default_offset[k]) / gain[k];
      cmd_min_[i] = std::min(a, b) + limit_margin_;
      cmd_max_[i] = std::max(a, b) - limit_margin_;
      RCLCPP_INFO(this->get_logger(), "手先制御 %s: 実角度 = %.3f x 指令値, 指令値範囲 [%.3f, %.3f]",
                  group_joints[i].c_str(), scale_[i], cmd_min_[i], cmd_max_[i]);
    }

    // 干渉判定用の planning scene（本ノード内だけで使う。move_group の scene には入れない）
    scene_ = std::make_shared<planning_scene::PlanningScene>(robot_model_);
    if (!initMountAndCollision()) {
      // 胴体干渉を判定できない状態では手先指令を受け付けない（関節角指令には影響しない）
      RCLCPP_ERROR(this->get_logger(), "手先制御無効: 取り付け位置・干渉判定の箱（amr_description/urdf/arm_mount.yaml）を読めない");
      return;
    }

    // 現在角は専用の callback group で joints を直接購読して保持する。
    // 指令の callback（default group）の中で MoveGroupInterface::getCurrentState() を待つと、
    // 同じ group の state monitor の受信が走らず取得できないため。
    this->declare_parameter<double>("joint_state_timeout", 1.0);   // [s] これより古い現在角では手先指令を中止
    this->get_parameter("joint_state_timeout", joint_state_timeout_);
    joints_callback_group_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    rclcpp::SubscriptionOptions joints_opt;
    joints_opt.callback_group = joints_callback_group_;
    subscription_joints_ = this->create_subscription<sensor_msgs::msg::JointState>("joints", 10,
      std::bind(&ArmMoveitDriver::jointsCallback, this, std::placeholders::_1), joints_opt);

    pose_enabled_ = true;
    RCLCPP_INFO(this->get_logger(), "手先位置制御 有効 (tip: %s, 胴体基準フレーム: %s)",
                tip_link_.c_str(), mount_enabled_ ? mount_parent_frame_.c_str() : "なし");
  }

  static Eigen::Isometry3d makeTransform(const double* xyz, const double* rpy)
  {
    Eigen::Isometry3d t = Eigen::Isometry3d::Identity();
    t.translation() = Eigen::Vector3d(xyz[0], xyz[1], xyz[2]);
    // URDF の rpy（固定軸 X→Y→Z）
    t.linear() = (Eigen::AngleAxisd(rpy[2], Eigen::Vector3d::UnitZ()) *
                  Eigen::AngleAxisd(rpy[1], Eigen::Vector3d::UnitY()) *
                  Eigen::AngleAxisd(rpy[0], Eigen::Vector3d::UnitX())).toRotationMatrix();
    return t;
  }

  bool initMountAndCollision()
  {
    mount_enabled_ = false;
    std::vector<double> mount_xyz, mount_rpy, box_sizes, box_poses;
    std::vector<std::string> box_names, allowed_links;
    double padding = 0.0;
    this->get_parameter("mount_parent_frame", mount_parent_frame_);
    this->get_parameter("mount_xyz", mount_xyz);
    this->get_parameter("mount_rpy", mount_rpy);
    this->get_parameter("collision_box_names", box_names);
    this->get_parameter("collision_box_sizes", box_sizes);
    this->get_parameter("collision_box_poses", box_poses);
    this->get_parameter("collision_padding", padding);
    this->get_parameter("collision_allowed_links", allowed_links);

    if (mount_parent_frame_.empty() || mount_xyz.size() != 3 || mount_rpy.size() != 3) {
      return false;
    }
    // 腕の base_link を親フレームから見た変換
    parent_to_arm_ = makeTransform(mount_xyz.data(), mount_rpy.data());
    mount_enabled_ = true;

    box_names.erase(std::remove(box_names.begin(), box_names.end(), std::string()), box_names.end());
    if (box_names.empty() || box_sizes.size() < box_names.size() * 3 || box_poses.size() < box_names.size() * 6) {
      return false;
    }
    const Eigen::Isometry3d arm_to_parent = parent_to_arm_.inverse();
    for (size_t i = 0; i < box_names.size(); i++) {
      moveit_msgs::msg::CollisionObject obj;
      obj.id = box_names[i];
      obj.header.frame_id = robot_model_->getModelFrame();   // 腕モデルの world（= base_link）
      obj.operation = moveit_msgs::msg::CollisionObject::ADD;
      shape_msgs::msg::SolidPrimitive prim;
      prim.type = shape_msgs::msg::SolidPrimitive::BOX;
      prim.dimensions = {box_sizes[i * 3] + 2 * padding, box_sizes[i * 3 + 1] + 2 * padding, box_sizes[i * 3 + 2] + 2 * padding};
      const Eigen::Isometry3d box_in_arm = arm_to_parent * makeTransform(&box_poses[i * 6], &box_poses[i * 6 + 3]);
      geometry_msgs::msg::Pose pose;
      pose.position.x = box_in_arm.translation().x();
      pose.position.y = box_in_arm.translation().y();
      pose.position.z = box_in_arm.translation().z();
      Eigen::Quaterniond q(box_in_arm.linear());
      pose.orientation.x = q.x();
      pose.orientation.y = q.y();
      pose.orientation.z = q.z();
      pose.orientation.w = q.w();
      obj.primitives.push_back(prim);
      obj.primitive_poses.push_back(pose);
      scene_->processCollisionObjectMsg(obj);
      for (const auto& link : allowed_links) {
        if (!link.empty()) {
          scene_->getAllowedCollisionMatrixNonConst().setEntry(obj.id, link, true);
        }
      }
      RCLCPP_INFO(this->get_logger(), "干渉判定の箱 '%s' を追加 (腕基準 中心 [%.3f, %.3f, %.3f])",
                  obj.id.c_str(), pose.position.x, pose.position.y, pose.position.z);
    }
    return true;
  }

  // 目標点を腕基準（腕モデルの world = base_link）に変換する。frame_id の規則:
  //   空 / 腕モデルの world / base_link : 腕基準（従来どおり）
  //   mount_parent_frame（例: <ROBOT_NAME>_body_link） : 取り付け位置で変換
  //   それ以外 : 拒否
  bool toArmFrame(const std::string& frame_id, const geometry_msgs::msg::Point& in, Eigen::Vector3d& out)
  {
    const Eigen::Vector3d p(in.x, in.y, in.z);
    if (frame_id.empty() || frame_id == robot_model_->getModelFrame() || frame_id == "base_link") {
      out = p;
      return true;
    }
    if (mount_enabled_ && frame_id == mount_parent_frame_) {
      out = parent_to_arm_.inverse() * p;
      return true;
    }
    RCLCPP_ERROR(this->get_logger(), "未対応の frame_id '%s'（空・base_link・%s のみ受け付ける）",
                 frame_id.c_str(), mount_enabled_ ? mount_parent_frame_.c_str() : "(取り付け未設定)");
    return false;
  }

  void jointsCallback(const sensor_msgs::msg::JointState::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lock(joints_mutex_);
    latest_joints_ = *msg;
    latest_joints_time_ = this->now();
  }

  // 現在の関節角（指令値、group の関節順）。joints の受信が古い・関節が欠けている場合は false
  bool currentCommand(std::vector<double>& out)
  {
    std::lock_guard<std::mutex> lock(joints_mutex_);
    if (latest_joints_.name.empty() || (this->now() - latest_joints_time_).seconds() > joint_state_timeout_) {
      return false;
    }
    const auto& group_joints = jmg_->getActiveJointModelNames();
    out.assign(group_joints.size(), 0.0);
    for (size_t i = 0; i < group_joints.size(); i++) {
      auto it = std::find(latest_joints_.name.begin(), latest_joints_.name.end(), group_joints[i]);
      const size_t k = std::distance(latest_joints_.name.begin(), it);
      if (it == latest_joints_.name.end() || k >= latest_joints_.position.size()) return false;
      out[i] = latest_joints_.position[k];
    }
    return true;
  }

  bool withinCommandLimits(const std::vector<double>& cmd) const
  {
    for (size_t i = 0; i < cmd.size(); i++) {
      if (cmd[i] < cmd_min_[i] || cmd[i] > cmd_max_[i]) return false;
    }
    return true;
  }

  // 目標位置（腕基準）に対する関節角（指令値）を求める。
  // seed_cmd: 初期値とする関節角（指令値）。空なら現在角を使う。現在角が取れなければ失敗にする
  // （モータは最終点へ直行するため、無関係な姿勢から解くと腕が大きく振れる）。
  bool solvePosition(const Eigen::Vector3d& target, const std::vector<double>& seed_cmd, std::vector<double>& out_cmd)
  {
    if (!pose_enabled_) {
      RCLCPP_ERROR(this->get_logger(), "手先位置制御は無効（起動時のログを確認）");
      return false;
    }
    std::vector<double> current_cmd;
    if (!currentCommand(current_cmd)) {
      RCLCPP_ERROR(this->get_logger(), "現在の関節角（joints）を取得できない、または古いため手先指令を中止");
      return false;
    }
    const size_t n = scale_.size();
    std::vector<double> ref_cmd = seed_cmd.empty() ? current_cmd : seed_cmd;
    if (ref_cmd.size() != n) return false;
    std::vector<double> ref_phys(n);
    for (size_t i = 0; i < n; i++) ref_phys[i] = ref_cmd[i] * scale_[i];

    moveit::core::RobotState state(robot_model_);
    state.setToDefaultValues();
    geometry_msgs::msg::Pose pose;   // 姿勢は position_only_ik のため使われない
    pose.position.x = target.x();
    pose.position.y = target.y();
    pose.position.z = target.z();
    pose.orientation.w = 1.0;

    // 現在姿勢がすでに干渉判定に掛かっている場合は、組み合わせをログに出す（取り付け値・箱・許可リストの見直し用）
    {
      std::vector<double> cur_phys(n);
      for (size_t i = 0; i < n; i++) cur_phys[i] = current_cmd[i] * scale_[i];
      state.setJointGroupPositions(jmg_, cur_phys);
      state.update();
      collision_detection::CollisionRequest req;
      collision_detection::CollisionResult res;
      req.contacts = true;
      req.max_contacts = 20;
      req.group_name = group_name_;
      scene_->checkCollision(req, res, state);
      if (res.collision) {
        for (const auto& c : res.contacts) {
          RCLCPP_WARN(this->get_logger(), "現在姿勢で干渉判定に掛かっている: %s - %s", c.first.first.c_str(), c.first.second.c_str());
        }
      }
    }

    // 妥当性判定: 指令値側の可動範囲と、自己干渉・胴体干渉
    int reject_limit = 0, reject_collision = 0, ik_fail = 0, reject_tolerance = 0;
    auto valid = [this, n, &reject_limit, &reject_collision](moveit::core::RobotState* s, const moveit::core::JointModelGroup* g, const double* phys) {
      std::vector<double> cmd(n);
      for (size_t i = 0; i < n; i++) cmd[i] = phys[i] / scale_[i];
      if (!withinCommandLimits(cmd)) { reject_limit++; return false; }
      s->setJointGroupPositions(g, phys);
      s->update();
      if (scene_->isStateColliding(*s, group_name_)) { reject_collision++; return false; }
      return true;
    };

    std::mt19937 rng(std::random_device{}());
    bool found = false;
    double best_dist = std::numeric_limits<double>::max();
    std::vector<double> best_phys;
    for (int attempt = 0; attempt < std::max(1, ik_attempts_); attempt++) {
      std::vector<double> seed_phys(n);
      if (attempt == 0) {
        seed_phys = ref_phys;
      } else {
        for (size_t i = 0; i < n; i++) {
          std::uniform_real_distribution<double> d(cmd_min_[i], cmd_max_[i]);
          seed_phys[i] = d(rng) * scale_[i];
        }
      }
      state.setJointGroupPositions(jmg_, seed_phys);
      state.update();
      if (!state.setFromIK(jmg_, pose, ik_timeout_, valid)) { ik_fail++; continue; }
      state.update();
      const double err = (state.getGlobalLinkTransform(tip_link_).translation() - target).norm();
      if (err > ik_position_tolerance_) { reject_tolerance++; continue; }
      std::vector<double> phys;
      state.copyJointGroupPositions(jmg_, phys);
      double dist = 0.0;
      for (size_t i = 0; i < n; i++) dist += (phys[i] - ref_phys[i]) * (phys[i] - ref_phys[i]);
      if (dist < best_dist) {
        best_dist = dist;
        best_phys = phys;
        found = true;
      }
    }
    if (!found) {
      RCLCPP_ERROR(this->get_logger(), "目標位置 [%.3f, %.3f, %.3f]（腕基準）への解なし（到達範囲外・可動範囲外・胴体干渉のいずれか）"
                   " 内訳: IK失敗 %d / 可動範囲外の候補 %d / 干渉する候補 %d / 位置誤差超過 %d",
                   target.x(), target.y(), target.z(), ik_fail, reject_limit, reject_collision, reject_tolerance);
      return false;
    }
    out_cmd.resize(n);
    for (size_t i = 0; i < n; i++) out_cmd[i] = best_phys[i] / scale_[i];
    RCLCPP_INFO(this->get_logger(), "手先目標 [%.3f, %.3f, %.3f] -> 関節角(指令値) [%.3f, %.3f, %.3f, %.3f]",
                target.x(), target.y(), target.z(), out_cmd[0], out_cmd[1], out_cmd[2], out_cmd[3]);
    return true;
  }

  void warnOrientationIgnored()
  {
    RCLCPP_WARN_ONCE(this->get_logger(), "腕は 4 軸のため手先姿勢（orientation / roll・pitch・yaw）は無視し、位置のみで制御する");
  }

  void moveToPosition(const std::string& frame_id, const geometry_msgs::msg::Point& point)
  {
    Eigen::Vector3d target;
    std::vector<double> cmd;
    if (!toArmFrame(frame_id, point, target)) return;
    if (!solvePosition(target, {}, cmd)) return;
    moveToJoint(cmd);
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

  // goal_pose: 腕基準の手先位置（orientation は無視）
  void goalPoseCallback(const geometry_msgs::msg::Pose msg) {
    warnOrientationIgnored();
    moveToPosition("", msg.position);
  }

  // euler_goal_pose: header.frame_id 基準の手先位置（vector = roll/pitch/yaw は無視）
  void eulerGoalPoseCallback(const flamingo_grp_msgs::msg::EulerPoseStamped msg) {
    warnOrientationIgnored();
    moveToPosition(msg.header.frame_id, msg.point);
  }

  // euler_way_and_end_pose: 経由点→終点の順に指令（姿勢は無視）。終点の IK は経由点の解を初期値にする
  void eulerWayAndEndPoseCallback(const flamingo_grp_msgs::msg::EulerWayEndPoseStamped msg) {
    warnOrientationIgnored();
    Eigen::Vector3d way_target, end_target;
    std::vector<double> way_cmd, end_cmd;
    if (!toArmFrame(msg.header.frame_id, msg.way_point, way_target)) return;
    if (!toArmFrame(msg.header.frame_id, msg.end_point, end_target)) return;
    if (!solvePosition(way_target, {}, way_cmd)) return;
    if (!solvePosition(end_target, way_cmd, end_cmd)) return;
    moveToJoint(way_cmd);
    moveToJoint(end_cmd);
  }

  rclcpp::Subscription<std_msgs::msg::Empty>::SharedPtr subscription_;
  std::shared_ptr<moveit::planning_interface::MoveGroupInterface> move_group_;

  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr subscription_goal_joints_;
  rclcpp::Subscription<geometry_msgs::msg::Pose>::SharedPtr subscription_pose_;
  rclcpp::Subscription<flamingo_grp_msgs::msg::EulerPoseStamped>::SharedPtr subscription_euler_goal_pose_;
  rclcpp::Subscription<flamingo_grp_msgs::msg::EulerWayEndPoseStamped>::SharedPtr subscription_euler_way_and_end_pose_;

  rclcpp::Publisher<trajectory_msgs::msg::JointTrajectory>::SharedPtr publisher_joint_trajectory_;
  std::string group_name_;

  // 手先位置制御
  bool pose_enabled_ = false;
  bool mount_enabled_ = false;
  moveit::core::RobotModelConstPtr robot_model_;
  const moveit::core::JointModelGroup* jmg_ = nullptr;
  std::string tip_link_;
  std::vector<double> scale_;     // 実角度 = scale × 指令値
  std::vector<double> cmd_min_;   // 指令値側の可動範囲（余裕込み）
  std::vector<double> cmd_max_;
  double limit_margin_ = 0.05;
  double ik_timeout_ = 0.05;
  int ik_attempts_ = 20;
  double ik_position_tolerance_ = 0.005;
  std::string mount_parent_frame_;
  Eigen::Isometry3d parent_to_arm_ = Eigen::Isometry3d::Identity();
  planning_scene::PlanningScenePtr scene_;
  rclcpp::CallbackGroup::SharedPtr joints_callback_group_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr subscription_joints_;
  std::mutex joints_mutex_;
  sensor_msgs::msg::JointState latest_joints_;
  rclcpp::Time latest_joints_time_{0, 0, RCL_ROS_TIME};
  double joint_state_timeout_ = 1.0;
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
