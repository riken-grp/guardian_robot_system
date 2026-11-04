#include "../include/Robstride02.hpp"
#include "../include/motor_control.hpp"

// コンストラクタ
MotorControl::MotorControl()
    : Node("motor_control_node") {
    uint8_t target_can_id;

    std::string robot_name = this->get_namespace();
    robot_name = robot_name.replace(0, 1, "");

    // パラメータ宣言
    this->declare_parameter<std::string>("can_interface", "");
    this->declare_parameter<std::vector<std::string>>("joint_name", std::vector<std::string>(0));
    this->declare_parameter<std::vector<long int>>("can_id", std::vector<long int>(0));     // YAMLから読み込む想定で空のベクタを設定
    this->declare_parameter<std::vector<double>>("default_offset", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("gain", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("max_velocity", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("max_position", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("min_position", std::vector<double>(0));
    this->declare_parameter<std::vector<double>>("default_velocity", std::vector<double>(0));

    // コールバックグループ
    auto callback_group = create_callback_group(rclcpp::CallbackGroupType::Reentrant);
    auto sub_opt = rclcpp::SubscriptionOptions();
    sub_opt.callback_group = callback_group;

    // サブスクライバーの初期化
    control_position_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
        "motor_control/control_position", 10,
        std::bind(&MotorControl::control_position, this, std::placeholders::_1), sub_opt
    );
    control_speed_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
        "motor_control/control_speed", 10,
        std::bind(&MotorControl::control_speed, this, std::placeholders::_1), sub_opt
    );
    control_enable_sub_ = this->create_subscription<std_msgs::msg::Empty>(
        "motor_control/enable", 10,
        std::bind(&MotorControl::control_enable, this, std::placeholders::_1), sub_opt
    );
    control_disable_sub_ = this->create_subscription<std_msgs::msg::Empty>(
        "motor_control/disable", 10,
        std::bind(&MotorControl::control_disable, this, std::placeholders::_1), sub_opt
    );

    // パブリッシャーの初期化
    motor_info_pub_ = this->create_publisher<sensor_msgs::msg::JointState>("motor_control/joints", 10);
    temp_pub_ = this->create_publisher<std_msgs::msg::Float32MultiArray>("motor_control/temperature", 10);

    // パラメータを取得
    this->get_parameter("can_interface", can_interface_name_);
    this->get_parameter("joint_name", joint_name_);
    this->get_parameter("can_id", can_id_);
    this->get_parameter("default_offset", default_offset_);
    this->get_parameter("gain", gain_);
    this->get_parameter("max_velocity", max_velocity_);
    this->get_parameter("max_position", max_position_);
    this->get_parameter("min_position", min_position_);
    this->get_parameter("default_velocity", default_velocity_);

    double tmp;
    for (size_t i = 0; i < joint_name_.size(); i++) {
        joint_name_[i] = robot_name + "_" + joint_name_[i];
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

    if (joint_name_.size() != can_id_.size()) {
        RCLCPP_ERROR(this->get_logger(), "YAML array length does NOT MATCH!");
        std::exit(-1);
    }

    RCLCPP_INFO(this->get_logger(), "MotorControl node has been started.");

    // CAN通信確立
    if(can_interface_.initSocket(can_interface_name_) < 0) {
        RCLCPP_ERROR(this->get_logger(), "Socket of CAN I/F '%s' initialize FAILED!", can_interface_name_.c_str());
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
                    RCLCPP_ERROR(this->get_logger(), "Failed to get position. MotorControl node will be stopped.");
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
        can_interface_.setPosition(target_can_id, offset_[i]);
    }

    sleep(2.0);

    // タイマーの設定
    timer_ = this->create_wall_timer(
        std::chrono::milliseconds(100),
        std::bind(&MotorControl::timer_callback, this), callback_group
    );

    can_init_flg_ = true;
    RCLCPP_INFO(this->get_logger(), "Motors up.");
}

MotorControl::~MotorControl() {
    uint8_t target_can_id;
    for (size_t i = 0; i < can_id_.size(); i++) {
        // 該当のモータ CAN IDを取得 (uint8_t型)
        target_can_id = can_id_[i];
        // 標準姿勢に移動
        can_interface_.setPosition(target_can_id, offset_[i]);
    }
    RCLCPP_INFO(this->get_logger(), "Motors down.");
}

// タイマーコールバック
void MotorControl::timer_callback() {
    uint8_t target_can_id;

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
        float position = can_interface_.getPosition(target_can_id) - offset_[i];    // 現在位置
        position = (position - default_offset_[i]) / gain_[i];
        float speed = can_interface_.getVelocity(target_can_id);                    // 現在速度
        float torque = can_interface_.getIqf(target_can_id);                        // 現在Iqf
        float temp = can_interface_.getTemp(target_can_id);                  // 現在温度

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
        msg.name.push_back(joint_name_[i]);     // モータ名
        msg.position.push_back(position);       // 現在位置
        msg.velocity.push_back(speed);          // 現在速度
        msg.effort.push_back(torque);           // 現在Iqf

        temp_msg.data.push_back(temp);          // 現在温度
    }

    // 現在情報をパブリッシュ
    motor_info_pub_->publish(msg);
    temp_pub_->publish(temp_msg);
}

// 角度制御
void MotorControl::control_position(const sensor_msgs::msg::JointState::SharedPtr msg) {
    uint8_t target_can_id;
    uint8_t max_vel_array[4];

    if (!can_init_flg_) {
        return;
    }

    // 入力サイズの一致を確認
    if (msg->name.size() != msg->position.size()) {
        RCLCPP_WARN(this->get_logger(), "MISMATCH between name and position array sizes!");
        return;
    }
    RCLCPP_INFO(this->get_logger(), "Received %lu Motor Commands.", msg->name.size());

    can_interface_.clearBuffer();

    // 各モータに対し処理
    // TODO: 照合を先に持ってきてリストに番号を格納すれば、二重ループは最初の一度で済む
    for (size_t i = 0; i < msg->name.size(); i++) {
        bool match_flg = false;
        // joint_nameを照合
        for (size_t j = 0; j < joint_name_.size(); j++) {
            if (joint_name_[j] == msg->name[i]) {
                if (motors_up_flg_[i] == false) {
                    break;
                }
                match_flg = true;
                // 位置指定エラーチェック
                if (msg->position[i] > max_position_[j]) {
                    RCLCPP_WARN(this->get_logger(), "%.2f is OUTSIDE the range of possible position (%.2f - %.2f)!", msg->position[i], min_position_[j], max_position_[j]);
                    msg->position[i] = max_position_[j];
                }
                else if (msg->position[i] < min_position_[j]) {
                    RCLCPP_WARN(this->get_logger(), "%.2f is OUTSIDE the range of possible position (%.2f - %.2f)!", msg->position[i], min_position_[j], max_position_[j]);
                    msg->position[i] = min_position_[j];
                }
                break;
            }
        }
        if (match_flg == false) {
            RCLCPP_WARN(this->get_logger(), "%s is not exist!", msg->name[i].c_str());
        }
    }

    bool velocity_provided = (msg->velocity.size() == msg->name.size());

    // 各モータに対し処理
    for (size_t i = 0; i < msg->name.size(); i++) {

        // joint_nameを照合
        for (size_t j = 0; j < joint_name_.size(); j++) {
            if (joint_name_[j] == msg->name[i]) {
                if (motors_up_flg_[i] == false) {
                    break;
                }

                // 該当のモータ CAN IDを取得 (uint8_t型)
                target_can_id = can_id_[j];

                // モータへの指令
                can_interface_.setMode(target_can_id, RunMode::position_csp);

                float speed_target;
                // 速度指令
                 if (velocity_provided) {
                    // メッセージに速度が設定されていれば使用
                    speed_target = static_cast<float>(msg->velocity[i]);
                    // max_velocity を超えていたらクランプ
                    if (speed_target > static_cast<float>(max_velocity_[j])) {
                        speed_target = static_cast<float>(max_velocity_[j]);
                    }
                } else {
                    // 速度未設定 → デフォルト速度を使用
                    speed_target = static_cast<float>(default_velocity_[j]);
                }

                std::memcpy(max_vel_array, &speed_target, sizeof(max_vel_array));
                can_interface_.writeOneParameter(target_can_id,
                                                 Parameterlist::LIMIT_SPD,
                                                 max_vel_array);

                double target_pose = gain_[j] * msg->position[i] + default_offset_[j] + offset_[j];
                can_interface_.setPosition(target_can_id, target_pose);

                RCLCPP_INFO(this->get_logger(),
                    "PROCESSING MOTOR CAN ID: %d, MODE: Position, POSITION: %.2f", 
                    target_can_id, target_pose
                );

                break;
            }
        }
    }
}

// 角速度制御
void MotorControl::control_speed(const sensor_msgs::msg::JointState::SharedPtr msg) {
    uint8_t target_can_id;

    if (!can_init_flg_) {
        return;
    }

    // 入力サイズの一致を確認
    if (msg->name.size() != msg->velocity.size()) {
        RCLCPP_WARN(this->get_logger(), "MISMATCH between name and velocity array sizes!");
        return;
    }
    RCLCPP_INFO(this->get_logger(), "Received %lu motor commands.", msg->name.size());

    can_interface_.clearBuffer();

    // 各モータに対し処理
    // TODO: 照合を先に持ってきてリストに番号を格納すれば、二重ループは最初の一度で済む
    for (size_t i = 0; i < msg->name.size(); i++) {
        bool match_flg = false;
        // joint_nameを照合
        for (size_t j = 0; j < joint_name_.size(); j++) {
            if (joint_name_[j] == msg->name[i]) {
                if (motors_up_flg_[i] == false) {
                    break;
                }
                match_flg = true;
                if (msg->velocity[i] > max_velocity_[j]) {
                    msg->velocity[i] = max_velocity_[j];
                    RCLCPP_WARN(this->get_logger(), "%.2f is OUTSIDE the range of possible velocity (<= %.2f)!", msg->velocity[i], max_velocity_[j]);
                }
                break;
            }
        }
        if (match_flg == false) {
            RCLCPP_WARN(this->get_logger(), "%s is not exist!", msg->name[i].c_str());
        }
    }

    // 各モータに対し処理
    for (size_t i = 0; i < msg->name.size(); i++) {

        // joint_nameを照合
        for (size_t j = 0; j < joint_name_.size(); j++) {
            if (joint_name_[j] == msg->name[i]) {
                if (motors_up_flg_[i] == false) {
                    break;
                }

                // 該当のモータ CAN IDを取得 (uint8_t型)
                target_can_id = can_id_[j];

                // モータへの指令
                can_interface_.setMode(target_can_id, RunMode::speed);              // 動作モード設定
                can_interface_.setSpeed(target_can_id, msg->velocity[i]);        // 目標角速度設定
                RCLCPP_INFO(this->get_logger(),
                    "PROCESSING MOTOR CAN ID: %d, MODE: Speed, SPEED: %.2f",
                    target_can_id, msg->velocity[i]
                );

                break;
            }
        }
    }
}

// ENABLE命令送信
void MotorControl::control_enable(const std_msgs::msg::Empty::SharedPtr msg) {
    if (!can_init_flg_) {
        RCLCPP_WARN(this->get_logger(), "Motors are down. Cannot enable.");
        return;
    }

    for (size_t i = 0; i < can_id_.size(); i++) {
        if (motors_up_flg_[i] == false) {
            break;
        }
        can_interface_.enable(can_id_[i]);
    }
}

// DISABLE命令送信
void MotorControl::control_disable(const std_msgs::msg::Empty::SharedPtr msg) {
    for (size_t i = 0; i < can_id_.size(); i++) {
        can_interface_.disable(can_id_[i]);
    }
}

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    auto node = std::make_shared<MotorControl>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
