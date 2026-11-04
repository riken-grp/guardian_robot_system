# This file is included by each platform-specific makefile.

# Get Subversion revision number: svn info output includes a line
# like 'Revision: 123' - awk gets word 2 of line starting 'Revision'
# REVNO = $(shell svn info | awk '/^Revision/ {print $$2}')
# Above doesn't work on Jenkins whose svn plugin uses an old version
# of the svn client.  So specify REVNO on Make command line!
REVNO ?= 1
# Calculate high and low bytes of REVNO.  Assumes bc installed.
REV_HIGH := $(shell echo "$(REVNO)/99" | bc)
REV_LOW := $(shell echo "$(REVNO)%99" | bc)

LIBTEST = dynamictest
# Build D3XX by specifying BASENAME=libftd3xx to Make.  Default to d2xx.
BASENAME ?= libmpsse
STATICNAME = $(BASENAME).a
STATICTEST = statictest
UNAME := $(shell uname)

DEFINES = \
    -D_GNU_SOURCE \
    -DFT_VER_MAJOR=$(MAJOR_VERSION) \
    -DFT_VER_MINOR=$(MINOR_VERSION) \
    -DFT_VER_BUILD=$(BUILD_VERSION) \
    -DFT_VER_BUILD_HIGH=$(REV_HIGH) \
    -DFT_VER_BUILD_LOW=$(REV_LOW) \

CFLAGS = $(TARGET_MACHINE)
CFLAGS += \
    -Wall \
    -c \
    -fPIC \
    -fno-stack-protector \

# The python release scripts depend on the D2XX case preceding the D3XX case.
ifeq ($(BASENAME), libmpsse)
    MAJOR_VERSION = 1
    MINOR_VERSION = 0
    BUILD_VERSION = 5
    MIN_OSX = 10.8
    TEST_SOURCE = test.c
    C_INCLUDES = source \
		include \
		libftd2xx
    C_SOURCES = \
		source/ftdi_infra.c \
		source/ftdi_mid.c \
		source/ftdi_i2c.c \
		source/ftdi_spi.c
	C_HEADERS = include/libmpsse_i2c.h \
		include/libmpsse_spi.h
else
endif

# Assume target is Mac OS if build host is Mac OS; any other host
# (Linux or Windows) targets Linux (which is also used for Android).
ifeq ($(UNAME), Darwin)
    DEFINES += -D_OSX_
    SONAME := $(BASENAME).dylib
    # Mac convention is libxxx.version-number.dylib, unlike Linux (libxxx.so.version-number)
    LIBNAME = $(BASENAME).$(MAJOR_VERSION).$(MINOR_VERSION).$(BUILD_VERSION).dylib
    CFLAGS += -mmacosx-version-min=$(MIN_OSX)
    LINKER_OPTIONS := -mmacosx-version-min=$(MIN_OSX) -Wl,-install_name,$(SONAME)
    DEPENDENCIES := -lpthread -lobjc -framework IOKit -framework CoreFoundation
    READELF := otool -h
else
    DEFINES += -DLINUX
    CFLAGS += -fno-stack-check
    SONAME := $(BASENAME).so
    LIBNAME = $(SONAME).$(MAJOR_VERSION).$(MINOR_VERSION).$(BUILD_VERSION)
    LINKER_OPTIONS := -Wl,-soname,$(SONAME)
    ifeq ($(TARGET_MACHINE), -m64)
        # Map memcpy to a symver wrapper to avoid depending on modern GLibC
        LINKER_OPTIONS += -Wl,--wrap=memcpy
        C_SOURCES += source/memcpy.c
    endif
    DEPENDENCIES := -lpthread -lrt -ldl
    READELF := readelf -A
endif

# To enable debugging, include "DEBUG=1" on the make command line.
# The following line makes DEBUG default to 0, i.e. a release build.
DEBUG ?= 0
ifeq ($(DEBUG), 1)
    # Enable debugging
    DEFINES += -D_DEBUG -DINFRA_DEBUG_ENABLE
    CFLAGS += -ggdb
    #C_SOURCES += ../libFTD2XX/libftd2xx/debug.c
    # Enable Fortify memory checking
    #FORTIFY_SOURCES += ../libFTD2XX/fortify/fortify.c \
    #                   ../libFTD2XX/fortify/fortify-ftdi.c
    #C_INCLUDES += fortify
    #DEFINES += -DFORTIFY
endif

INCDIRECTORIES := $(addprefix -I, $(C_INCLUDES))

# To avoid accessing the real device's EEPROM, include "FAKE_EE=1" 
# on the make command line.
# The following line makes FAKE_EE default to 0.
FAKE_EE ?= 0
ifeq ($(FAKE_EE), 1)
    DEFINES += -DFAKE_EE
endif

# Include Fortify sources (none if Fortify not enabled)
C_SOURCES += $(FORTIFY_SOURCES)

# Create a list of .o files from the list of .c files
C_OBJECTS = $(C_SOURCES:.c=.o)

# Prefix each .o file with the output directory
C_OBJECTS := $(addprefix $(OUTDIR)/, $(C_OBJECTS))

# List of sub-directories for objects (note: sorting removes duplicates)
C_OBJECT_DIRS := $(sort $(dir $(C_OBJECTS)))
