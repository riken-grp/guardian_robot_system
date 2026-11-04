#pragma once

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "LibMPSSE/build_lib/libmpsse_spi.h"
#include "LibMPSSE/libftd2xx/ftd2xx.h"
//#include "ftdi_mid.h"

namespace SPIinterface
{
  class FT232H_SPI
  {
  protected:
    const static uint32_t bufsize = 120000;

    uint8_t spibuf[bufsize];

    ChannelConfig ft232_Conf;
    FT_STATUS status;

    bool initialize = false;

  public:
    FT_HANDLE ftHandle;
    
    FT232H_SPI();
    ~FT232H_SPI();
    bool Init(void);
    bool sendbyte(uint8_t *data, uint32_t Len);
    bool sendbyte(uint8_t *data, uint32_t Len, uint8_t EndCSClear);
    bool readbyte(uint8_t *data, uint32_t Len) { (void)data; (void)Len; return false; }
    bool SelectDevice(uint8_t DeviceID);
    uint32_t bufmax(void) { return bufsize;}
  };
  
  FT232H_SPI::FT232H_SPI()
  {
    //SPIChannel = 0;
    initialize = false;
    //Init();
  }
  
  FT232H_SPI::~FT232H_SPI()
  {
    if(initialize) { SPI_CloseChannel(ftHandle); }
    Cleanup_libMPSSE();
    printf("FT232H_SPI Shutdown Complete\n");
  }
  
  bool FT232H_SPI::Init()
  {
    if(initialize) { return true; }

  //#ifdef _MSC_VER
	  Init_libMPSSE();
  //#endif
    ft232_Conf.ClockRate = 30000000;
    ft232_Conf.LatencyTimer = 255;
    ft232_Conf.configOptions = 
          SPI_CONFIG_OPTION_MODE0 |
          SPI_CONFIG_OPTION_CS_DBUS3 |
          SPI_CONFIG_OPTION_CS_ACTIVELOW;
    ft232_Conf.Pin = 0xFFFFFFFF;
    ft232_Conf.currentPinState = 0xFFFF;

    // --------------------- Get D2XX DLL version ---------------------
    DWORD libraryVersion = 0;
    DWORD libraryMSSPVersion = 0;

    if(FT_GetLibraryVersion(&libraryVersion) == FT_OK)
    {
      //printf("Library version = 0x%x\n", (unsigned int)libraryVersion);
      Ver_libMPSSE(&libraryMSSPVersion, &libraryVersion);
      printf("[FT232H_SPI] MSSP Ver = 0x%lx / FTD2xx  Library version = 0x%x\n", (unsigned long)libraryMSSPVersion, (unsigned int)libraryVersion);
    }
    else
    {
      printf("[FT232H_SPI] Error reading library version.\n");
      return false;
    }

    static DWORD SPIChannel;
    status = SPI_GetNumChannels(&SPIChannel);
    printf("[FT232H_SPI] Available SPI channels = %d Status = %s\n", SPIChannel, status == FT_OK ? "OK" : "NG");

    if(SPIChannel > 0) 
    {
      printf("[FT232H_SPI] OpenSPI CH1\n");
      status = SPI_OpenChannel(0, &ftHandle);
      printf("\n[FT232H_SPI] handle=0x%p status=0x%x\n",ftHandle,status);

      status = SPI_InitChannel(ftHandle,&ft232_Conf);
      if(status != FT_OK) 
      {
        printf("[FT232H_SPI] Init Failure\n");
        return false;
      }
      else
      {
        printf("[FT232H_SPI] Init Complete\n");
        initialize = true;
        return true; // SPI Open
      }
    }
    return false; // SPI Not Open
  }
  
  inline bool FT232H_SPI::sendbyte(uint8_t *data, uint32_t Len)
  {
    return sendbyte(data, Len, 1);
  }

  bool FT232H_SPI::sendbyte(uint8_t *data, uint32_t Len, uint8_t EndCSClear)
  {
    if(!initialize) { return false; } // not initialize
    if(Len > sizeof(spibuf) / sizeof(spibuf[0])) { return false; } // Over buf size

    DWORD sizeToTransfer = Len;
    DWORD sizeTrans = 0;
    LPDWORD sizeTransfered = &sizeTrans;

    for (uint32_t i = 0; i < Len; i++)
    {
      spibuf[i] = data[i];
    }

    //printf("1:%d 2:%d 3:%d 4:%d\n", ftHandle == NULL, spibuf == NULL, sizeToTransfer == NULL, sizeTransfered == NULL);

    if(EndCSClear != 0)
    {
      status = SPI_Write(ftHandle, spibuf, sizeToTransfer, sizeTransfered, 
                        SPI_TRANSFER_OPTIONS_SIZE_IN_BYTES |
                        SPI_TRANSFER_OPTIONS_CHIPSELECT_ENABLE |
                        SPI_TRANSFER_OPTIONS_CHIPSELECT_DISABLE);
    
    }
    else
    {
      status = SPI_Write(ftHandle, spibuf, sizeToTransfer, sizeTransfered, 
                        SPI_TRANSFER_OPTIONS_SIZE_IN_BYTES |
                        SPI_TRANSFER_OPTIONS_CHIPSELECT_ENABLE);
    
    }
    
    
    if(status == FT_OK)
    {
      return true;
    }
    
    return false;
  }
  
  bool FT232H_SPI::SelectDevice(uint8_t DeviceID)
  {
    if(!initialize) { return false; } // not initialize

    DWORD CS_Config = 0;
    switch (DeviceID)
    {
    case 0:
      CS_Config = \
        SPI_CONFIG_OPTION_MODE0 | \
        SPI_CONFIG_OPTION_CS_DBUS3 | \
        SPI_CONFIG_OPTION_CS_ACTIVELOW;
      break;
    
    case 1:
      CS_Config = \
        SPI_CONFIG_OPTION_MODE0 | \
        SPI_CONFIG_OPTION_CS_DBUS4 | \
        SPI_CONFIG_OPTION_CS_ACTIVELOW;
      break;
    
    default:
      return false;
      break;
    }

    FT_STATUS status = FT_OTHER_ERROR;
    status = SPI_ChangeCS(ftHandle, CS_Config);
    //printf("return Status%d\n", (uint8_t)status);
    
    return status == FT_OK;
  }
} // namespace FT232H_SPI
