# A bootable SunOS 4.0.3 disk image for a MultiBus Sun-2 with a Xylogics 450.
#
# The image is built by installing SunOS under tme onto an emulated SCSI disk
# that is labelled with the target SMD geometry.  sd and xy address the medium
# identically -- both take a partition's start block from the label as
# cylno * nhead * nsect and run linearly -- so the result is already the image
# the 450 wants, once the boot block, /dev, /etc/fstab and the bad-sector map
# are made xy's.  No emulator emulates the Xylogics 450; this is why.
#
#   make tme        build the emulator (once)
#   make idprom     the machine's IDPROM (once)
#   make images     empty, labelled disk images for both profiles
#   make miniroot   put the distribution miniroot in the swap partition
#   make install    install SunOS from the tape -- unattended, ~20 minutes
#   make console    boot the finished image and watch it
#   make verify     boot a SCSI copy of it under tme, to a login prompt
#   make finish     the host-side label and bad-sector-map fixups
#   make check      everything verifiable without a Sun
#
# Inputs/ is immutable.  ../Sun-2_FPGA is read-only; nothing here writes there.

TOP     := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD   := $(TOP)/build
TOOLS   := $(TOP)/tools
INPUTS  := $(TOP)/Inputs

TME_SRC   := $(BUILD)/tme-src
TME_PREFIX:= $(BUILD)/tme
TMESH     := $(TME_PREFIX)/bin/tmesh
IDPROM    := $(BUILD)/sun2-idprom.bin
ROM       := $(INPUTS)/sun2-multi-rev-R.bin

# 08:00:20 is Sun's OUI; the rest is arbitrary and unused (no Ethernet card).
ETHER   ?= 8:0:20:00:2f:0a

EAGLE   := $(BUILD)/eagle.img
SMALL   := $(BUILD)/small.img

PYTHON  ?= python3
LABEL   := $(PYTHON) $(TOOLS)/sunlabel.py
DKBAD   := $(PYTHON) $(TOOLS)/mkdkbad.py
RUN     := $(TOOLS)/run-sun2

.PHONY: all tme idprom images miniroot install install-small installed-ok \
        verify finish \
        check clean distclean \
        profiles console rescue

all: images

## ---------------------------------------------------------------- emulator

tme: $(TMESH)

$(TMESH):
	@echo "=== building tme 0.8 (headless: no GTK, serial console only) ==="
	rm -rf $(TME_SRC)
	mkdir -p $(BUILD)
	cp -a $(INPUTS)/Run-Sun3-SunOS-4.1.1/tme-0.8_up $(TME_SRC)
	cd $(TME_SRC) && rm -f config.cache && \
	  ./configure --disable-shared --disable-warnings --enable-ltdl-install \
	              --prefix=$(TME_PREFIX) > $(BUILD)/configure.log 2>&1
	@# the tree ships pre-configured, so stop make from re-running autotools
	cd $(TME_SRC) && touch aclocal.m4 && sleep 1 && touch configure config.h.in && \
	  sleep 1 && find . -name Makefile.in -exec touch {} + && \
	  touch config.status Makefile config.h && sleep 1 && touch stamp-h1
	@# serial: generic/Makefile's all-local copies the .la before -j builds it
	cd $(TME_SRC) && $(MAKE) && $(MAKE) install

idprom: $(IDPROM)

$(IDPROM): | $(TMESH)
	@# tme-sun-idprom dumps an existing IDPROM when stdin is not a tty, so
	@# it needs one even though we are making a new one.
	script -qec "$(TME_PREFIX)/bin/tme-sun-idprom 2/120 $(ETHER) > $@" /dev/null
	@test -s $@ || (rm -f $@; echo "IDPROM generation failed"; exit 1)
	@od -Ad -tx1 $@ | head -2

## ------------------------------------------------------------------ images

profiles:
	@$(LABEL) profile --profile eagle
	@echo
	@$(LABEL) profile --profile small

images: $(EAGLE) $(SMALL)

# Fully allocated, not sparse: sun3zoo's advice is to trade the space for the
# speed, and 400 MB is not what it was in 1989.
$(EAGLE):
	mkdir -p $(BUILD)
	$(PYTHON) -c "import sys; sys.path.insert(0,'$(TOOLS)'); \
	  from sun2disk import EAGLE; open('$@','wb').truncate(EAGLE.image_bytes)"
	$(LABEL) write $@ --profile eagle
	$(DKBAD) $@ --profile eagle
	@ls -l $@

$(SMALL):
	mkdir -p $(BUILD)
	$(PYTHON) -c "import sys; sys.path.insert(0,'$(TOOLS)'); \
	  from sun2disk import SMALL; open('$@','wb').truncate(SMALL.image_bytes)"
	$(LABEL) write $@ --profile small
	$(DKBAD) $@ --profile small
	@ls -l $@

## ----------------------------------------------------------------- install

# On real hardware MUNIX copies the miniroot onto the swap partition with dd,
# because its ram-disk root holds dd and mt and nearly nothing else.  We are
# already on a host where the tape files and the disk are both ordinary files,
# so we put it there directly and skip MUNIX entirely.
# The 4.0.3 miniroot, even though the base installed from it is 4.0: a 4.0
# kernel will not boot on a machine with no network to ask who it is.  See the
# head of tools/scripts/install.txt.
miniroot: $(EAGLE)
	$(PYTHON) $(TOOLS)/putminiroot.py $(EAGLE) --profile eagle --release 403

