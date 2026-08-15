"""Sun-2 disk geometry and label, shared by the tools in this directory.

The label is `struct dk_label` from
Inputs/sunos-34-src/sun/sys/sun/dklabel.h -- 512 bytes, big-endian, block 0:

    0    dkl_asciilabel[128]
    128  dkl_pad[296]
    424  apc, gap1, gap2, intrlv, ncyl, acyl, nhead, nsect, bhead, ppart
    444  dkl_map[8] = { dkl_cylno, dkl_nblk } as pairs of 32-bit words
    508  dkl_magic = 0xDABE
    510  dkl_cksum

This is the same layout ../Sun-2_FPGA/tools/mkxydisk writes, and the same one
SunOS format(8) writes; the point of having it here is to check and repair what
came out of the emulator, not to compete with either.

Image convention: byte K of sector N of the file is byte K of the sector as the
Sun sees it.  No byte swapping anywhere -- only the IOPB is swapped, and that
never touches the medium.
"""

import struct

SECSIZE = 512
DKL_MAGIC = 0xDABE
NDKMAP = 8

OFF_ASCII = 0
OFF_GEOM = 424
OFF_MAP = 444
OFF_MAGIC = 508
OFF_CKSUM = 510

# dkl_map slot -> partition letter
PART_LETTERS = "abcdefgh"


