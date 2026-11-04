#include "vel_filter/velfilter.hpp"
#include <mutex>

namespace vel_filter
{
VelFilter::VelFilter() : Node("vel_filter_node")
{
  // Get robot name from environment variable
  const char* robot_name_env = std::getenv("ROBOT_NAME");
  if (robot_name_env == nullptr) {
    RCLCPP_ERROR(this->get_logger(), "failed to get robot name");
    return;
  }
  robot_name_ = std::string(robot_name_env);

  // Declare parameters
  this->declare_parameter("robot_height", 1.5);
  this->declare_parameter("robot_width", 0.7);
  this->declare_parameter("max_velocity", 0.7);
  this->declare_parameter("min_back_velocity", -0.1);
  this->declare_parameter("max_recog_range", 10.0);
  this->declare_parameter("min_obstacle_range", 0.5);
  this->declare_parameter("max_obstacle_range", 1.5);
  this->declare_parameter("max_scan_obstacle_range", 0.3);
  this->declare_parameter("min_cliff_range", 0.7);
  this->declare_parameter("max_cliff_range", 2.0);
  this->declare_parameter("filtering_factor", 0.5);

  // Get parameter values
  robot_height_ = this->get_parameter("robot_height").as_double();
  robot_width_ = this->get_parameter("robot_width").as_double();
  max_velocity_ = this->get_parameter("max_velocity").as_double();
  min_back_velocity_ = this->get_parameter("min_back_velocity").as_double();
  max_recog_range_ = this->get_parameter("max_recog_range").as_double();
  min_obstacle_range_ = this->get_parameter("min_obstacle_range").as_double();
  max_obstacle_range_ = this->get_parameter("max_obstacle_range").as_double();
  max_scan_obstacle_range_ = this->get_parameter("max_scan_obstacle_range").as_double();
  min_cliff_range_ = this->get_parameter("min_cliff_range").as_double();
  max_cliff_range_ = this->get_parameter("max_cliff_range").as_double();
  filtering_factor_ = this->get_parameter("filtering_factor").as_double();

  // Initialize state variables
  min_x_bu_ = max_recog_range_;
  min_x_td_ = max_recog_range_;
  min_y_bu_ = max_recog_range_;
  min_y_td_ = max_recog_range_;
  min_range_bu_ = max_recog_range_;
  min_range_td_ = max_recog_range_;

  front_min_x_scan_ = max_recog_range_;
  front_min_y_scan_ = max_recog_range_;
  front_min_range_scan_ = max_recog_range_;
  back_min_x_scan_ = -max_recog_range_;
  back_min_y_scan_ = max_recog_range_;
  back_min_range_scan_ = max_recog_range_;

  default_max_velocity_ = max_velocity_;

  // td_camera_info_とbu_camera_info_の初期化(サイズ4のベクトル)
  td_camera_info_ = std::vector<double>(4, 0.0);
  bu_camera_info_ = std::vector<double>(4, 0.0);

  // Initialize TF2
  tf_buffer_ = std::make_unique<tf2_ros::Buffer>(this->get_clock());
  tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

  td_transform_inited_ = false;
  bu_transform_inited_ = false;

  // Create callback groups
  velocity_cb_group_ = this->create_callback_group(
    rclcpp::CallbackGroupType::MutuallyExclusive);
  camera_bu_cb_group_ = this->create_callback_group(
    rclcpp::CallbackGroupType::MutuallyExclusive);
  camera_td_cb_group_ = this->create_callback_group(
    rclcpp::CallbackGroupType::MutuallyExclusive);
  scan_cb_group_ = this->create_callback_group(
    rclcpp::CallbackGroupType::MutuallyExclusive);

  // Create subscription options
  rclcpp::SubscriptionOptions velocity_options;
  velocity_options.callback_group = velocity_cb_group_;
  
  rclcpp::SubscriptionOptions camera_bu_options;
  camera_bu_options.callback_group = camera_bu_cb_group_;
  
  rclcpp::SubscriptionOptions camera_td_options;
  camera_td_options.callback_group = camera_td_cb_group_;

  rclcpp::SubscriptionOptions scan_options;
  scan_options.callback_group = scan_cb_group_;

  // Create publisher
  filtered_vel_pub_ = this->create_publisher<geometry_msgs::msg::Twist>(
    "rover/cmd_vel_filtered", 10);
  nearest_camera_point_pub_ = this->create_publisher<geometry_msgs::msg::Vector3>(
    "rover/nearest_camera_point", 10);
  nearest_scan_point_pub_ = this->create_publisher<geometry_msgs::msg::Vector3>(
    "rover/nearest_scan_point", 10);

  // camera_infoをサブスクライブ
  // camera_bu_info_sub_ = this->create_subscription<sensor_msgs::msg::CameraInfo>(
  //   robot_name_ + "_camera_bu/depth/camera_info",
  //   rclcpp::SensorDataQoS(),
  //   std::bind(&VelFilter::bu_camera_info_callback, this, std::placeholders::_1),
  //   camera_bu_options);
  
  camera_td_info_sub_ = this->create_subscription<sensor_msgs::msg::CameraInfo>(
    robot_name_ + "_camera_td/depth/camera_info",
    rclcpp::SensorDataQoS(),
    std::bind(&VelFilter::td_camera_info_callback, this, std::placeholders::_1),
    camera_td_options);
  
  // imageをサブスクライブ
  // camera_bu_raw_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
  //   robot_name_ + "_camera_bu/depth/image_rect_raw",
  //   rclcpp::SensorDataQoS(),
  //   std::bind(&VelFilter::bu_image_callback, this, std::placeholders::_1),
  //   camera_bu_options);

  camera_td_raw_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
    robot_name_ + "_camera_td/depth/image_rect_raw",
    rclcpp::QoS(1).best_effort().durability_volatile(),
    std::bind(&VelFilter::td_image_callback, this, std::placeholders::_1),
    camera_td_options);

