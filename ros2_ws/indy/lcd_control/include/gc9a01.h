#pragma once

#include "SPIinterface.h"
#include <thread>
#include <chrono>

namespace gc9a01
{
  class gc9a01
  {
  protected:
    SPIinterface::FT232H_SPI ft232spi;
    bool initialize = false;

    // ID 0xFF = ALL
    void writecommand(uint8_t cmd);
    void writecommand(uint8_t cmd, uint8_t EndCSClear);
    void writedata(uint8_t data);
    void writedata(uint8_t *data, uint32_t len);
    void writedata(uint8_t *data, uint32_t len, uint8_t EndCSClear);

    void GPIO_write(UCHAR IO, uint8_t Level);
    void initializeLCD();

    void setWundow(int32_t _widthStart, int32_t _heightStart, int32_t _widthEnd, int32_t _heightEnd);

    uint8_t GPIO_LOW = 0;
    uint8_t GPIO_HIGH = 1;

    #define LCD_NUM 2

    // Data/Command high = data mode
    UCHAR gpio_DC = 0x1 << 1;  // IO1  DC

    // HIGH Normal
    UCHAR gpio_RST = 0x1 << 0; // IO0 RST

    UCHAR IO_MODE = 0;
    UCHAR NowIO = 0;

    const static uint16_t height = 240;
    const static uint16_t width  = 240;

    enum Command
    {
      TFT_MAC   = 0x36, // Memory Access Control (36h)
      TFT_CASET = 0x2A, // Column Address Set (2Ah)
      TFT_PASET = 0x2B, // Row Address Set (2Bh)
      TFT_RAMWR = 0x2C, // Memory Write (2Ch)

    };
    //uint8_t TFT_CASET = 0x2A;
    //uint8_t TFT_PASET = 0x2B;
    //uint8_t TFT_RAMWR = 0x2C;
  
    
  public:
    gc9a01(/* args */);
    ~gc9a01();

    uint8_t LCD_Num(void) { return LCD_NUM; }

    bool FullScreenColorWrite(uint8_t R, uint8_t G, uint8_t B);
    bool FullScreenColorWrite(uint16_t RGB565);

    bool ImageWite(uint16_t *RGB565, uint32_t len);
    bool ImageWite(uint8_t *RGB565, uint32_t len);
    bool ImageWiteRGB_888(uint8_t *RGB888, uint32_t len);
    
    bool SelectLCD_ID(uint8_t LCDid);
    
    uint16_t FormatConverter_Color565(uint8_t R, uint8_t G, uint8_t B);

    bool Init(void);
  };
  
  gc9a01::gc9a01(/* args */)
  {
    IO_MODE = 0;
    IO_MODE |= gpio_RST;
    IO_MODE |= gpio_DC;

    NowIO = IO_MODE;
  }

  
  gc9a01::~gc9a01()
  {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    // ResetLCD
    SelectLCD_ID(0);
    FullScreenColorWrite(0x00, 0x00, 0x00);

    SelectLCD_ID(1);
    FullScreenColorWrite(0x00, 0x00, 0x00);
    
    printf("[GC9A01] Shutdown Complete\n");
  }
  
  /// @brief Init Func
  /// @param  None
  /// @return Success:True
  bool gc9a01::Init(void)
  {
    if(initialize) { return false; }

    if(!ft232spi.Init()) { return false; } // SPI Not Open

    FT_WriteGPIO(ft232spi.ftHandle, IO_MODE, NowIO);

    writedata(0x00);


    // --------------------- LCD RESET  ---------------------

    GPIO_write(gpio_RST, GPIO_HIGH);
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
    GPIO_write(gpio_RST, GPIO_LOW);
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    GPIO_write(gpio_RST, GPIO_HIGH);

    std::this_thread::sleep_for(std::chrono::milliseconds(150));


    // --------------------- LCD Initialize  ---------------------

    // Select LCD 0
    SelectLCD_ID(0);
    
    // initialize LCD 0
    initializeLCD();

    // Select LCD 1
    SelectLCD_ID(1);
    
    // initialize LCD 1
    initializeLCD();
    
    // SELECT LCD 0
    SelectLCD_ID(0);

    // --------------------- End Init  ---------------------

    initialize = true;
    printf("[GC9A01] Init Complete\n");
    
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    // ResetLCD
    SelectLCD_ID(0);
    FullScreenColorWrite(0x00, 0x00, 0x00);

    SelectLCD_ID(1);
    FullScreenColorWrite(0x00, 0x00, 0x00);

    // SELECT LCD 0
    SelectLCD_ID(0);

    return true; // gc9a01 Ready
  }


