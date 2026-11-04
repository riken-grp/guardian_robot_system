#include "../src/Robstride02.hpp"

void motorTest()
{
    Robstride02Driver motor;
    const std::string can_interface = "motors";

    const int motor_can_id = 0x10;

    if(motor.initSocket(can_interface) < 0)
    {
        printf("Socket initialize failed!\n");
        return;
    }

    motor.clearBuffer();

    printf("start pose: %f, cur: %f, vol: %f\n", motor.getPosition(motor_can_id), motor.getIqf(motor_can_id), motor.getVbus(motor_can_id));

    // モータの動作モードを設定します（角度モード）
    motor.setMode(motor_can_id, RunMode::position);
    // モータにイネーブル命令を送ります
    motor.enable(motor_can_id);
    uint8_t recv_data[4];
    motor.readOneParameter(motor_can_id, 0x7025, recv_data);
    printf("speed: %d\n", recv_data[3]);
    // モータの目標角度を設定します[rad]
    motor.setPosition(motor_can_id, 0.0f);
    sleep(2);
    uint8_t send_data[4];
    send_data[3] = 10;
    motor.writeOneParameter(motor_can_id, 0x7025, send_data);
    motor.readOneParameter(motor_can_id, 0x7025, recv_data);
    printf("speed: %d\n", recv_data[3]);
    sleep(3);

    motor.disable(motor_can_id);
    printf("end pose: %f, cur: %f, vol: %f\n", motor.getPosition(motor_can_id), motor.getIqf(motor_can_id), motor.getVbus(motor_can_id));
}

int main() {
    motorTest();
}