  vel_cmd_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
    "rover/cmd_vel",
    10,
    std::bind(&VelFilter::vel_cmd_callback, this, std::placeholders::_1),
    velocity_options);
  
  scan_sub_ = this->create_subscription<sensor_msgs::msg::LaserScan>(
    "rover/scan",
    rclcpp::QoS(20).best_effort(),
    std::bind(&VelFilter::scan_callback, this, std::placeholders::_1),
    scan_options);

  max_vel_cmd_sub_ = this->create_subscription<std_msgs::msg::Float64>(
    "vel_filter/set_max_velocity",
    rclcpp::QoS(1).best_effort().durability_volatile(),
    std::bind(&VelFilter::max_vel_cmd_callback, this, std::placeholders::_1)); 

  timer_main_ = this->create_wall_timer(
    std::chrono::milliseconds(100),
    std::bind(&VelFilter::timer_callback, this));

  last_camera_time_ = std::chrono::system_clock::time_point(std::chrono::seconds(0));
  last_vel_time_ = std::chrono::system_clock::time_point(std::chrono::seconds(0));
  last_max_vel_time_ = std::chrono::system_clock::time_point(std::chrono::seconds(0));
  last_twist_cnt_ = 0;
  last_target_vel_ = 0.0;
  last_target_angle_ = 0.0;
}

void VelFilter::bu_image_callback(const sensor_msgs::msg::Image::SharedPtr msg)
{
  last_camera_time_ = std::chrono::system_clock::now();
  geometry_msgs::msg::TransformStamped transform;
  if (!bu_transform_inited_) {
    try {
        transform = tf_buffer_->lookupTransform(
          robot_name_ + "_base_link",
          msg->header.frame_id,
          tf2::TimePointZero);
        bu_tf_.setOrigin(tf2::Vector3(
          transform.transform.translation.x,
          transform.transform.translation.y,
          transform.transform.translation.z));
        tf2::Quaternion quat(
          transform.transform.rotation.x,
          transform.transform.rotation.y,
          transform.transform.rotation.z,
          transform.transform.rotation.w);
        bu_tf_.setRotation(quat);
        bu_transform_inited_ = true;
        RCLCPP_DEBUG(this->get_logger(), "Succeeded to get transform for BU camera");
    } catch (const tf2::TransformException& ex2) {
      RCLCPP_WARN(this->get_logger(), "Could not transform for BU camera: %s", ex2.what());
    }
  }
  try {
    std::tie(min_range_bu_, min_x_bu_, min_y_bu_) = calc_range_from_image(msg, bu_camera_info_, bu_tf_);
  } catch (const std::exception& e) {
    RCLCPP_ERROR(this->get_logger(), "Failed to convert image to point cloud: %s", e.what());
  }
}

