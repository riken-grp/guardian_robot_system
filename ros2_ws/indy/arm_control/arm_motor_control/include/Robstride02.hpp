#pragma once


#define CRCPP_USE_CPP11
#include <iostream>
#include <stdint.h>
#include <algorithm>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <unistd.h>
#include <linux/can.h>
#include <linux/can/raw.h>


enum class RunMode
{
    motion,
    position,
    speed,
    current,
    nan,
    position_csp
};


namespace Parameterlist
{
    constexpr uint16_t RUN_MODE      = 0x7005;
    constexpr uint16_t IQ_REF        = 0x7006;
    constexpr uint16_t SPD_REF       = 0x700A;
    constexpr uint16_t LIMIT_TORQUE  = 0x700B;
    constexpr uint16_t CUR_KP        = 0x7010;
    constexpr uint16_t CUR_KI        = 0x7011;
    constexpr uint16_t CUR_FILT_GAIN = 0x7014;
    constexpr uint16_t LOC_REF       = 0x7016;
    constexpr uint16_t LIMIT_SPD     = 0x7017;
    constexpr uint16_t LIMIT_CUR     = 0x7018;
    constexpr uint16_t MECH_POS      = 0x7019;
    constexpr uint16_t IQF           = 0x701A;
    constexpr uint16_t MECH_VEL      = 0x701B;
    constexpr uint16_t VBUS          = 0x701C;
    constexpr uint16_t LOC_KP        = 0x701E;
    constexpr uint16_t SPD_KP        = 0x701F;
    constexpr uint16_t SPD_KI        = 0x7020;
    constexpr uint16_t EPSCAN_TIME   = 0x7024;
    constexpr uint16_t VEL_MAX       = 0x7025;
    constexpr uint16_t ACC_SET       = 0x7026;
    constexpr uint16_t SPD_FILT_GAIN = 0x7027;
    constexpr uint16_t CANTIMEOUT    = 0x7028;
    constexpr uint16_t ZERO_STA      = 0x7029;
};


class Robstride02Driver
{
    private:
        static constexpr uint8_t EXTENDED_FRAME = 1;
        int can_socket_;
        struct sockaddr_can addr;
        uint8_t is_enable = false;

        int readMsg(struct can_frame &rx_frame);
        int writeMsg(uint32_t can_id, uint8_t (&data)[8]);
        uint16_t mapFloatToUint16(float val,
                                  float start1,
                                  float stop1,
                                  uint16_t start2,
                                  uint16_t stop2);

    public:
        // Data Convert Union
        typedef union
        {
          float f;
          uint8_t b[4];
        } float_byte;

        Robstride02Driver(){ ; }


        /* ===== SOCKET CAN COMMAND ===== */
        int initSocket(const std::string & can_interface);
        int closeSocket();
        void clearBuffer();


        /* ===== ROBSTRIDE CONTROL COMMAND ===== */
        // 1
        int operationControl(uint8_t target_can_id,
                             float torque,
                             float goal_position,
                             float velocity,
                             float kp,
                             float ki);
        // 3
        void enable(uint8_t target_can_id);
        // 4
        void disable(uint8_t target_can_id);
        // 6
        void setMechPosZero(uint8_t target_can_id);
        // 7
        void setCanId(uint8_t target_can_id, uint8_t present_can_id);
        // 17
        void readOneParameter(uint8_t target_can_id,
                              uint16_t parameter,
                              uint8_t (&receive_data)[4]);
        // 18
        int writeOneParameter(uint8_t target_can_id,
                              uint16_t parameter,
                              uint8_t (&param_data)[4]);




        /* ===== OPTION COMMAND ===== */
        void setMode(uint8_t target_can_id, RunMode mode);
        RunMode getMode(uint8_t target_can_id);
        void setSpeed(uint8_t target_can_id, float speed);
        void setPosition(uint8_t target_can_id, float position);
        void setLimitCur(uint8_t target_can_id, float cur);
        float getVelocity(uint8_t target_can_id);
        float getPosition(uint8_t target_can_id);
        float getIqf(uint8_t target_can_id);
        float getVbus(uint8_t target_can_id);
        float getTemp(uint8_t target_can_id);
        bool isActive(uint8_t target_can_id);
};











