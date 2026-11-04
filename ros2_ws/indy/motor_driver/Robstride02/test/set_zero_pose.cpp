#include "../src/Robstride02.hpp"

void motorTest()
{
    Robstride02Driver motor;
    const std::string can_interface = "neck";

    const int motor_can_id = 1;

    if(motor.initSocket(can_interface) < 0)
    {
        printf("Socket initialize failed!\n");
        return;
    }

    motor.clearBuffer();
    printf("start pose: %f\n", motor.getPosition(motor_can_id));
    motor.enable(motor_can_id);
    motor.setMechPosZero(motor_can_id);
    motor.disable(motor_can_id);
    printf("end pose: %f\n", motor.getPosition(motor_can_id));
}

int main() {
    motorTest();
}