void VelFilter::td_image_callback(const sensor_msgs::msg::Image::SharedPtr msg)
{
  last_camera_time_ = std::chrono::system_clock::now();
  geometry_msgs::msg::TransformStamped transform;
  if (!td_transform_inited_) {
    try {
        transform = tf_buffer_->lookupTransform(
          robot_name_ + "_base_link",
          msg->header.frame_id,
          tf2::TimePointZero);
        td_tf_.setOrigin(tf2::Vector3(
          transform.transform.translation.x,
          transform.transform.translation.y,
          transform.transform.translation.z));
        tf2::Quaternion quat(
          transform.transform.rotation.x,
          transform.transform.rotation.y,
          transform.transform.rotation.z,
          transform.transform.rotation.w);
        td_tf_.setRotation(quat);
        td_transform_inited_ = true;
        RCLCPP_DEBUG(this->get_logger(), "Succeeded to get transform for TD camera");
    } catch (const tf2::TransformException& ex2) {
      RCLCPP_WARN(this->get_logger(), "Could not transform for TD camera: %s", ex2.what());
    }
  }
  try {
    std::tie(min_range_td_, min_x_td_, min_y_td_) = calc_range_from_image(msg, td_camera_info_, td_tf_);
  } catch (const std::exception& e) {
    RCLCPP_ERROR(this->get_logger(), "Failed to convert image to point cloud: %s", e.what());
  }
}

void VelFilter::bu_camera_info_callback(const sensor_msgs::msg::CameraInfo::SharedPtr msg)
{

  // fx, fy, cx, cyを保存
  bu_camera_info_[0] = msg->k[0];
  bu_camera_info_[1] = msg->k[4];
  bu_camera_info_[2] = msg->k[2];
  bu_camera_info_[3] = msg->k[5];
}

void VelFilter::td_camera_info_callback(const sensor_msgs::msg::CameraInfo::SharedPtr msg)
{
  // fx, fy, cx, cyを保存
  td_camera_info_[0] = msg->k[0];
  td_camera_info_[1] = msg->k[4];
  td_camera_info_[2] = msg->k[2];
  td_camera_info_[3] = msg->k[5];
}

void VelFilter::vel_cmd_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
{
  last_vel_time_ = std::chrono::system_clock::now();
  last_twist_cnt_ = 0;
  last_target_vel_ = msg->linear.x;
  last_target_angle_ = msg->angular.z;
}

void VelFilter::max_vel_cmd_callback(const std_msgs::msg::Float64::SharedPtr msg){
  last_max_vel_time_ = std::chrono::system_clock::now();
  max_velocity_ = msg->data;
}

void VelFilter::scan_callback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
{
  float front_min_range = max_obstacle_range_;
  float front_min_x = max_obstacle_range_;
  float front_min_y = max_obstacle_range_;
  float back_min_range = max_obstacle_range_;
  float back_min_x = -max_obstacle_range_;
  float back_min_y = max_obstacle_range_;
  for (size_t i = 0; i < msg->ranges.size(); ++i) {
    float r = msg->ranges[i];
    float angle = msg->angle_min + i * msg->angle_increment;
    float x = r * std::cos(angle);
    float y = r * std::sin(angle);
    if (r < 0.01 || r > max_obstacle_range_) continue; // 無効値除外
    if (x >= 0.0 && r < front_min_range) {
      front_min_range = r;
      front_min_x = x;
      front_min_y = y;
    }
    if (x < 0.0 && r < back_min_range) {
      back_min_range = r;
      back_min_x = x;
      back_min_y = y;
    }
  }
  RCLCPP_DEBUG(rclcpp::get_logger("vel_filter"), "[LaserScan] Front closest: x=%.3f, y=%.3f, range=%.3f", front_min_x, front_min_y, front_min_range);
  RCLCPP_DEBUG(rclcpp::get_logger("vel_filter"), "[LaserScan] Back closest:  x=%.3f, y=%.3f, range=%.3f", back_min_x, back_min_y, back_min_range);

  front_min_x_scan_ = front_min_x;
  front_min_y_scan_ = front_min_y;
  front_min_range_scan_ = front_min_range;
  back_min_x_scan_ = back_min_x;
  back_min_y_scan_ = back_min_y;
  back_min_range_scan_ = back_min_range;
}

