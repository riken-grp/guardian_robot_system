# This uses the system defaults for CC, LD and AR, so the resultant
# binaries will be perfect for the system used to build them.
# 
# This is useful for building Raspberry Pi images, or any other
# platform which may be emulated with QEMU.

OUTDIR = build/native

# Targets (e.g. 'all' and 'clean') and definitions (e.g. CFLAGS) are in
# separate files because Android has its own implicit targets but still
# needs the definitions.
include defs.mak
include targets.mak
