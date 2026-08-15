#! /usr/bin/env python3
"""Write the bad-sector map the xy driver expects, and nothing else.

This step is not optional, and it is the one thing about an xy disk that a
SCSI install cannot leave behind.  xy.c:463 in Inputs/sunos-34-src reads one
sector from

    (((dkg_ncyl + dkg_acyl) * dkg_nhead) - 1) * dkg_nsect

-- the first sector of the last physical track -- and assigns it straight into
the unit's struct dkbad.  On a real drive format(8) put it there.  On our image
that read *succeeds* and returns a sector of zeros, and a zero bt_cyl is not an
empty table: it is an entry saying cylinder 0 is bad.  The driver then starts
forwarding cylinder 0, which is where the label and the boot block live.

initlabel() in the same file shows what a table of non-entries looks like: 126
entries with bt_cyl = 0xFFFF.

  mkdkbad.py IMAGE --profile eagle
  mkdkbad.py IMAGE --profile eagle --verify
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sun2disk import SECSIZE, PROFILES, build_dkbad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="eagle")
    ap.add_argument("--verify", action="store_true",
                    help="check what is there instead of writing")
    args = ap.parse_args()

    geom = PROFILES[args.profile]
    lba = geom.dkbad_lba
    want = build_dkbad()
    off = lba * SECSIZE

    size = os.path.getsize(args.image)
    if off + SECSIZE > size:
        sys.exit("%s: LBA %d is past the end of a %d-byte image"
                 % (args.image, lba, size))

    if args.verify:
        with open(args.image, "rb") as f:
            f.seek(off)
            got = f.read(SECSIZE)
        if got == want:
            print("%s: bad-sector map at LBA %d is 126 non-entries" % (args.image, lba))
            return 0
        if got == bytes(SECSIZE):
            print("%s: bad-sector map at LBA %d is ZEROS -- the driver will "
                  "read that as 'cylinder 0 is bad' and start forwarding"
                  % (args.image, lba))
        else:
            print("%s: bad-sector map at LBA %d is not what we write"
                  % (args.image, lba))
        return 1

    with open(args.image, "r+b") as f:
        f.seek(off)
        f.write(want)
    print("%s: wrote 126 non-entries at LBA %d (cyl %d, head %d, sector 0)"
          % (args.image, lba, (geom.ncyl + geom.acyl) - 1, geom.nhead - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