std::tuple<double, double> VelFilter::calc_slow_twist()
{
  double target_vel = last_target_vel_;
  double target_angle = last_target_angle_;

  // ToDo: スムーズに減速するように動作確認する
  // double slow_rate = std::max(0.0, (1.0 - last_twist_cnt_ / 3.0));
  double slow_rate = 1.0;

  last_twist_cnt_++;
  double slowed_target_vel = target_vel * slow_rate;
  double slowed_target_angle = target_angle * slow_rate;

  return std::make_tuple(slowed_target_vel, slowed_target_angle);
}


double VelFilter::calc_filtered_velocity(double target_vel)
{
  double min_range;
  double filtered_vel;
  double max_obstacle_range = max_obstacle_range_;

  // Apply filtering logic
  if (target_vel <= 0.0) {
    min_range = back_min_range_scan_;
    max_obstacle_range = min_obstacle_range_ + max_scan_obstacle_range_;  // 後退時は障害物検知範囲を狭める
    filtered_vel = (min_range - min_obstacle_range_) /
                (max_obstacle_range - min_obstacle_range_) * -max_velocity_;
    filtered_vel = std::min(0.0, filtered_vel);
    filtered_vel = std::max(filtered_vel, min_back_velocity_);
    filtered_vel = std::max(filtered_vel, target_vel);
  } else {
    min_range = std::min(min_range_bu_, min_range_td_);

    double camera_coef = (min_range - min_obstacle_range_) / (max_obstacle_range - min_obstacle_range_);
    double scan_coef = (front_min_range_scan_ - min_obstacle_range_) / max_scan_obstacle_range_;
    if (camera_coef > scan_coef) {
      min_range = front_min_range_scan_;
      max_obstacle_range = min_obstacle_range_ + max_scan_obstacle_range_;
    }
    
    if (min_range > max_obstacle_range) {
        filtered_vel = target_vel;
    } else if (min_range < min_obstacle_range_) {
        filtered_vel = 0.0;
    } else {
        filtered_vel = (min_range - min_obstacle_range_) /
                    (max_obstacle_range - min_obstacle_range_) * max_velocity_;
        filtered_vel = std::max(0.0, filtered_vel);
        filtered_vel = std::min(target_vel, filtered_vel);
    }
  }
  return filtered_vel;
}