class Geometry:
    """A drive as both the label and the Xylogics 450 understand it."""

    def __init__(self, name, ncyl, acyl, nhead, nsect, rpm, parts, ascii_label=None):
        self.name = name
        self.ncyl = ncyl
        self.acyl = acyl
        self.nhead = nhead
        self.nsect = nsect
        self.rpm = rpm
        # parts: { letter: (start_cyl, nblk) }
        self.parts = parts
        self.ascii_label = ascii_label or (
            "%s cyl %d alt %d hd %d sec %d"
            % (name, ncyl, acyl, nhead, nsect)
        )

    @property
    def blocks_per_cyl(self):
        return self.nhead * self.nsect

    @property
    def data_blocks(self):
        return self.ncyl * self.blocks_per_cyl

    @property
    def total_blocks(self):
        """Alternate cylinders included -- they are part of the file."""
        return (self.ncyl + self.acyl) * self.blocks_per_cyl

    @property
    def image_bytes(self):
        return self.total_blocks * SECSIZE

    @property
    def dkbad_lba(self):
        """Where the xy driver looks for the bad-sector map.

        Inputs/sunos-34-src/sun/sys/sundev/xy.c:463 --
            (((dkg_ncyl + dkg_acyl) * dkg_nhead) - 1) * dkg_nsect
        i.e. the first sector of the last physical track.
        """
        return (((self.ncyl + self.acyl) * self.nhead) - 1) * self.nsect

    def check(self):
        """The bounds sun2_xy450.sv and mkxydisk impose."""
        errs = []
        if self.nhead > 256 or self.nsect > 256 or (self.ncyl + self.acyl) > 2048:
            errs.append(
                "geometry is outside what an 11-bit cylinder and 8-bit "
                "head/sector address can reach"
            )
        if self.dkbad_lba >= self.total_blocks:
            errs.append("the bad-sector map would fall past the end of the medium")
        for letter, (cyl, nblk) in sorted(self.parts.items()):
            if cyl + -(-nblk // self.blocks_per_cyl) > self.ncyl + self.acyl:
                errs.append("partition %s runs past the end of the disk" % letter)
            if nblk % self.blocks_per_cyl:
                errs.append(
                    "partition %s is %d blocks, not a whole number of cylinders"
                    % (letter, nblk)
                )
        return errs

    def describe(self):
        out = ["%s: %d+%d cyl, %d heads, %d sectors, %d rpm"
               % (self.name, self.ncyl, self.acyl, self.nhead, self.nsect, self.rpm)]
        out.append("  %d blocks/cyl, %d data blocks, %d total, %d bytes (%.1f MB)"
                   % (self.blocks_per_cyl, self.data_blocks, self.total_blocks,
                      self.image_bytes, self.image_bytes / 1e6))
        out.append("  bad-sector map at LBA %d" % self.dkbad_lba)
        for letter, (cyl, nblk) in sorted(self.parts.items()):
            out.append("  %s  cyl %4d..%-4d  %8d blk  %7.1f MB"
                       % (letter, cyl, cyl + nblk // self.blocks_per_cyl - 1,
                          nblk, nblk * SECSIZE / 1e6))
        return "\n".join(out)


# The Fujitsu M2351 Eagle is a genuine format.dat XY450 type (Inputs/sunos403/
# tape1/07. ./etc/format.dat) and is also the FPGA's power-up drive type 2:
# max_head 19 / max_sect 45 / max_cyl 841 in sun2_xy450.sv, which is the same
# drive counted from zero.
#
# / and /usr are ONE filesystem, deliberately.  SunOS 4.0.3's kernel looks for
# init in /sbin, /etc, /bin, /usr/etc and /usr/bin, and on this release the
# only one of those that has it is /usr/etc -- the distribution ships no init
# in the root at all, and /sbin in the prototype root is empty.  So /usr has to
# be there before the first process starts, which means it cannot be a
# partition that /etc/rc mounts later.  Splitting them gives
# "Can't invoke init, error 2" and a panic: icode.
#
EAGLE = Geometry(
    name="Fujitsu-M2351 Eagle",
    ncyl=840, acyl=2, nhead=20, nsect=46, rpm=3961,
    parts={
        "a": (0, 680800),     # / and /usr   cyl   0..739   348.6 MB
        "b": (740, 92000),    # swap         cyl 740..839    47.1 MB
        "c": (0, 772800),     # whole disk   cyl   0..839
    },
)

# Sized for tb/tb_sun2.sv, which instantiates blk_file with the default
# MAX_BLOCKS = 65536 -- a hard 32 MiB ceiling that $fread truncates past
# silently.  64,256 blocks fits with room to spare.
SMALL = Geometry(
    name="FPGA-XY450-small",
    ncyl=500, acyl=2, nhead=4, nsect=32, rpm=3600,
    parts={
        "a": (0, 48640),      # / and /usr   cyl   0..379    24.9 MB
        "b": (380, 15360),    # swap         cyl 380..499     7.9 MB
        "c": (0, 64000),      # whole disk   cyl   0..499
    },
)

PROFILES = {"eagle": EAGLE, "small": SMALL}


def checksum(block):
    """The label's own rule: the XOR of all 256 big-endian shorts is zero.

    chklabel() in the PROM and in the driver both do
        count = sizeof(struct dk_label) / sizeof(short);
        while (count--) sum ^= *sp++;
    so the checksum is whatever makes that come out zero.
    """
    total = 0
    for (word,) in struct.iter_unpack(">H", bytes(block[:510])):
        total ^= word
    return total


def build_label(geom, ascii_label=None):
    """A fresh 512-byte block 0 for this geometry."""
    b = bytearray(SECSIZE)
    text = (ascii_label or geom.ascii_label).encode("ascii", "replace")[:127]
    b[OFF_ASCII:OFF_ASCII + len(text)] = text

    struct.pack_into(
        ">10H", b, OFF_GEOM,
        0,             # dkl_apc, alternates per cylinder
        0,             # dkl_gap1
        0,             # dkl_gap2
        1,             # dkl_intrlv, 1:1 -- the 450's own default
        geom.ncyl,
        geom.acyl,
        geom.nhead,
        geom.nsect,
        0,             # dkl_bhead: the label is on head 0, and says so
        0,             # dkl_ppart
    )

    for i, letter in enumerate(PART_LETTERS):
        cyl, nblk = geom.parts.get(letter, (0, 0))
        struct.pack_into(">II", b, OFF_MAP + i * 8, cyl, nblk)

    struct.pack_into(">H", b, OFF_MAGIC, DKL_MAGIC)
    struct.pack_into(">H", b, OFF_CKSUM, checksum(b))
    return bytes(b)


def parse_label(block):
    """Everything block 0 says, as a dict.  No judgement passed."""
    (apc, gap1, gap2, intrlv, ncyl, acyl, nhead, nsect, bhead,
     ppart) = struct.unpack_from(">10H", block, OFF_GEOM)
    magic, cksum = struct.unpack_from(">HH", block, OFF_MAGIC)
    parts = {}
    for i, letter in enumerate(PART_LETTERS):
        cyl, nblk = struct.unpack_from(">II", block, OFF_MAP + i * 8)
        parts[letter] = (cyl, nblk)
    ascii_label = bytes(block[:128]).split(b"\0")[0].decode("ascii", "replace")
    return dict(
        ascii_label=ascii_label, apc=apc, gap1=gap1, gap2=gap2, intrlv=intrlv,
        ncyl=ncyl, acyl=acyl, nhead=nhead, nsect=nsect, bhead=bhead,
        ppart=ppart, parts=parts, magic=magic, cksum=cksum,
        cksum_ok=(checksum(block) == cksum),
    )


def build_dkbad():
    """struct dkbad with 126 non-entries, per initlabel() in xy.c.

        struct dkbad {
            long   bt_csn;          u_short bt_mbz;   u_short bt_flag;
            struct bt_bad { u_short bt_cyl; u_short bt_trksec; } bt_bad[126];
        };

    A zero-filled sector is NOT the same thing: bt_cyl == 0 reads as a real
    entry for cylinder 0, and the driver starts forwarding the label out from
    under itself.  0xFFFF is the non-entry the driver writes when it gives up.
    """
    b = bytearray(SECSIZE)
    struct.pack_into(">iHH", b, 0, 0, 0, 0)   # bt_csn, bt_mbz, bt_flag
    for i in range(126):
        struct.pack_into(">HH", b, 8 + i * 4, 0xFFFF, 0xFFFF)
    return bytes(b)