# SunOS 4.0 from the full release, then the 4.0.3 upgrade over it; the tape is
# swapped mid-script.  Unattended, and long -- roughly half an hour of wall
# clock.  Every answer is in tools/scripts/install.txt and doc/INSTALL.md
# explains why each one is what it is.  Watch it with:
#   tail -f build/install.log
install: $(TMESH) $(IDPROM) $(EAGLE) miniroot
	$(RUN) --disk eagle.img --tape 403-1 --script $(TOOLS)/scripts/install.txt \
	       --stop-on '[\r\n]M-INSTALL-COMPLETE' --timeout 3500 \
	       --log $(BUILD)/install.log
	@$(MAKE) --no-print-directory installed-ok IMG=eagle LOG=$(BUILD)/install.log

# The same, for the sim-sized profile.  Its extra step trims the release to fit
# 24.9 MB; see tools/scripts/install-small.txt.
install-small: $(TMESH) $(IDPROM) $(SMALL)
	$(PYTHON) $(TOOLS)/putminiroot.py $(SMALL) --profile small --release 403
	$(RUN) --disk small.img --tape 403-1 --script $(TOOLS)/scripts/install-small.txt \
	       --stop-on '[\r\n]M-INSTALL-COMPLETE' --timeout 3500 \
	       --log $(BUILD)/install-small.log
	@$(MAKE) --no-print-directory installed-ok IMG=small LOG=$(BUILD)/install-small.log

# Boot an installed image and leave the console attached.
console: $(TMESH) $(IDPROM)
	$(RUN) --disk eagle.img --log $(BUILD)/console.log

# Back into the miniroot on an installed disk, to fix something by hand.
rescue: $(TMESH) $(IDPROM)
	$(RUN) --disk eagle.img --tape 403-1 \
	       --script $(TOOLS)/scripts/boot-miniroot.txt --log $(BUILD)/miniroot.log

# Did the install actually install anything?  The completion marker only says
# the script reached its end -- every step can have failed and it still echoes.
# Two things are checked here because both have gone wrong: the filesystem
# filling mid-extraction (which shows up as tar write errors in the log, and
# then as no /boot for installboot to find), and the boot block being the raw
# a.out newfs wrote rather than the xy one installboot strips and patches.
installed-ok:
	@if grep -aqE "file system full|write failed|No space left|bootfile open" $(LOG); then \
	  echo "$(IMG): the log has write failures -- the filesystem filled:"; \
	  grep -aE "file system full|write failed|No space left|bootfile open" $(LOG) | head -4; \
	  exit 1; \
	fi
	@$(LABEL) bootblk $(BUILD)/$(IMG).img --want xy
	@echo "$(IMG): installed"

## ------------------------------------------------------------------ verify

# The finished image cannot be booted here: its boot block is bootxy, which
# carries its own Xylogics driver and goes looking for a controller at 0xEE40
# that no emulator has -- under tme it gets exactly as far as
#
#   Boot: sd(0,0,0)vmunix
#   Timeout Bus Error, addr: 00100644 at 240E66
#
# which is bootxy running from block 1 and finding no 450.  That is the right
# answer, and it is also the strongest evidence tme can give that the xy boot
# block is real and correctly installed.
#
# To exercise the rest -- kernel, root filesystem, init, /etc/rc, getty -- this
# makes a copy, swaps the boot block and fstab for their sd equivalents, and
# boots that.  Nothing else differs, so a login prompt here means the image is
# sound everywhere except the four bytes of device name.
# make verify           the eagle image
# make verify IMG=small the sim-sized one
IMG ?= eagle

verify:
	cp $(BUILD)/$(IMG).img $(BUILD)/$(IMG)-sd.img
	$(RUN) --disk $(IMG)-sd.img --tape 403-1 --script $(TOOLS)/scripts/to-sd.txt \
	       --stop-on '[\r\n]M-CONVERT-COMPLETE' --timeout 900 \
	       --log $(BUILD)/tosd-$(IMG).log
	@# A literal "login:" also proves the console is eight bits: getty's
	@# default is 7E1, which would arrive as 363 365 356 262 240 l o 347 i 356.
	$(RUN) --disk $(IMG)-sd.img --timeout 1800 --stop-on 'login:' \
	       --log $(BUILD)/verify-$(IMG).log
	@echo "$(IMG): reached a login prompt"

## ------------------------------------------------------------------ finish

# Everything that turns an installed SCSI disk into an xy disk on the host
# side.  The parts that must happen inside SunOS (MAKEDEV xy0, /etc/fstab,
# installboot with bootxy) are in doc/INSTALL.md.
finish:
	@for img in $(EAGLE) $(SMALL); do \
	  test -f $$img || continue; \
	  prof=eagle; case $$img in *small*) prof=small;; esac; \
	  $(LABEL) repair $$img --profile $$prof || exit 1; \
	  $(DKBAD)        $$img --profile $$prof || exit 1; \
	  $(LABEL) dump   $$img | tee $(TOP)/doc/$$prof.label.txt; \
	done

## ------------------------------------------------------------------- check

check:
	$(PYTHON) $(TOOLS)/selftest.py
	@for img in $(EAGLE) $(SMALL); do \
	  test -f $$img || continue; \
	  prof=eagle; case $$img in *small*) prof=small;; esac; \
	  $(LABEL) check $$img --profile $$prof || exit 1; \
	  $(DKBAD) $$img --profile $$prof --verify || exit 1; \
	  $(LABEL) bootblk $$img --want xy || exit 1; \
	done

clean:
	rm -f $(BUILD)/SUN2-MULTIBUS $(BUILD)/console.log

distclean:
	rm -rf $(BUILD)