std::tuple<float, float, float> VelFilter::calc_range_from_image(
  const sensor_msgs::msg::Image::SharedPtr& img_msg,
  const std::vector<double>& camera_info,
  const tf2::Transform& tf)
{
  const uint8_t* data = img_msg->data.data();

  int width = img_msg->width;
  int height = img_msg->height;
  int step = img_msg->step;
  // camera_infoが{0,0,0,0}ならエラーを出す
  if (camera_info == std::vector<double>(4, 0.0)) {
    RCLCPP_WARN(this->get_logger(), "camera_info is not set");
    return std::make_tuple(max_obstacle_range_, 0.0, 0.0);
  }
  float fx = camera_info[0];
  float fy = camera_info[1];
  float cx = camera_info[2];
  float cy = camera_info[3];

  // Transform を回転行列と平行移動ベクトルに事前分解（ループ外で1回のみ）
  const tf2::Matrix3x3& rotation = tf.getBasis();
  const tf2::Vector3& translation = tf.getOrigin();
  
  // 回転行列の各要素を取得（メモリアクセス最適化）
  float r00 = rotation[0][0], r01 = rotation[0][1], r02 = rotation[0][2];
  float r10 = rotation[1][0], r11 = rotation[1][1], r12 = rotation[1][2];
  float r20 = rotation[2][0], r21 = rotation[2][1], r22 = rotation[2][2];
  float tx = translation.x(), ty = translation.y(), tz = translation.z();

  float camera_x, camera_y, camera_z;
  float base_x, base_y, base_z;
  float min_range = max_recog_range_;
  float min_x = max_recog_range_;
  float min_y = max_recog_range_;
  bool found_valid_point = false;
  
  // ダウンサンプリング: 2ピクセルおきに処理してメモリ・CPU負荷削減
  int step_u = 2;
  int step_v = 2;
  
  for (int v = 0; v < height; v += step_v) {
    for (int u = 0; u < width; u += step_u) {
      int idx = v * step + u * 2;
      uint16_t raw = data[idx] | (data[idx + 1] << 8);
      float depth = static_cast<float>(raw) * 0.001f; // mm to m
      if (std::isfinite(depth) && depth > 0.1 && depth < max_recog_range_) {
        // カメラ座標系: x(右), y(下), z(前方)
        camera_z = depth;
        camera_x = (u - cx) * camera_z / fx;
        camera_y = (v - cy) * camera_z / fy;
        
        // 手動で座標変換（tf2::Vector3 オブジェクト生成を回避）
        base_x = r00 * camera_x + r01 * camera_y + r02 * camera_z + tx;
        base_y = r10 * camera_x + r11 * camera_y + r12 * camera_z + ty;
        base_z = r20 * camera_x + r21 * camera_y + r22 * camera_z + tz;

        float range = std::sqrt(base_x * base_x + base_y * base_y);
        if (std::abs(base_y) < robot_width_ / 2.0 &&
            base_z < robot_height_ && base_z > 0.1) {
          if (range < min_range) {
            min_range = range;
            min_x = base_x;
            min_y = base_y;
            found_valid_point = true;
          }
        }
      }
    }
  }
  if (!found_valid_point) {
    return std::make_tuple(max_obstacle_range_, 0.0, 0.0);
  }
  return std::make_tuple(min_range, min_x, min_y);
}

void VelFilter::timer_callback()
{
  auto now = std::chrono::system_clock::now();

  // vel_cmd_filteredの計算とパブリッシュ
  auto filtered_msg = geometry_msgs::msg::Twist();
  double target_vel, target_angle, filtered_vel;

  if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_max_vel_time_).count() > 60000) {
    max_velocity_ = default_max_velocity_;
  }

  // std::tie(target_vel, target_angle) = calc_slow_twist();

  if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_vel_time_).count() <= 1000) {
    target_vel = last_target_vel_;
    target_angle = last_target_angle_;
  }
  else {
    target_vel = 0.0;
    target_angle = 0.0;
  }

  if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_camera_time_).count() <= 200) {
    target_vel = std::min(target_vel, max_velocity_);
    filtered_vel = calc_filtered_velocity(target_vel);
  }
  else {
    filtered_vel = 0.0;
  }
  filtered_msg.linear.x = filtered_vel;
  filtered_msg.angular.z = target_angle;
  filtered_vel_pub_->publish(filtered_msg);

  // nearest_pointの計算とパブリッシュ
  double min_x, min_y;
  if (min_range_bu_ > min_range_td_) {
    min_x = min_x_td_;
    min_y = min_y_td_;
  } else {
    min_x = min_x_bu_;   
    min_y = min_y_bu_; 
  }
  auto nearest_camera_point_msg = geometry_msgs::msg::Vector3();
  nearest_camera_point_msg.x = min_x;
  nearest_camera_point_msg.y = min_y;
  nearest_camera_point_msg.z = 0.0;
  nearest_camera_point_pub_->publish(nearest_camera_point_msg);

  double min_x_scan, min_y_scan;
  if (front_min_range_scan_ < back_min_range_scan_) {
    min_x_scan = front_min_x_scan_;
    min_y_scan = front_min_y_scan_;
  } else {
    min_x_scan = back_min_x_scan_;
    min_y_scan = back_min_y_scan_;
  }
  auto nearest_scan_point_msg = geometry_msgs::msg::Vector3();
  nearest_scan_point_msg.x = min_x_scan;
  nearest_scan_point_msg.y = min_y_scan;
  nearest_scan_point_msg.z = 0.0;
  nearest_scan_point_pub_->publish(nearest_scan_point_msg);
}

}  // namespace vel_filter

int main(int argc, char** argv)
{
  rclcpp::init(argc, argv);
  
  auto node = std::make_shared<vel_filter::VelFilter>();
  
  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  
  executor.spin();
  
  rclcpp::shutdown();
  return 0;
}