  /// @brief internal write cmd func
  /// @param cmd cmd
  void gc9a01::writecommand(uint8_t cmd)
  {
    writecommand(cmd, 1);
  }

  void gc9a01::writecommand(uint8_t cmd, uint8_t EndCSClear)
  {
    //if(!initialize) { return; }

    GPIO_write(gpio_DC, GPIO_LOW); // DC LOW = Cmd mode

    ft232spi.sendbyte(&cmd, 1, EndCSClear);

    GPIO_write(gpio_DC, GPIO_HIGH); // DC HIGH = Data mode
  }


  /// @brief internal write data func
  /// @param data data
  void gc9a01::writedata(uint8_t data)
  {
    //if(!initialize) { return; }

    GPIO_write(gpio_DC, GPIO_HIGH); // DC HIGH = Data mode

    ft232spi.sendbyte(&data, 1);
  }


  
  inline void gc9a01::writedata(uint8_t *data, uint32_t len)
  {
    writedata(data, len, 1);
  }

  void gc9a01::writedata(uint8_t *data, uint32_t len, uint8_t EndCSClear)
  {
    GPIO_write(gpio_DC, GPIO_HIGH); // DC HIGH = Data mode
    ft232spi.sendbyte(data, len, EndCSClear);
    //std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }


  /// @brief internal write GPIO func
  /// @param IO Select IO
  /// @param Level IO Level
  void gc9a01::GPIO_write(UCHAR IO, uint8_t Level)
  {
    if(Level == 0)
    {
      if((NowIO & IO) == 0) { return; }
      NowIO &= ~(IO);
    }
    else
    {
      if((NowIO & IO) == 1) { return; }
      NowIO |= (IO);
    }

    FT_WriteGPIO(ft232spi.ftHandle, IO_MODE, NowIO);
  }

  
  // --------------------- Write Display Interface  ---------------------


  inline bool gc9a01::FullScreenColorWrite(uint8_t R, uint8_t G, uint8_t B)
  {
    return FullScreenColorWrite(FormatConverter_Color565(R, G, B));
  }
  
  bool gc9a01::FullScreenColorWrite(uint16_t RGB565)
  {
    if(!initialize) { return false; }

    writecommand(Command::TFT_MAC);
    writedata(0x08);

    uint8_t spibuf[width * 2 * height];
    for (uint64_t i = 0; i < sizeof(spibuf) / sizeof(spibuf[0]); i+=2)
    {
      spibuf[i] = (uint8_t)(RGB565 >> 8);
      spibuf[i + 1] = (uint8_t)RGB565;
    }

    setWundow(0, 0, height - 1, width - 1);
    writedata(spibuf, width * 2 * height);
    //for (uint16_t i = 0; i < height * 2; i++)
    //{
    //  writedata(spibuf, width * 2, (uint8_t)(i == height * 2 - 1));
    //}
    

    return true;
  }


  bool gc9a01::ImageWite(uint16_t *RGB565, uint32_t len)
  {
    if(!initialize) { return false; }

    uint8_t spibuf[width * 2 * height];
    for (uint64_t i = 0; i < ( sizeof(spibuf) / sizeof(spibuf[0]) ) / 2; i++)
    {
      spibuf[i * 2] = (uint8_t)(RGB565[i] >> 8);
      spibuf[i * 2 + 1] = (uint8_t)RGB565[i];
    }
    return ImageWite(spibuf, len * 2);
  }

  bool gc9a01::ImageWite(uint8_t *RGB565, uint32_t len)
  {
    if(!initialize) { return false; }

    writecommand(Command::TFT_MAC);
    writedata(0x08);

    std::this_thread::sleep_for(std::chrono::milliseconds(1));

    setWundow(0, 0, width - 1, height / 2 - 1);
    writedata(RGB565, len / 2);

    std::this_thread::sleep_for(std::chrono::milliseconds(1));

    writecommand(Command::TFT_MAC);
    writedata(0x08);

    std::this_thread::sleep_for(std::chrono::milliseconds(1));

    setWundow(0, height / 2, width - 1, height - 1);
    writedata(&(RGB565[len / 2]), len / 2);

    return true;
  }


  
  bool gc9a01::ImageWiteRGB_888(uint8_t *RGB888, uint32_t unuse)
  {
    (void)unuse; // unuse
    uint16_t ColorBuffer[240 * 240];
    for (uint32_t i = 0; i < sizeof(ColorBuffer) / sizeof(ColorBuffer[0]); i++)
    {
      ColorBuffer[i] = FormatConverter_Color565(RGB888[i * 3], RGB888[i * 3 + 1], RGB888[i * 3 + 2]);
    }

    return ImageWite(ColorBuffer, 240 * 240);
  }
  

  // R 0xF800: 1111 1000 0000 0000
  // G 0x07E0: 0000 0111 1110 0000
  // B 0x001F: 0000 0000 0001 1111
  
  inline uint16_t gc9a01::FormatConverter_Color565(uint8_t R, uint8_t G, uint8_t B)
  {
    return (((R & 0xF8) << (11 - 3)) & 0xF800) | (((G & 0xFC) << (5 - 2)) & 0x07E0 ) |  (((B & 0xF8) >> 3) & 0x001F );
  }

  
  void gc9a01::setWundow(int32_t _widthStart, int32_t _heightStart, int32_t _widthEnd, int32_t _heightEnd)
  {
    uint8_t spibuf[4];
    writecommand(Command::TFT_CASET, 0);
    spibuf[0] = (uint8_t) (_widthStart >> 8);
    spibuf[1] = (uint8_t) _widthStart;
    spibuf[2] = (uint8_t) (_widthEnd >> 8);
    spibuf[3] = (uint8_t) _widthEnd;
    writedata(spibuf, 4, 0);

    writecommand(Command::TFT_PASET, 0);
    spibuf[0] = (uint8_t) (_heightStart >> 8);
    spibuf[1] = (uint8_t) _heightStart;
    spibuf[2] = (uint8_t) (_heightEnd >> 8);
    spibuf[3] = (uint8_t) _heightEnd;
    writedata(spibuf, 4, 0);
    
    writecommand(Command::TFT_RAMWR, 0);
  }


  bool gc9a01::SelectLCD_ID(uint8_t LCDid)
  {
    return ft232spi.SelectDevice(LCDid);
  }


  /// @brief internal initialize LCD Command Func from TFT_eLCD
  void gc9a01::initializeLCD()
  {
    writecommand(0xEF); // Inter Register Enable 2
    writecommand(0xEB); // N/A
    writedata(0x14);

    writecommand(0xFE); // Inter Register Enabl 1
    writecommand(0xEF); // Inter Register Enabl 2

    writecommand(0xEB); // N/A
    writedata(0x14);

    writecommand(0x84); // N/A
    writedata(0x40);

    writecommand(0x85); // N/A
    writedata(0xFF);

    writecommand(0x86); // N/A
    writedata(0xFF);

    writecommand(0x87); // N/A
    writedata(0xFF);

    writecommand(0x88); // N/A
    writedata(0x0A);

    writecommand(0x89); // N/A
    writedata(0x21);

    writecommand(0x8A); // N/A
    writedata(0x00);

    writecommand(0x8B); // N/A
    writedata(0x80);

    writecommand(0x8C); // N/A
    writedata(0x01);

    writecommand(0x8D); // N/A
    writedata(0x01);

    writecommand(0x8E); // N/A
    writedata(0xFF);

    writecommand(0x8F); // N/A
    writedata(0xFF);

    writecommand(0xB6); // N/A
    writedata(0x00);
    writedata(0x20);

    writecommand(0x3A); // COLMOD: Pixel Format Set (3Ah)
    writedata(0x05);    // 16bit / pixel mode

    writecommand(0x90); // N/A
    writedata(0x08);
    writedata(0x08);
    writedata(0x08);
    writedata(0x08);

    writecommand(0xBD); // N/A
    writedata(0x06);

    writecommand(0xBC); // N/A
    writedata(0x00);

    writecommand(0xFF); // N/A
    writedata(0x60);
    writedata(0x01);
    writedata(0x04);

    writecommand(0xC3); // Power C ontrol 2 (C3h)
    writedata(0x13);    // grayscale voltage level
    writecommand(0xC4); // Power C ontrol 3 ( C4 h)
    writedata(0x13);    // grayscale voltage level

    writecommand(0xC9); //Power C ontrol 4 (C9h)
    writedata(0x22);    // grayscale voltage level

    writecommand(0xBE); // N/A
    writedata(0x11);

    writecommand(0xE1); // N/A
    writedata(0x10);
    writedata(0x0E);

    writecommand(0xDF); // N/A
    writedata(0x21);
    writedata(0x0c);
    writedata(0x02);

    writecommand(0xF0); // SET_GAMMA1 (F0h)
    writedata(0x45);
    writedata(0x09);
    writedata(0x08);
    writedata(0x08);
    writedata(0x26);
    writedata(0x2A);

    writecommand(0xF1); // SET_GAMMA2 (F1h)
    writedata(0x43);
    writedata(0x70);
    writedata(0x72);
    writedata(0x36);
    writedata(0x37);
    writedata(0x6F);

    writecommand(0xF2); // SET_GAMMA3 (F2h)
    writedata(0x45);
    writedata(0x09);
    writedata(0x08);
    writedata(0x08);
    writedata(0x26);
    writedata(0x2A);

    writecommand(0xF3); // SET_GAMMA4 (F3h)
    writedata(0x43);
    writedata(0x70);
    writedata(0x72);
    writedata(0x36);
    writedata(0x37);
    writedata(0x6F);

    writecommand(0xED); // N/A
    writedata(0x1B);
    writedata(0x0B);

    writecommand(0xAE); // N/A
    writedata(0x77);

    writecommand(0xCD); // N/A
    writedata(0x63);

    writecommand(0x70); // N/A
    writedata(0x07);
    writedata(0x07);
    writedata(0x04);
    writedata(0x0E);
    writedata(0x0F);
    writedata(0x09);
    writedata(0x07);
    writedata(0x08);
    writedata(0x03);

    writecommand(0xE8); // Frame Rate (E8h)
    writedata(0x34);    // 4 dot inversion

    writecommand(0x62); // N/A
    writedata(0x18);
    writedata(0x0D);
    writedata(0x71);
    writedata(0xED);
    writedata(0x70);
    writedata(0x70);
    writedata(0x18);
    writedata(0x0F);
    writedata(0x71);
    writedata(0xEF);
    writedata(0x70);
    writedata(0x70);

    writecommand(0x63); // N/A
    writedata(0x18);
    writedata(0x11);
    writedata(0x71);
    writedata(0xF1);
    writedata(0x70);
    writedata(0x70);
    writedata(0x18);
    writedata(0x13);
    writedata(0x71);
    writedata(0xF3);
    writedata(0x70);
    writedata(0x70);

    writecommand(0x64); // N/A
    writedata(0x28);
    writedata(0x29);
    writedata(0xF1);
    writedata(0x01);
    writedata(0xF1);
    writedata(0x00);
    writedata(0x07);

    writecommand(0x66); // N/A
    writedata(0x3C);
    writedata(0x00);
    writedata(0xCD);
    writedata(0x67);
    writedata(0x45);
    writedata(0x45);
    writedata(0x10);
    writedata(0x00);
    writedata(0x00);
    writedata(0x00);

    writecommand(0x67); // N/A
    writedata(0x00);
    writedata(0x3C);
    writedata(0x00);
    writedata(0x00);
    writedata(0x00);
    writedata(0x01);
    writedata(0x54);
    writedata(0x10);
    writedata(0x32);
    writedata(0x98);

    writecommand(0x74); // N/A
    writedata(0x10);
    writedata(0x85);
    writedata(0x80);
    writedata(0x00);
    writedata(0x00);
    writedata(0x4E);
    writedata(0x00);

    writecommand(0x98); // N/A
    writedata(0x3e);
    writedata(0x07);

    writecommand(0x35); // Tearing Effect Line ON (35h)
    writecommand(0x21); // Display Inversion ON (21h)

    writecommand(0x11); // Sleep Out Mode (11h) Sleep OFF
    std::this_thread::sleep_for(std::chrono::milliseconds(120));
    writecommand(0x29); // Display ON (29h)
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

}