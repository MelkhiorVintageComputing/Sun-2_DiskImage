#! /usr/bin/env python3
"""Read, check and repair the Sun disk label in block 0 of an image.

The label an image needs is not quite the label SunOS format(8) leaves behind
when it labels a SCSI disk, because the Xylogics 450's boot path reads it
differently: xyboot() walks base heads 0..3 and drive types 0..3 looking for a
label whose own idea of where it sits agrees with where it was found, so
dkl_bhead and dkl_ppart must both be zero.  --check reports every difference
from what this image ought to have; --repair writes the geometry, the partition
map and the checksum back the way the profile says.

  sunlabel.py dump    IMAGE
  sunlabel.py check   IMAGE --profile eagle
  sunlabel.py repair  IMAGE --profile eagle
  sunlabel.py write   IMAGE --profile eagle     (a fresh label, nothing else)
  sunlabel.py bootblk IMAGE [--want xy]
  sunlabel.py profile --profile eagle           (no image; just the numbers)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sun2disk import (SECSIZE, DKL_MAGIC, PART_LETTERS, PROFILES,
                      build_label, checksum, parse_label)


def read_block0(path):
    with open(path, "rb") as f:
        block = f.read(SECSIZE)
    if len(block) != SECSIZE:
        sys.exit("%s: shorter than one sector" % path)
    return block


def cmd_dump(args):
    block = read_block0(args.image)
    lab = parse_label(block)
    size = os.path.getsize(args.image)
    print("image        %s" % args.image)
    print("  size       %d bytes, %d blocks" % (size, size // SECSIZE))
    print("  ascii      %r" % lab["ascii_label"])
    print("  magic      0x%04X %s" % (lab["magic"],
                                      "" if lab["magic"] == DKL_MAGIC else "(NOT 0xDABE)"))
    print("  checksum   0x%04X %s" % (lab["cksum"],
                                      "ok" if lab["cksum_ok"] else "BAD"))
    print("  geometry   ncyl %d  acyl %d  nhead %d  nsect %d"
          % (lab["ncyl"], lab["acyl"], lab["nhead"], lab["nsect"]))
    print("  apc %d  gap1 %d  gap2 %d  intrlv %d  bhead %d  ppart %d"
          % (lab["apc"], lab["gap1"], lab["gap2"], lab["intrlv"],
             lab["bhead"], lab["ppart"]))
    bpc = lab["nhead"] * lab["nsect"]
    for letter in PART_LETTERS:
        cyl, nblk = lab["parts"][letter]
        if nblk == 0 and cyl == 0:
            continue
        end = cyl + nblk // bpc - 1 if bpc else 0
        print("  %s  cyl %4d..%-4d  %8d blk  %7.1f MB"
              % (letter, cyl, end, nblk, nblk * SECSIZE / 1e6))
    return 0


def differences(lab, geom, size):
    """Every way this image departs from what the profile says it should be."""
    bad = []
    if lab["magic"] != DKL_MAGIC:
        bad.append("magic is 0x%04X, want 0x%04X -- if the geometry looks "
                   "right this is byte order" % (lab["magic"], DKL_MAGIC))
    if not lab["cksum_ok"]:
        bad.append("checksum does not zero the sector")
    for field in ("ncyl", "acyl", "nhead", "nsect"):
        if lab[field] != getattr(geom, field):
            bad.append("%s is %d, want %d" % (field, lab[field], getattr(geom, field)))
    # xyboot() tries head 0 and drive type 0 first, and only accepts a label
    # that agrees it was found there.
    if lab["bhead"] != 0:
        bad.append("dkl_bhead is %d, must be 0 for xyboot()" % lab["bhead"])
    if lab["ppart"] != 0:
        bad.append("dkl_ppart is %d, must be 0 for xyboot()" % lab["ppart"])
    for letter, want in sorted(geom.parts.items()):
        got = lab["parts"][letter]
        if got != want:
            bad.append("partition %s is cyl %d nblk %d, want cyl %d nblk %d"
                       % (letter, got[0], got[1], want[0], want[1]))
    if size != geom.image_bytes:
        bad.append("image is %d bytes, want %d (%d blocks) -- anything the "
                   "label claims past the end returns CC_HDNF"
                   % (size, geom.image_bytes, geom.total_blocks))
    return bad


def cmd_check(args):
    geom = PROFILES[args.profile]
    lab = parse_label(read_block0(args.image))
    bad = differences(lab, geom, os.path.getsize(args.image))
    if not bad:
        print("%s: label agrees with profile %s" % (args.image, args.profile))
        return 0
    print("%s: %d problem(s) against profile %s:" % (args.image, len(bad), args.profile))
    for line in bad:
        print("  - %s" % line)
    return 1


def cmd_repair(args):
    geom = PROFILES[args.profile]
    old = read_block0(args.image)
    lab = parse_label(old)
    bad = differences(lab, geom, os.path.getsize(args.image))
    size_only = [b for b in bad if b.startswith("image is")]
    if not bad:
        print("%s: nothing to repair" % args.image)
        return 0
    if size_only:
        # We will not silently grow or truncate somebody's installed disk.
        for line in size_only:
            print("%s: refusing to repair -- %s" % (args.image, line))
        return 1
    # Keep whatever ascii label the install wrote; it is the human-readable
    # part and format(8) matches on it when the disk is re-labelled.
    new = build_label(geom, ascii_label=lab["ascii_label"] or None)
    with open(args.image, "r+b") as f:
        f.write(new)
    print("%s: repaired %d field(s):" % (args.image, len(bad)))
    for line in bad:
        print("  - %s" % line)
    return 0


def cmd_write(args):
    geom = PROFILES[args.profile]
    if not os.path.exists(args.image):
        sys.exit("%s: does not exist (create it first)" % args.image)
    with open(args.image, "r+b") as f:
        f.write(build_label(geom))
    print("%s: wrote a fresh label for %s" % (args.image, args.profile))
    return 0


def cmd_bootblk(args):
    """Blocks 1..15: what the PROM loads and jumps into.

    Three things are worth checking and all three have bitten:

    * The first instruction.  newfs installs the boot program raw, exec header
      and all, and the PROM jumps to the first byte -- straight into the header,
      where it dies at LOADADDR+20 on the a_entry field.  installboot strips the
      header, so a correctly installed block starts with real code.
    * Which driver is in there.  bootsd and bootxy are the same program built
      for different controllers, and the only way to tell from the outside is
      the SCCS string each one carries.
    * That anything is there at all.
    """
    with open(args.image, "rb") as f:
        f.seek(SECSIZE)
        blk = f.read(15 * SECSIZE)

    if blk == bytes(len(blk)):
        print("%s: blocks 1..15 are empty -- no boot block installed" % args.image)
        return 1

    first = blk[:2]
    ok = True
    # 0x4EFA is jmp d16(pc), which is how every one of these starts.  0x0001 is
    # the first half of an a.out magic, i.e. an unstripped header.
    if first == b"\x4e\xfa":
        print("%s: first instruction %02x%02x, a jmp -- header stripped"
              % (args.image, first[0], first[1]))
    else:
        print("%s: first instruction is %02x%02x, expected 4efa; if it is 0001 "
              "the a.out header was left on and the PROM will jump into it"
              % (args.image, first[0], first[1]))
        ok = False

    drivers = [(b"@(#)xy.c", "xy (Xylogics 450/451)"),
               (b"@(#)sd.c", "sd (SCSI)"),
               (b"@(#)xd.c", "xd (Xylogics 7053)")]
    found = [name for sig, name in drivers if sig in blk]
    if found:
        print("%s: driver %s" % (args.image, ", ".join(found)))
    else:
        print("%s: no recognisable driver signature" % args.image)
        ok = False
    if args.want and not any(args.want in name for name in found):
        print("%s: wanted %s" % (args.image, args.want))
        ok = False
    return 0 if ok else 1


def cmd_profile(args):
    geom = PROFILES[args.profile]
    print(geom.describe())
    errs = geom.check()
    for err in errs:
        print("  ERROR: %s" % err)
    return 1 if errs else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, func, needs_image in (("dump", cmd_dump, True),
                                    ("check", cmd_check, True),
                                    ("repair", cmd_repair, True),
                                    ("write", cmd_write, True),
                                    ("bootblk", cmd_bootblk, True),
                                    ("profile", cmd_profile, False)):
        p = sub.add_parser(name)
        if needs_image:
            p.add_argument("image")
        p.add_argument("--profile", choices=sorted(PROFILES), default="eagle")
        if name == "bootblk":
            p.add_argument("--want", default="xy",
                           help="require this driver (default xy)")
        p.set_defaults(func=func)
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
