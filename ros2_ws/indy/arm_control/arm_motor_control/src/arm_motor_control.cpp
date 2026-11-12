#include "Robstride02.hpp"
#include "../include/arm_motor_control.hpp"

// コンストラクタ
ArmMotorControl::ArmMotorControl()
    : Node("arm_motor_control_node") {
    uint8_t target_can_id;

    // パラメータ宣言
    this->declare_parameter<std::string>("arm_status_file", "arm_status.txt");
    this->declare_parameter<std::string>("can_interface", "");
    this->declare_parameter<std::vector<std::string>>("joint_names", std::vector<std::string>(0));
    this->declare_parameter<std::vector<long int>>("can_id", std::vector<long int>(0));     // YAMLから読み込む想定で空のベクタを設定
    this->declare_parameter<long int>("joints_pub_cycle", 0L);
    this->declare_parameter<bool>("temp_check", false);
    this->declare_parameter<double>("restart_temp", 30.0);
    this->declare_parameter<double>("max_temp", 80.0);
    this->declare_parameter<std::vector<double>>("default_offset", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("gain", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("default_position", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("max_velocity", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("max_position", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("min_position", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("default_velocity", std::vector<double>(0));

    // コールバックグループ
    auto callback_group = create_callback_group(rclcpp::CallbackGroupType::Reentrant);
    auto sub_opt = rclcpp::SubscriptionOptions();
    sub_opt.callback_group = callback_group;

    // サブスクライバーの初期化
    joint_trajectory_sub_ = this->create_subscription<trajectory_msgs::msg::JointTrajectory>(
        "joint_trajectory", 10,
        std::bind(&ArmMotorControl::control_joints, this, std::placeholders::_1), sub_opt
    );
    enable_sub_ = this->create_subscription<std_msgs::msg::Empty>(
        "enable", 10,
        std::bind(&ArmMotorControl::enable_callback, this, std::placeholders::_1), sub_opt
    );
    disable_sub_ = this->create_subscription<std_msgs::msg::Empty>(
        "disable", 10,
        std::bind(&ArmMotorControl::disable_callback, this, std::placeholders::_1), sub_opt
    );

    // パブリッシャーの初期化
    joints_pub_ = this->create_publisher<sensor_msgs::msg::JointState>(
        "joints", 10
    );

    temp_pub_ = this->create_publisher<std_msgs::msg::Float32MultiArray>(
        "temperature", 10
    );

    // パラメータを取得
    std::string arm_status_file;
    this->get_parameter("arm_status_file", arm_status_file);
    this->get_parameter("can_interface", can_interface_name_);
    this->get_parameter("joint_names", joint_names_);
    this->get_parameter("can_id", can_id_);
    this->get_parameter("joints_pub_cycle", joints_pub_cycle_);
    this->get_parameter("temp_check", temp_check_);
    this->get_parameter("restart_temp", restart_temp_);
    this->get_parameter("max_temp", max_temp_);
    this->get_parameter("default_offset", default_offset_);
    this->get_parameter("gain", gain_);
    this->get_parameter("default_position", default_position_);
    this->get_parameter("max_velocity", max_velocity_);
    this->get_parameter("max_position", max_position_);
    this->get_parameter("min_position", min_position_);
    this->get_parameter("default_velocity", default_velocity_);

    double tmp;
    for (size_t i = 0; i < joint_names_.size(); i++) {
        if (gain_[i] >= 0) {
            max_position_[i] = (max_position_[i] - default_offset_[i]) / gain_[i];
            min_position_[i] = (min_position_[i] - default_offset_[i]) / gain_[i];
        }
        else {
            tmp = (max_position_[i] - default_offset_[i]) / gain_[i];
            max_position_[i] = (min_position_[i] - default_offset_[i]) / gain_[i];
            min_position_[i] = tmp;
        }
    }

    if (joint_names_.size() != can_id_.size()) {
        RCLCPP_ERROR(this->get_logger(), "YAML array length does NOT MATCH!");
    }

    RCLCPP_INFO(this->get_logger(), "ArmMotorControl node has been started.");

    // CAN通信確立
    if(can_interface_.initSocket(can_interface_name_) < 0) {
        RCLCPP_INFO(this->get_logger(), "Socket of CAN I/F '%s' initialize FAILED!", can_interface_name_.c_str());
        can_init_flg_ = false;
        return;
    }
    RCLCPP_INFO(this->get_logger(), "Socket of CAN I/F '%s' initialize success.", can_interface_name_.c_str());

    can_interface_.clearBuffer();

        
    // モータごとにオフセット設定
    for (size_t i = 0; i < can_id_.size(); i++) {

        // 該当のモータ CAN IDを取得 (uint8_t型)
        target_can_id = can_id_[i];
        error_cnt_.push_back(0);
        motors_up_flg_.push_back(true);

	    // 位置オフセットの設定
        float position;
        float current_value;
        int check_cnt = 0;
        int outrange_cnt = 0;
        while(true) {
            position = can_interface_.getPosition(target_can_id);
            if ((position <= 3 * M_PI and position > 1e-10) or
                (position >= -3* M_PI and position < -1e-10)) {
                if (check_cnt == 0) {
                    current_value = position;
                    check_cnt++;
                    continue;
                }
                else {
                    if (abs(current_value - position) < 0.01) {
                        current_value = position;
                        check_cnt++;
                        if (check_cnt == 5) break;
                        continue;
                    }
                    else {
                        check_cnt = 0;
                        continue;
                    }
                }
            }
            else {
                RCLCPP_WARN(this->get_logger(), "Outrange value %d: %f", target_can_id, position);
                outrange_cnt++;
                if (outrange_cnt == 10) {
                    RCLCPP_ERROR(this->get_logger(), "Failed to get position. ArmMotorControl node will be stopped.");
                    motors_up_flg_[i] = false;
                    can_interface_.disable(target_can_id);
                    return;
                }
                usleep(10000);
            }
        }
        RCLCPP_INFO(this->get_logger(), "startup pos %d: %f", target_can_id, position);
        if (position <= M_PI and position >= -M_PI){
            offset_.push_back(0);
        } else {
            offset_.push_back(2*M_PI);
        }
    }

    uint8_t vel_array[4];
    uint8_t max_torque_array[4];
    uint8_t spd_kp_array[4];
    float spd_kp_float = 1;
    std::memcpy(spd_kp_array, &spd_kp_float, sizeof(spd_kp_array));
    uint8_t spd_ki_array[4];
    float spd_ki_float = 0.006;
    std::memcpy(spd_ki_array, &spd_ki_float, sizeof(spd_ki_array));

    // モータごとに初期位置移動
    for (size_t i = 0; i < can_id_.size(); i++) {

        // 該当のモータ CAN IDを取得 (uint8_t型)
        target_can_id = can_id_[i];

        can_interface_.disable(target_can_id);
        can_interface_.setMode(target_can_id, RunMode::position_csp);

        // モータにイネーブル命令を送信
        can_interface_.enable(target_can_id);

	    // // ゲインパラメタの設定
        can_interface_.writeOneParameter(target_can_id, Parameterlist::SPD_KP, spd_kp_array);
        can_interface_.writeOneParameter(target_can_id, Parameterlist::SPD_KI, spd_ki_array);

        float vel_float = default_velocity_[i];
        std::memcpy(vel_array, &vel_float, sizeof(vel_array));
        can_interface_.writeOneParameter(target_can_id, Parameterlist::LIMIT_SPD, vel_array);

	    // 初期位置に移動
        double target_pose = gain_[i] * default_position_[i] + default_offset_[i] + offset_[i];
        can_interface_.setPosition(target_can_id, target_pose);
    }

    temp_over_flg_ = false;
    temp_over_cnt_ = 0;
    
    sleep(2.0);

    // タイマーの設定
    timer_ = this->create_wall_timer(
        std::chrono::milliseconds(joints_pub_cycle_),
        std::bind(&ArmMotorControl::timer_callback, this), callback_group
    );

    // ホームディレクトリにarm_status_file_が存在しない場合は作成
    std::string home_dir = std::getenv("HOME");
    std::string arm_status_dir = home_dir + "/arm_status";
    if (!std::filesystem::exists(arm_status_dir)) {
        std::filesystem::create_directory(arm_status_dir);
    }
    arm_status_file_ = arm_status_dir + "/" + arm_status_file;

    // ファイルに"start 時刻"を上書き
    std::ofstream ofs(arm_status_file_, std::ios::out);
    if (ofs.fail()) {
        RCLCPP_ERROR(this->get_logger(), "Failed to open %s file.", arm_status_file_.c_str());
    } else {
        auto now = std::chrono::system_clock::now();
        std::time_t now_c = std::chrono::system_clock::to_time_t(now);
        ofs << "start " << std::put_time(std::localtime(&now_c), "%Y-%m-%d %H:%M:%S") << std::endl;
        ofs.close();
        RCLCPP_INFO(this->get_logger(), "Created %s file.", arm_status_file_.c_str());
    }

    can_init_flg_ = true;
    RCLCPP_INFO(this->get_logger(), "Arm motors up.");
}

ArmMotorControl::~ArmMotorControl() {
    uint8_t target_can_id;
    for (size_t i = 0; i < can_id_.size(); i++) {
        // 該当のモータ CAN IDを取得 (uint8_t型)
        target_can_id = can_id_[i];
        // 標準姿勢に移動
        double target_pose = gain_[i] * default_position_[i] + default_offset_[i] + offset_[i];
        can_interface_.setPosition(target_can_id, target_pose);
    }

    // ファイルの最終行に"end 時刻"を追記
    std::ofstream ofs(arm_status_file_, std::ios::app);
    if (ofs.fail()) {
        RCLCPP_ERROR(this->get_logger(), "Failed to open %s file.", arm_status_file_.c_str());
    } else {
        auto now = std::chrono::system_clock::now();
        std::time_t now_c = std::chrono::system_clock::to_time_t(now);
        ofs << "end " << std::put_time(std::localtime(&now_c),  "%Y-%m-%d %H:%M:%S") << std::endl;
        ofs.close();
        RCLCPP_INFO(this->get_logger(), "Updated %s file.", arm_status_file_.c_str());
    }
    RCLCPP_INFO(this->get_logger(), "Motors down.");
}

// タイマーコールバック
void ArmMotorControl::timer_callback() {
    uint8_t target_can_id;
    float position;
    float speed;
    float torque;
    float temp;

    // JointStateメッセージ作成
    auto msg = sensor_msgs::msg::JointState();
    msg.header.stamp = this->get_clock()->now();

    // 温度メッセージ作成
    auto temp_msg = std_msgs::msg::Float32MultiArray();

    // 各モータに対し処理
    for (size_t i = 0; i < can_id_.size(); i++) {

        // 該当のモータ CAN IDを取得 (uint8_t型)
        target_can_id = can_id_[i];

        // APIから情報取得
        {
            std::lock_guard<std::mutex> lock(get_mutex_);
            position = can_interface_.getPosition(target_can_id) - offset_[i]; // 現在位置
            position = (position - default_offset_[i]) / gain_[i];
            speed = can_interface_.getVelocity(target_can_id);                 // 現在速度
            torque = can_interface_.getIqf(target_can_id);                     // 現在Iqf
            temp = can_interface_.getTemp(target_can_id);                       // 現在温度
        }

        // 異常状態のときdisable
        if (position < (min_position_[i] - 0.05) or position > (max_position_[i] + 0.05)) {
            error_cnt_[i]++;
            RCLCPP_WARN(this->get_logger(), "CAN ID:%d OUT OF POSITION LIMIT:%.2f [%f~%f]", target_can_id, position, min_position_[i], max_position_[i]);
            if (error_cnt_[i] == 5) can_interface_.disable(target_can_id);
        }
        else {
            error_cnt_[i] = 0;
        }

        // メッセージに情報追加
        msg.name.push_back(joint_names_[i]);    // モータ名
        msg.position.push_back(position);       // 現在位置
        msg.velocity.push_back(speed);          // 現在速度
        msg.effort.push_back(torque);           // 現在Iqf

        temp_msg.data.push_back(temp);          // 現在温度
    }

    temp_check(temp_msg.data);

    // 現在情報をパブリッシュ
    joints_pub_->publish(msg);
    temp_pub_->publish(temp_msg);
}

// 関節位置制御
void ArmMotorControl::control_joints(const trajectory_msgs::msg::JointTrajectory::SharedPtr msg) {
    uint8_t target_can_id;
    uint8_t max_vel_array[4];
    uint8_t max_torque_arr[4];
    double max_vel_array_finally[4];
    std::vector<double> last_positions = msg->points.back().positions;

    if (!can_init_flg_) {
        return;
    }

    can_interface_.clearBuffer();

    // 各モータに対し処理
    for (size_t j = 0; j < msg->joint_names.size(); j++) {
        if (motors_up_flg_[j] == false) {
            continue;
        }

        // 位置指定エラーチェック
        if (last_positions[j] > max_position_[j]) {
            RCLCPP_DEBUG(this->get_logger(), 
                "WARNING: %.2f is OUTSIDE the range of possible position (%.2f - %.2f)!", 
                last_positions[j], min_position_[j], max_position_[j]
            );
            last_positions[j] = max_position_[j];
        } else if (last_positions[j] < min_position_[j]) {
            RCLCPP_DEBUG(this->get_logger(), 
                "WARNING: %.2f is OUTSIDE the range of possible position (%.2f - %.2f)!", 
                last_positions[j], min_position_[j], max_position_[j]
            );
            last_positions[j] = min_position_[j];
        }

        max_vel_array_finally[j] = 0;
    }


    set_process_flag_ = false;
    {
        std::lock_guard<std::mutex> lock(set_mutex_);
        set_process_flag_ = true;

        // 各ポイントに分割処理
        for (size_t i = 0; i < msg->points.size(); i++) {

            // 新指令受領時に現指令破棄
            if (set_process_flag_ == false){
                break;
            }

            const auto& point = msg->points[i];

            // 各モータに対し処理
            for (size_t j = 0; j < point.velocities.size(); j++) {
                if (motors_up_flg_[j] == false) {
                    continue;
                }

                std::lock_guard<std::mutex> lock(get_mutex_);

                // 該当のモータ CAN IDを取得 (uint8_t型)
                target_can_id = can_id_[j];
                can_interface_.setMode(target_can_id, RunMode::position_csp);

                // // JointTrajectoryの指定速度を最大速度に設定
                // // float max_vel_float = abs(static_cast<float>(point.velocities[j]));
                // max_vel_array_finally[j] = std::max(max_vel_array_finally[j], abs(point.velocities[j]));
                // float max_vel_float = static_cast<float>(max_vel_array_finally[j]);
                // std::memcpy(max_vel_array, &max_vel_float, sizeof(max_vel_array));
                // can_interface_.writeOneParameter(target_can_id, Parameterlist::LIMIT_SPD, max_vel_array);
                // RCLCPP_DEBUG(this->get_logger(), "max_vel_float %.2f", max_vel_float);

                double target_pose = gain_[j] * last_positions[j] + default_offset_[j] + offset_[j];
                // 目標位置指定
                can_interface_.setPosition(target_can_id, target_pose); 

                RCLCPP_DEBUG(this->get_logger(),
                    "PROCESSING MOTOR CAN ID: %d, MODE: Position(CSP), GOAL POSITION: %.2f, SPEED: %.2f",
                    target_can_id, target_pose, point.velocities[j]
                );
            }

            // インターバルの設定
            if (i > 0) {
                const auto& prev_point = msg->points[i - 1];

                // 前後のポイントの time_from_start を取得
                double prev_time = prev_point.time_from_start.sec + prev_point.time_from_start.nanosec * 1e-9;
                double curr_time = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9;

                // 時間間隔を計算
                double time_interval = (curr_time - prev_time) * 1e6;
                usleep(static_cast<useconds_t>(time_interval));
            }
        }
    }
}

void ArmMotorControl::enable_callback(const std_msgs::msg::Empty::SharedPtr msg) {
    control_enable();
}

// ENABLE命令送信
void ArmMotorControl::control_enable() {
    if (!can_init_flg_) {
        RCLCPP_WARN(this->get_logger(), "Motors are down. Cannot enable.");
        return;
    }
    // 各モータに対し処理
    for (size_t i = 0; i < joint_names_.size(); i++) {
        if (motors_up_flg_[i] == false) {
            continue;
        }
        can_interface_.enable(can_id_[i]);
        RCLCPP_INFO(this->get_logger(), "Sended ENABLE commands to %s motor.", joint_names_[i].c_str());
    }
}

void ArmMotorControl::disable_callback(const std_msgs::msg::Empty::SharedPtr msg) {
    control_disable();
}

// DISABLE命令送信
void ArmMotorControl::control_disable() {
    // 各モータに対し処理
    for (size_t i = 0; i < joint_names_.size(); i++) {
            can_interface_.disable(can_id_[i]);
            RCLCPP_INFO(this->get_logger(), "Sended DISABLE commands to %s motor.", joint_names_[i].c_str());
    }
}

void ArmMotorControl::temp_check(const std::vector<float>& temps) {
    if (!temp_check_) {
        return;
    }

    // 1つでも max_temp_ を超えていたらカウントアップ、3回連続で全モータdisable
    bool any_over = false;
    for (float temp : temps) {
        if (temp > max_temp_) {
            any_over = true;
            break;
        }
    }

    if (any_over) {
        temp_over_cnt_++;
        RCLCPP_DEBUG(this->get_logger(), "Temperature over! count: %d/3", temp_over_cnt_);
        if (temp_over_cnt_ >= 3 && !temp_over_flg_) {
            RCLCPP_WARN(this->get_logger(), "Temperature over! Disabling all motors.");
            // 初期位置に移動してから3秒待ってdisable
            for (size_t i = 0; i < can_id_.size(); i++) {
                double target_pose = gain_[i] * default_position_[i] + default_offset_[i] + offset_[i];
                can_interface_.setPosition(can_id_[i], target_pose);
            }
            sleep(3);
            control_disable();
            temp_over_flg_ = true;
        }
        return;
    } else {
        temp_over_cnt_ = 0;
    }

    // 全モータが restart_temp_ を下回っていたらenable
    if (temp_over_flg_) {
        bool all_below = true;
        for (float temp : temps) {
            if (temp >= restart_temp_) {
                all_below = false;
                break;
            }
        }
        if (all_below) {
            RCLCPP_INFO(this->get_logger(), "All temperatures below restart threshold. Enabling motors and moving to default position.");
            control_enable();
            // 初期姿勢に移動
            for (size_t i = 0; i < can_id_.size(); i++) {
                double target_pose = gain_[i] * default_position_[i] + default_offset_[i] + offset_[i];
                can_interface_.setPosition(can_id_[i], target_pose);
            }
            temp_over_flg_ = false;
        }
    }
}

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    auto node = std::make_shared<ArmMotorControl>();
    rclcpp::executors::MultiThreadedExecutor executor;
    executor.add_node(node);
    executor.spin();
    rclcpp::shutdown();
    return 0;
}
