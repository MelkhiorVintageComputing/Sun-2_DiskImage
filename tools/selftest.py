#! /usr/bin/env python3
"""Checks for the label and bad-sector tools that need no Sun to run.

Most of these assert against something outside this repository -- the PROM's
chklabel(), the driver's dkbad arithmetic, the geometry in format.dat -- so
they are worth having even though the code is short.
"""

import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sun2disk import (SECSIZE, DKL_MAGIC, EAGLE, SMALL, PROFILES,
                      build_dkbad, build_label, checksum, parse_label)

failures = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        failures.append(name)


print("geometry")
# format.dat in Inputs/sunos403/tape1/07. gives the Eagle as
#   ncyl 840 : acyl 2 : pcyl 842 : nhead 20 : nsect 46 : rpm 3961
check("eagle matches format.dat's Fujitsu-M2351 Eagle",
      (EAGLE.ncyl, EAGLE.acyl, EAGLE.nhead, EAGLE.nsect, EAGLE.rpm)
      == (840, 2, 20, 46, 3961))
# sun2_xy450.sv power-up drive type 2: max_head 19, max_sect 45, max_cyl 841,
# which is this drive counted from zero.
check("eagle is the FPGA's drive type 2",
      (EAGLE.nhead - 1, EAGLE.nsect - 1, (EAGLE.ncyl + EAGLE.acyl) - 1)
      == (19, 45, 841))
# tb/tb_sun2.sv instantiates blk_file with the default MAX_BLOCKS = 65536.
check("small fits the boot testbench's 32 MiB blk_file",
      SMALL.total_blocks <= 65536,
      "%d blocks" % SMALL.total_blocks)
for name, geom in sorted(PROFILES.items()):
    check("%s is within the 11-bit cyl / 8-bit head+sector address" % name,
          not geom.check(), "; ".join(geom.check()))
    check("%s bad-sector map is on the medium" % name,
          geom.dkbad_lba < geom.total_blocks)
    # The miniroot is dd'd into the swap partition during the install.
    miniroot = os.path.join(os.path.dirname(HERE),
                            "Inputs", "sunos403", "tape1", "04.")
    if os.path.exists(miniroot):
        need = -(-os.path.getsize(miniroot) // SECSIZE)
        check("%s partition b holds the %d-block miniroot" % (name, need),
              geom.parts["b"][1] >= need,
              "b is %d blocks" % geom.parts["b"][1])

print("label")
lab = build_label(EAGLE)
check("label is one sector", len(lab) == SECSIZE)
check("magic is 0xDABE at 508", struct.unpack_from(">H", lab, 508)[0] == DKL_MAGIC)
# chklabel(): sum ^= *sp++ over all 256 shorts must come out zero.
total = 0
for (word,) in struct.iter_unpack(">H", lab):
    total ^= word
check("chklabel() xor over all 256 shorts is zero", total == 0, "got 0x%04X" % total)
parsed = parse_label(lab)
check("round-trips through parse_label",
      (parsed["ncyl"], parsed["acyl"], parsed["nhead"], parsed["nsect"])
      == (EAGLE.ncyl, EAGLE.acyl, EAGLE.nhead, EAGLE.nsect))
# xyboot() walks base heads 0..3 and drive types 0..3 and only accepts a label
# that agrees with where it was found; head 0 is what it tries first.
check("dkl_bhead and dkl_ppart are both zero",
      (parsed["bhead"], parsed["ppart"]) == (0, 0))
check("partitions survive the round trip",
      all(parsed["parts"][k] == v for k, v in EAGLE.parts.items()))
# A label read with the sector bytes swapped still passes the checksum -- it is
# only the magic that catches it.  Worth knowing the check is real.
swapped = bytearray(lab)
swapped[0::2], swapped[1::2] = lab[1::2], lab[0::2]
check("a byte-swapped label still checksums (so magic is the only guard)",
      checksum(swapped) == struct.unpack_from(">H", swapped, 510)[0])
check("...and its magic is wrong",
      struct.unpack_from(">H", swapped, 508)[0] != DKL_MAGIC)

print("bad-sector map")
bad = build_dkbad()
check("dkbad is one sector", len(bad) == SECSIZE)
check("bt_csn, bt_mbz, bt_flag are zero",
      struct.unpack_from(">iHH", bad, 0) == (0, 0, 0))
entries = struct.unpack_from(">252H", bad, 8)
check("all 126 entries are 0xFFFF non-entries",
      all(w == 0xFFFF for w in entries))
check("a zero sector is NOT a valid map (bt_cyl 0 means cylinder 0 is bad)",
      bad != bytes(SECSIZE))
# xy.c:463 -- (((ncyl + acyl) * nhead) - 1) * nsect
check("eagle dkbad LBA is the first sector of the last physical track",
      EAGLE.dkbad_lba == (((840 + 2) * 20) - 1) * 46 == 774594)

print("tools end to end")
with tempfile.TemporaryDirectory() as tmp:
    img = os.path.join(tmp, "t.img")
    with open(img, "wb") as f:
        f.truncate(SMALL.image_bytes)

    def tool(name, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, name)] + list(args),
                              capture_output=True, text=True)

    tool("sunlabel.py", "write", img, "--profile", "small")
    r = tool("sunlabel.py", "check", img, "--profile", "small")
    check("check passes on a freshly written label", r.returncode == 0, r.stdout)
    r = tool("mkdkbad.py", img, "--profile", "small", "--verify")
    check("verify fails on a zeroed bad-sector map", r.returncode == 1)
    tool("mkdkbad.py", img, "--profile", "small")
    r = tool("mkdkbad.py", img, "--profile", "small", "--verify")
    check("verify passes once it is written", r.returncode == 0, r.stdout)

    # What format(8) might plausibly leave behind: a good label with a
    # non-zero bhead.  repair must put it back.
    with open(img, "r+b") as f:
        block = bytearray(f.read(SECSIZE))
        struct.pack_into(">H", block, 440, 2)      # dkl_bhead
        struct.pack_into(">H", block, 510, checksum(block))
        f.seek(0)
        f.write(block)
    r = tool("sunlabel.py", "check", img, "--profile", "small")
    check("check catches a non-zero dkl_bhead", r.returncode == 1)
    r = tool("sunlabel.py", "repair", img, "--profile", "small")
    check("repair fixes it", r.returncode == 0, r.stdout)
    r = tool("sunlabel.py", "check", img, "--profile", "small")
    check("check passes after repair", r.returncode == 0, r.stdout)

    # repair must refuse to touch an image of the wrong size rather than
    # quietly relabel somebody's disk.
    with open(img, "r+b") as f:
        f.truncate(SMALL.image_bytes - SECSIZE)
    r = tool("sunlabel.py", "repair", img, "--profile", "small")
    check("repair refuses an image of the wrong size", r.returncode == 1)

print()
if failures:
    print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all checks passed")
