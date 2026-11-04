# This file is included by the architecture specific makefiles,
# i386_make.mak etc.  Those makefiles also include defs.mak which
# defines CFLAGS etc.  Definitions are separate from targets to keep
# the Android makefile happy.

# Targets which do not refer to real files (e.g. don't skip processing
# the 'all' target if a file named 'all' exists):
.PHONY:	all clean objfiles ccver

all: 	$(OUTDIR) \
        $(OUTDIR)/$(STATICNAME) \
        $(OUTDIR)/$(LIBNAME) \
        $(OUTDIR)/$(STATICTEST) \
        $(OUTDIR)/$(LIBTEST)

# To clean, just remove the output directory, as all objects and 
# libraries end up there.
clean:
	rm -rf $(OUTDIR)

# Create output directory, plus required sub-directories.
$(OUTDIR):
	@for dir in $(C_OBJECT_DIRS) ; do \
		mkdir -p $$dir ; \
	done

# The objfiles target uses this target for each of its prerequisites.
# Note that '$<' is our prerequisite (e.g. source/ftdi_i2c.c) 
# and '$@' is our target (e.g. build/i386/libmpsse/ftdi_i2c.o).
# TODO Support splint (will need -booltype BOOL -booltype BOOLEAN)
$(OUTDIR)/%.o : %.c
	@echo '    $<'
	@$(CC) -c $(INCDIRECTORIES) $(DEFINES) $(CFLAGS) $< -o $@

objfiles:	$(OUTDIR) \
			$(C_OBJECTS)
	echo $<
	echo $@
	cp $(C_HEADERS) $(OUTDIR)

# Shared (dynamic) library
$(OUTDIR)/$(LIBNAME): objfiles
	@echo Shared library: $(OUTDIR)/$(LIBNAME)
	@$(CC) -o $(OUTDIR)/$(LIBNAME) \
		-shared \
		-fPIC \
		$(LINKER_OPTIONS) \
		$(TARGET_MACHINE) \
		$(C_OBJECTS) \
		$(DEPENDENCIES)

# Sanity test of dynamic library
$(OUTDIR)/$(LIBTEST): $(OUTDIR)/$(LIBNAME)
	@echo Test for shared library: $(OUTDIR)/$(LIBTEST)
	$(CC) test/$(TEST_SOURCE) -o $(OUTDIR)/$(LIBTEST) $(OUTDIR)/$(LIBNAME) \
		$(DEFINES) \
		$(INCDIRECTORIES) \
		-Wall -Wextra \
		$(TARGET_MACHINE) \
		-ggdb \
		-ldl \
		$(DEPENDENCIES)

# Static library
$(OUTDIR)/$(STATICNAME): objfiles
	@echo Static library: $(OUTDIR)/$(STATICNAME)
	@$(AR) cr $(OUTDIR)/$(STATICNAME) $(C_OBJECTS)

# Sanity test of static library
$(OUTDIR)/$(STATICTEST): $(OUTDIR)/$(STATICNAME)
	@echo Test for static library: $(OUTDIR)/$(STATICTEST)
	$(CC) test/$(TEST_SOURCE) -o $(OUTDIR)/$(STATICTEST) $(OUTDIR)/$(STATICNAME) \
		$(DEFINES) \
		$(INCDIRECTORIES) \
		-Wall -Wextra \
		$(TARGET_MACHINE) \
		-ggdb \
		$(DEPENDENCIES)

# Text file with build and target architecture info
$(OUTDIR)/$(BASENAME).txt: $(OUTDIR)/$(LIBNAME)
	@echo "Output of 'file' command:" > $(OUTDIR)/$(BASENAME).txt
	@echo "=========================" >> $(OUTDIR)/$(BASENAME).txt
	@file $(OUTDIR)/$(LIBNAME) >> $(OUTDIR)/$(BASENAME).txt
	@echo "Output of '$(READELF)' command:" >> $(OUTDIR)/$(BASENAME).txt
	@echo "===============================" >> $(OUTDIR)/$(BASENAME).txt
	@$(READELF) $(OUTDIR)/$(LIBNAME) >> $(OUTDIR)/$(BASENAME).txt

ccver:
	$(CC) -v