/* ======================
   ===== SOCKET CAN =====
   ====================== */

int Robstride02Driver::initSocket(const std::string & can_interface)
{
    struct ifreq ifr;

    // Create socket
    if((can_socket_ = socket(PF_CAN, SOCK_RAW, CAN_RAW)) < 0){ return -1; }

    // Socket option
    struct timeval tv;
    tv.tv_sec = 0;
    tv.tv_usec = 500;  // 1ms
    setsockopt(can_socket_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    // Specify device
    strncpy(ifr.ifr_name, can_interface.c_str(), IFNAMSIZ -1);
    if(ioctl(can_socket_, SIOCGIFINDEX, &ifr) < 0){ return -1; }

    // Bind the socket
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if(bind(can_socket_, (struct sockaddr *)&addr, sizeof(addr)) < 0){ return -1; }

    return 1;
}


int Robstride02Driver::closeSocket()
{
    close(can_socket_);

    return 1;
}


void Robstride02Driver::clearBuffer()
{
    struct can_frame frame;
    memset(&frame, 0, sizeof(struct can_frame));
    ssize_t nbytes;

    do
    {
        nbytes = read(can_socket_, &frame, sizeof(struct can_frame));
    } while (nbytes > 0);
}


int Robstride02Driver::writeMsg(uint32_t can_id, uint8_t (&data)[8])
{
    struct can_frame tx_frame;

    // set mode
    tx_frame.can_id = can_id | EXTENDED_FRAME << 31;
    tx_frame.len = 8;
    tx_frame.data[0] = data[0];
    tx_frame.data[1] = data[1];
    tx_frame.data[2] = data[2];
    tx_frame.data[3] = data[3];
    tx_frame.data[4] = data[4];
    tx_frame.data[5] = data[5];
    tx_frame.data[6] = data[6];
    tx_frame.data[7] = data[7];
    
    int bytes_sent = write(can_socket_, &tx_frame, sizeof(tx_frame));
    usleep(2 * 1000);   // wait 2ms

    if(bytes_sent < 0){ return -1; }

    return 1;
}


int Robstride02Driver::readMsg(struct can_frame &rx_frame)
{
    struct can_frame frame;
    memset(&frame, 0, sizeof(struct can_frame));

    ssize_t ret = read(can_socket_, &frame, sizeof(struct can_frame));
    usleep(2 * 1000);   // wait 2ms

    if(ret <= 0){ return -1; }

    rx_frame = frame;

    return 1;
}


uint16_t Robstride02Driver::mapFloatToUint16(float val,
                                             float start1,
                                             float stop1,
                                             uint16_t start2,
                                             uint16_t stop2)
{
    val = std::clamp(val, start1, stop1);
    float mapped = start2 + (val - start1) * (stop2 - start2) / (stop1 - start1);

    return static_cast<uint16_t>(mapped);
}










/* =========================
   ===== COMMUNICATION =====
   ========================= */


/**
 * @fn
 * @brief (comm-type: 1)
 */
int Robstride02Driver::operationControl(uint8_t target_can_id,
                                        float torque,
                                        float goal_position,
                                        float velocity,
                                        float kp,
                                        float ki)
{
    uint16_t uint16_torque,
             uint16_goal_position,
             uint16_velocity,
             uint16_kp,
             uint16_ki = 0;

    // Convert float to uint16_t
    uint16_torque = mapFloatToUint16(torque, -17.0, 17.0, 0, 65535);
    uint16_goal_position = mapFloatToUint16(goal_position, -12.5663, 12.5663, 0, 65535);
    uint16_velocity = mapFloatToUint16(velocity, -44.0, 44.0, 0, 65535);
    uint16_kp = mapFloatToUint16(kp, 0.0, 500.0, 0, 65535);
    uint16_ki = mapFloatToUint16(ki, 0.0, 5.0, 0, 65535);

    // Send command
    uint32_t id = (1 << 24) | ((uint16_torque << 8) & 0x00FFFF00) | target_can_id;
    uint8_t data[8];

    data[0] = uint16_goal_position & 0xFF;
    data[1] = (uint16_goal_position >> 8) & 0xFF;
    data[2] = uint16_velocity & 0xFF;
    data[3] = (uint16_velocity >> 8) & 0xFF;
    data[4] = uint16_kp & 0xFF;
    data[5] = (uint16_kp >> 8) & 0xFF;
    data[6] = uint16_ki & 0xFF;
    data[7] = (uint16_ki >> 8) & 0xFF;

    if(this->writeMsg(id, data) < 0){ return -1; }

    return 1;
}


/**
 * @fn
 * @brief (comm-type: 3)
 */
void Robstride02Driver::enable(uint8_t target_can_id)
{
    uint32_t id = (3 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = 0x00;
    data[1] = 0x00;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = 0x00;
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->writeMsg(id, data);
    this->is_enable = 1;
}


/**
 * @fn
 * @brief (comm-type: 4)
 */
void Robstride02Driver::disable(uint8_t target_can_id)
{
    uint32_t id = (4 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = 0x00;
    data[1] = 0x00;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = 0x00;
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->writeMsg(id, data);
    this->is_enable = 0;
}


/**
 * @fn
 * @brief (comm-type: 6)
 */
void Robstride02Driver::setMechPosZero(uint8_t target_can_id)
{
    uint32_t id = (6 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = 0x01;
    data[1] = 0x00;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = 0x00;
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->writeMsg(id, data);
}


/**
 * @fn
 * @brief (comm-type: 7)
 */
void Robstride02Driver::setCanId(uint8_t target_can_id, uint8_t present_can_id)
{
    uint32_t id = (7 << 24)
                  | ((present_can_id << 16) & 0x00FF0000)
                  | ((0xDD << 8) & 0x0000FF00)
                  | target_can_id;
    uint8_t data[8];

    data[0] = 0x00;
    data[1] = 0x00;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = 0x00;
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->writeMsg(id, data);
}


/**
 * @fn
 * @brief (comm-type: 17)
 */
void Robstride02Driver::readOneParameter(uint8_t target_can_id,
                                         uint16_t parameter,
                                         uint8_t (&receive_data)[4])
{
    struct can_frame rx_frame;
    uint32_t id = (17 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = parameter & 0xFF;
    data[1] = (parameter >> 8) & 0xFF;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = 0x00;
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->clearBuffer();

    this->writeMsg(id, data);

    if(this->readMsg(rx_frame) > 0)
    {
        for(uint8_t i=0; i<4; i++){ receive_data[i] = rx_frame.data[i+4]; }
    }
    else
    {
        for(uint8_t i=0; i<4; i++){ receive_data[i] = 0; }
    }
}


/**
 * @fn
 * @brief (comm-type: 18)
 */
int Robstride02Driver::writeOneParameter(uint8_t target_can_id,
                                         uint16_t parameter,
                                         uint8_t (&param_data)[4])
{
    uint32_t id = (18 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = parameter & 0xFF;
    data[1] = (parameter >> 8) & 0xFF;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = param_data[0];
    data[5] = param_data[1];
    data[6] = param_data[2];
    data[7] = param_data[3];
    
    if(this->writeMsg(id, data) < 0){ return -1; }

    return 1;
}










/* =======================
   ===== CAN COMMAND =====
   ======================= */

void Robstride02Driver::setMode(uint8_t target_can_id, RunMode mode)
{
    if(mode == RunMode::nan){ return; }

    uint32_t id = (18 << 24) | ((0xDD << 8) & 0x0000FF00) | target_can_id;
    uint8_t data[8];

    data[0] = 0x7005 & 0xFF;
    data[1] = (0x7005 >> 8) & 0xFF;
    data[2] = 0x00;
    data[3] = 0x00;
    data[4] = static_cast<uint8_t>(mode);
    data[5] = 0x00;
    data[6] = 0x00;
    data[7] = 0x00;

    this->writeMsg(id, data);
}


RunMode Robstride02Driver::getMode(uint8_t target_can_id)
{
    uint8_t rx_data[4];
    this->readOneParameter(target_can_id, Parameterlist::RUN_MODE, rx_data);

    return static_cast<RunMode>(rx_data[0]);
}


void Robstride02Driver::setSpeed(uint8_t target_can_id, float speed)
{
    float_byte ftb;
    ftb.f = speed;

    uint8_t data[4];
    data[0] = ftb.b[0];
    data[1] = ftb.b[1];
    data[2] = ftb.b[2];
    data[3] = ftb.b[3];

    this->writeOneParameter(target_can_id, Parameterlist::SPD_REF, data);
}



void Robstride02Driver::setPosition(uint8_t target_can_id, float position)
{
    float_byte ftb;
    ftb.f = position;

    uint8_t data[4];
    data[0] = ftb.b[0];
    data[1] = ftb.b[1];
    data[2] = ftb.b[2];
    data[3] = ftb.b[3];

    this->writeOneParameter(target_can_id, Parameterlist::LOC_REF, data);
}



void Robstride02Driver::setLimitCur(uint8_t target_can_id, float cur)
{
    float_byte ftb;
    ftb.f = cur;

    uint8_t data[4];
    data[0] = ftb.b[0];
    data[1] = ftb.b[1];
    data[2] = ftb.b[2];
    data[3] = ftb.b[3];

    this->writeOneParameter(target_can_id, Parameterlist::LIMIT_CUR, data);
}



float Robstride02Driver::getVelocity(uint8_t target_can_id)
{
    float_byte ftb;
    this->readOneParameter(target_can_id, Parameterlist::MECH_VEL, ftb.b);

    return ftb.f;
}



float Robstride02Driver::getPosition(uint8_t target_can_id)
{
    float_byte ftb;
    this->readOneParameter(target_can_id, Parameterlist::MECH_POS, ftb.b);

    return ftb.f;
}


float Robstride02Driver::getIqf(uint8_t target_can_id)
{
    float_byte ftb;
    this->readOneParameter(target_can_id, Parameterlist::IQF, ftb.b);

    return ftb.f;
}


float Robstride02Driver::getVbus(uint8_t target_can_id)
{
    float_byte ftb;
    this->readOneParameter(target_can_id, Parameterlist::VBUS, ftb.b);

    return ftb.f;
}


float Robstride02Driver::getTemp(uint8_t target_can_id)
{
    struct can_frame rx_frame;

    this->clearBuffer();
    if(this->is_enable) { this->enable(target_can_id); }
    else                { this->disable(target_can_id); }
    this->readMsg(rx_frame);

    uint16_t temp = (rx_frame.data[6] << 8) | rx_frame.data[7];

    return static_cast<float>(temp) / 10.0f;
}


bool Robstride02Driver::isActive(uint8_t target_can_id)
{
    this->clearBuffer();
    if(this->is_enable) { this->enable(target_can_id); }
    else                { this->disable(target_can_id); }

    struct can_frame frame;
    memset(&frame, 0, sizeof(struct can_frame));

    ssize_t ret = read(can_socket_, &frame, sizeof(struct can_frame));
    usleep(2 * 1000);   // wait 2ms

    uint8_t recv_can_id = (frame.can_id >> 8) & 0xff;

    return (target_can_id == recv_can_id) ? true : false; 
}






/*

===== READ MESSAGE =====


struct can_frame frame;
memset(&frame, 0, sizeof(struct can_frame));

while(1)
{
    size_t nbytes = read(can_socket_, &frame, sizeof(struct can_frame));

    if(nbytes > 0)
    {
        if(!(frame.can_id&CAN_EFF_FLAG))
        {
            printf("Received standard frame!\n");
        }
        else
        {
            printf("Received extended frame!\n");
        }

        printf("can_id = 0x%Xn", frame.can_id&0x1FFFFFFF);

        for(uint8_t i=0; i<8; i++)
        {
            printf("data[%d] = %d\n", i, frame.data[i]);
        }

        break;
    }
}

*/