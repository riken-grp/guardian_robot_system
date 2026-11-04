#include "../src/Robstride02.hpp"
#include <cstring>

void motorTest()
{
    Robstride02Driver motor;
    const std::string can_interface = "neck";
    const int motor_can_id = 0x10;
    u_int16_t parameter = Parameterlist::LIMIT_SPD;
    float send_data_float = 1.0;

    if(motor.initSocket(can_interface) < 0)
    {
        printf("Socket initialize failed!\n");
        return;
    }

    motor.clearBuffer();

    uint8_t recv_data[4];
    motor.readOneParameter(motor_can_id, parameter, recv_data);
    float recv_data_float;
    std::memcpy(&recv_data_float, recv_data, sizeof(recv_data_float));
    printf("start param: %f\n", recv_data_float);

    uint8_t send_data[4];
    std::memcpy(send_data, &send_data_float, sizeof(send_data));
    motor.writeOneParameter(motor_can_id, parameter, send_data);

    motor.readOneParameter(motor_can_id, parameter, recv_data);
    std::memcpy(&recv_data_float, recv_data, sizeof(recv_data_float));
    printf("end param: %f\n", recv_data_float);
    sleep(3);

}

int main() {
    motorTest();
}