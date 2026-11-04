#include "../src/Robstride02.hpp"

void motorTest()
{
    std::vector<Robstride02Driver> motors(3);
    const std::string can_interface = "motors";

    const std::vector<int> motor_can_id{0x10, 0x11, 0x12};
    const std::vector<float> motor_speed{9.0, 6.0, 3.0};

    for (int i = 0; i < 3; i++) {
        if(motors[i].initSocket(can_interface) < 0)
        {
            printf("Socket initialize failed!\n");
            return;
        }
    }

    for (int i = 0; i < 3; i++) {
        motors[i].clearBuffer();
        // モータの動作モードを設定します（速度モード）
        motors[i].setMode(motor_can_id[i], RunMode::speed);
        // モータの回転速度を設定します[rad/s]
        motors[i].setSpeed(motor_can_id[i], motor_speed[i]);
        // モータにイネーブル命令を送ります
        motors[i].enable(motor_can_id[i]);
    }
    sleep(5);

    for (int i = 0; i < 3; i++) {
        // モータの回転速度を設定します（0.0rad/s）
        motors[i].setSpeed(motor_can_id[i], 0.0f);
    }
}

int main() {
    motorTest();
}