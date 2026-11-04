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

    uint8_t recv_data[4];
    motor.readOneParameter(motor_can_id, 0x700b, recv_data);
    printf("torque: %d\n", recv_data[3]);

    uint8_t send_data[4];
    send_data[3] = 0;
    motor.writeOneParameter(motor_can_id, 0x700b, send_data);
    motor.readOneParameter(motor_can_id, 0x700b, recv_data);
    printf("torque: %d\n", recv_data[3]);

    printf("start pose: %f, cur: %f, vol: %f\n", motor.getPosition(motor_can_id), motor.getIqf(motor_can_id), motor.getVbus(motor_can_id));

    // モータの動作モードを設定します（速度モード）
    motor.setMode(motor_can_id, RunMode::speed);
    // モータの回転速度を設定します[rad/s]
    motor.setSpeed(motor_can_id, 2.0f);
    sleep(3);
    // モータにイネーブル命令を送ります
    motor.enable(motor_can_id);
    sleep(5);
    // モータの回転速度を設定します（0.0rad/s）
    motor.setSpeed(motor_can_id, 0.0f);
    printf("enable pose: %f, cur: %f, vol: %f\n", motor.getPosition(motor_can_id), motor.getIqf(motor_can_id), motor.getVbus(motor_can_id));

    motor.disable(motor_can_id);
    printf("end pose: %f, cur: %f, vol: %f\n", motor.getPosition(motor_can_id), motor.getIqf(motor_can_id), motor.getVbus(motor_can_id));
}

int main() {
    motorTest();
}