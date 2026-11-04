MPSSE for Linux
---------------

As Linux distributions vary these instructions are a guide to installation 
and use.  FTDI has tested the driver with LTS Ubuntu distributions for 
x86 and x86_64 architectures, and Raspbian on Raspberry Pi.

FTDI developed libmpsse to extend libftd2xx primarily to aid porting Windows 
applications written with D2XX to Linux.  We intend the APIs to behave the 
same on Windows and Linux so if you notice any differences, please contact us 
(see http://www.ftdichip.com/FTSupport.htm).

FTDI do release the source code for libmpsse but not libftd2xx. An up-to-date
copy of libftd2xx is required to use the libmpsse library.

The libftd2xx library must be installed as a shared library on the system.


Installing the D2XX shared library and static library.
------------------------------------------------------

1.  tar xfvz libmpsse-x86_64-1.0.5.tgz

This unpacks the archive, creating the following directory structure:

    build
        libmpsse        (re-linkable objects)
        libmpsse.a      (static library)
        libmpsse.so.1.0.5   (dynamic library)
        libmpsse.txt    (platform-specific information)
    include
        ftdi_spi.h      (header file for SPI API)
        ftdi_i2c.h      (header file for I2C API)
    libftd2xx
        ftd2xx.h        (header file for D2XX API)
        WinTypes.h      (standard Windows C data types)
    source              (source code to build library and dll)
        ftdi_spi.c
        ftdi_i2c.c
        ftdi_infra.c
        ftdi_mid.c
        ftdi_infra.h
        ftdi_mid.h
        ftdi_common.h
    test
        test.c          (test program for library and dll)

2.  cd build

3.  sudo -s 
  or, if sudo is not available on your system: 
    su

Promotes you to super-user, with installation privileges.  If you're
already root, then step 3 (and step 7) is not necessary.

4.  cp libmpsse.* /usr/local/lib

Copies the libraries to a central location.

5.  chmod 0755 /usr/local/lib/libmpsse.so.1.0.5

Allows non-root access to the shared object.

6.  ln -sf /usr/local/lib/libmpsse.so.1.0.5 /usr/local/lib/libmpsse.so

Creates a symbolic link to the 1.0.5 version of the shared object.

7.  cd ..
    cp include/*.h  /usr/local/include
	
Copies the header files to a central location. The installation of libftd2xx will put
ftd2xx.h and WinTypes.h in this location already.

8.  ldconfig -v

Update the linker shared object cache to include the newly installed library.

9.  exit

Ends your super-user session.


Building the shared-object examples.
------------------------------------

1.  make -f native.mak

This rebuilds the libraries, the shared-object and static library test file.

2. sudo build/native/static_test

With an FTDI device connected to a USB port run the static library test file.

2. sudo build/native/dynamic_test

With an FTDI device connected to a USB port run the shared object test file.

