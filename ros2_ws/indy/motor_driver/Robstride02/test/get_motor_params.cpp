#include "../src/Robstride02.hpp"
#include <cstring>

void printAllMotorsParam(Robstride02Driver motor, u_int16_t parameter, std::string param_name, int motor_can_size);

void motorTest(const std::string& can_interface)
{
    Robstride02Driver motor;
    const int motor_can_size = 4;
    const int motor_can_id = 1;

    if(motor.initSocket(can_interface) < 0)
    {
        printf("Socket initialize failed!\n");
        return;
    }

    motor.clearBuffer();

    printAllMotorsParam(motor, Parameterlist::LIMIT_SPD, "limit spd", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::LIMIT_CUR, "limit cur", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::LIMIT_TORQUE, "limit torque", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::CUR_KP, "cur kp", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::CUR_KI, "cur ki", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::LOC_KP, "loc kp", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::SPD_KP, "spd kp", motor_can_size);
    printAllMotorsParam(motor, Parameterlist::SPD_KI, "spd ki", motor_can_size);
}

void printAllMotorsParam(Robstride02Driver motor, u_int16_t parameter, std::string param_name, int motor_can_size)
{
    for (int i = 0; i < motor_can_size; i++)
    {
        uint8_t recv_data[4];
        motor.readOneParameter(i + 1, parameter, recv_data);
        float* param_value = reinterpret_cast<float*>(recv_data);
        std::cout << "Motor CAN ID " << i + 1 << " " << param_name << ": " << *param_value << std::endl;
    }
}

int main(int argc, char* argv[]) {
    std::string can_interface = "neck";
    if (argc > 1) {
        can_interface = argv[1];
    }
    motorTest(can_interface);
}