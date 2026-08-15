#! /usr/bin/env python3
"""Put the distribution miniroot into a partition of a disk image.

On real hardware this is done from MUNIX, whose ram-disk root holds dd and mt
and little else, precisely so it can copy tape file 3 onto the swap partition
before rebooting into it.  We are already on a host with the tape files as
ordinary files and the disk as an ordinary file, so we do it here: the result
is the same blocks in the same place, and it is a Makefile rule instead of a
transcript.

The miniroot goes in partition b -- swap -- because that is the one partition
the install is not about to newfs out from under itself.

  putminiroot.py IMAGE --profile eagle [--part b]

Note the miniroot carries no Sun label and no boot block of its own: block 0 is
filesystem, not a label.  So the PROM cannot boot this partition directly.
tpboot can, because it reads filesystems -- see doc/INSTALL.md.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sun2disk import SECSIZE, PART_LETTERS, PROFILES

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tape file 3 either way -- the first six files are the same packages in the
# same order in both releases.  Only the names on disk differ: the 4.0.3 dump
# has a trailing dot and the 4.0 dump does not.
MINIROOTS = {
    "400": os.path.join(TOP, "Inputs", "sunos400", "tape1", "04"),
    "403": os.path.join(TOP, "Inputs", "sunos403", "tape1", "04."),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="eagle")
    ap.add_argument("--part", default="b", help="partition letter (default b, swap)")
    ap.add_argument("--release", choices=sorted(MINIROOTS), default="400",
                    help="which distribution's miniroot (default 400)")
    ap.add_argument("--miniroot", help="an explicit path, overriding --release")
    args = ap.parse_args()
    if not args.miniroot:
        args.miniroot = MINIROOTS[args.release]

    geom = PROFILES[args.profile]
    if args.part not in geom.parts:
        sys.exit("profile %s has no partition %s" % (args.profile, args.part))
    start_cyl, nblk = geom.parts[args.part]
    start = start_cyl * geom.blocks_per_cyl

    size = os.path.getsize(args.miniroot)
    need = -(-size // SECSIZE)
    if need > nblk:
        sys.exit("miniroot is %d blocks; partition %s holds %d"
                 % (need, args.part, nblk))

    with open(args.miniroot, "rb") as src, open(args.image, "r+b") as dst:
        dst.seek(start * SECSIZE)
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())

    print("%s: miniroot -> partition %s, %d blocks at LBA %d (cyl %d), %d spare"
          % (args.image, args.part, need, start, start_cyl, nblk - need))
    # sd(c,u,p): p is the index into dkl_map, so a=0, b=1, ... not the index
    # among the partitions that happen to be defined.
    print("boot it from tpboot with:  sd(0,0,%d)vmunix -s"
          % PART_LETTERS.index(args.part))
    return 0


if __name__ == "__main__":
    sys.exit(main())
