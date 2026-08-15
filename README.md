# Sun-2 disk image

A bootable SunOS 4.0.3 disk image for a MultiBus Sun-2, laid out as an SMD
drive on a Xylogics 450 — the disk `../Sun-2_FPGA` implements and has so far
had nothing real to read.

That project's boot path already works end to end in simulation: the PROM
probes the 450, reads the label, loads blocks 1 to 15 and runs them. What it
runs is a 26-byte stub `tools/mkxydisk` synthesises, because, as its README
says, that was enough to prove the path "without anyone having to find a
genuine SunOS image first". This is where the genuine image gets made.

```sh
git submodule update --init
make tme        # build the emulator (once, a few minutes)
make idprom     # the machine's IDPROM (once)
make images     # empty, labelled disk images
make miniroot   # the 4.0.3 miniroot into the swap partition
make install    # 4.0 then the 4.0.3 upgrade; unattended, about half an hour
make verify     # boot a SCSI copy of the result, to a login prompt
make finish     # the host-side label and bad-sector-map fixups
make check      # everything checkable without a Sun
```

`Inputs/` is immutable, the same rule as in `Sun-2_FPGA`. `../Sun-2_FPGA`
itself is read-only here; nothing in this repository writes to it.

## The problem, and the shape of the answer

**No emulator emulates the Xylogics 450.** tme 0.8 and the current phabrics
fork both offer a Sun-2 exactly one mass-storage path, the MultiBus SCSI board
(`tme/bus/multibus/sun-sc`); `grep -i xylogics` across either tree returns
nothing. Neither does MAME's Sun-2, and lisper's emulator-sun-2 is SCSI too.

It does not matter, because **sd and xy address the medium identically**. Both
drivers take a partition's start block from the label as `cylno * nhead *
nsect` and run linearly from there; the xy driver converts back to cylinder,
head and sector, and the controller re-linearises with the same geometry —
`sun2_xy450.sv` computes `lba = (cyl * heads + head) * sectors + sector`. So a
SCSI disk *labelled with the target SMD geometry* already is, block for block,
the image the 450 wants.

Four things are controller-specific, and the build handles all four:

| | |
|---|---|
| the boot block | `installboot` with `/usr/mdec/bootxy`, not the `bootsd` that `newfs` installs by itself |
| `/dev` | `MAKEDEV xy0` — block major 3, char major 9 |
| `/etc/fstab` | `/dev/xy0a /` and `/dev/xy0b swap` |
| the bad-sector map | written on the host by `tools/mkdkbad.py`; see below |

## The bad-sector map is not optional

`Inputs/sunos-34-src/sun/sys/sundev/xy.c:463` reads one sector from

```
(((dkg_ncyl + dkg_acyl) * dkg_nhead) - 1) * dkg_nsect
```

— the first sector of the last physical track — and assigns it straight into
the unit's `struct dkbad`. On a real drive `format(8)` put it there. We cannot
run `format` on the target (`Sun-2_FPGA/BRINGUP.md`: "The disk cannot be
formatted from the machine"), and a SCSI install never writes one, so that read
returns a sector of zeros — and a zero `bt_cyl` is not an empty table, it is an
entry claiming cylinder 0 is bad. The driver then starts forwarding cylinder 0,
which is where the label and the boot block live.

`tools/mkdkbad.py` writes the 126 `0xFFFF` non-entries `initlabel()` in that
same file writes when it gives up. `make check` verifies it is there.

## Geometry

Two profiles, one install, in `tools/sun2disk.py`.

**eagle** — Fujitsu M2351 Eagle, a genuine `format.dat` `ctlr = XY450` type
(`Inputs/sunos403/tape1/07. ./etc/format.dat`) and also the FPGA's power-up
drive type 2 (`max_head 19 / max_sect 45 / max_cyl 841` in `sun2_xy450.sv`,
which is this drive counted from zero):

```
840+2 cyl, 20 heads, 46 sectors, 3961 rpm   ->  396.6 MB
a  cyl   0..739   680800 blk   348.6 MB   / and /usr
b  cyl 740..839    92000 blk    47.1 MB   swap (and the miniroot, during install)
c  cyl   0..839   772800 blk             whole disk
```

**small** — a custom geometry sized for `Sun-2_FPGA/tb/tb_sun2.sv`, which
instantiates `blk_file` with the default `MAX_BLOCKS = 65536`: a hard 32 MiB
ceiling that `$fread` truncates past in silence.

```
500+2 cyl, 4 heads, 32 sectors   ->  32.9 MB, 64,256 blocks
a  cyl   0..379    48640 blk    24.9 MB   / and /usr
b  cyl 380..499    15360 blk     7.9 MB   swap
```

`/` and `/usr` share a filesystem on purpose — see below. Split them and the
boot ends `Can't invoke init, error 2` / `panic: icode`.

## Which SunOS, and why two of them

`Inputs/` has two distributions, and the build uses both:

* **`sunos400/`** — SunOS 4.0 for sun2, 9 April 1988, a **full** release. Its
  TOC says `4.0` and every package is built from `/proto`. The Root File System
  package is a real root — 135 entries, with `./bin -> usr/bin` and
  `./lib -> usr/lib` already in it — and `/usr` has 1556 entries including
  `sh`, `mv`, `ln`, `ld.so`, `init` and `getty`.
* **`sunos403/`** — SunOS 4.0.3, 11 May 1989, an **upgrade**. Its TOC says
  `/rel.403.upgrade/spec/proto` and its miniroot kernel calls itself
  SUNUPGRADE. Its "root" package is thirteen files, and its `/usr` is only what
  changed — 582 entries, with **no Bourne shell among them**. It was meant to
  be unpacked over an existing 4.0, and on its own it cannot build a system
  that boots.

So: install 4.0, then lay 4.0.3 over it, which is what the upgrade set was for.
The result is a complete SunOS 4.0.3 — the last release that supports a Sun-2 —
with nothing hand-filled. Logged in on the finished eagle image:

```
SunOS Release 4.0.3 (GENERIC) #1: Mon Apr 24 14:48:42 PDT 1989
sun2# arch
sun2
sun2# ls /usr/bin | wc -l
     219
sun2# cc -o /tmp/h /tmp/h.c && /tmp/h
hello from the sun2 -- 4.0 base + 4.0.3
```

219 commands in `/usr/bin` against 142 from the upgrade tape alone, a real
Bourne shell, and a working compiler.

### The 4.0 pieces that never run

Two things about 4.0 shape the build, and both were found the hard way:

* **4.0's `tpboot` breaks the kernel it loads.** The 4.0.3 miniroot boots
  cleanly when 4.0.3's `tpboot` loads it and panics when 4.0's does — same
  disk, same kernel, same command:

  ```
  whoami: in_control 0x16 if_flags 0x49
  panic: bad SIOCGIFBRDADDR in_control
  ```

  Whatever 4.0's `tpboot` leaves in the boot parameters sends the kernel off to
  ask the network who it is; `0x49` is `UP|LOOPBACK|RUNNING`, so with only
  `lo0` to ask, it asks `lo0`. So the machine boots from the 4.0.3 tape and
  swaps to the 4.0 tape once there is a shell.

* **A 4.0 kernel would want a network anyway.** Fit a 3C400 with nothing
  behind it (`tools/run-sun2 --ether`) and the panic becomes

  ```
  revarp: Requesting Internet address for 8:0:20:0:2f:a
  ```

  retried for ever. It never comes up here, so the finished disk carries the
  **4.0.3** kernel, which is the one verified to boot with no network at all.

### What still has to be told

Both releases ship the same two defaults that are wrong for this machine, and
the install fixes both:

* `gettytab`'s `std.9600` has no `p8`, so the console comes up 7 bits with even
  parity and the login prompt arrives as `363 365 356 262 240 l o 347 i 356`.
  The capability is `p8`, not the `np` that BSD `gettytab(5)` documents.
* `rc.local` starts `ypbind` and then asks YP for a netmask, which never
  returns without a server. `ypbind` is moved aside.

And `/usr` lives on the root filesystem: neither release ships an `init` in the
root, so `/usr` has to exist before the first process does.

## What is here

| path | what |
|---|---|
| `Makefile` | the whole build |
| `tools/sun2disk.py` | geometry profiles, `struct dk_label`, `struct dkbad` |
| `tools/sunlabel.py` | dump / check / repair / write block 0 |
| `tools/mkdkbad.py` | the bad-sector map, and `--verify` for it |
| `tools/putminiroot.py` | a distribution miniroot into a partition, from the host |
| `tools/run-sun2` | run the machine: pty console, logging, scripting, a control fifo |
| `tools/SUN2-MULTIBUS.in` | the tme machine, headless, console on ttya |
| `tools/scripts/*.txt` | the answers, as `PATTERN<TAB>REPLY` |
| `tools/selftest.py` | the label and bad-sector checks that need no Sun |
| `doc/INSTALL.md` | why each answer is what it is |

## Installing on the target

```sh
dd if=build/eagle.img of=/dev/sdX bs=1M conv=fsync
```

Raw, at LBA 0, no partition table and no filesystem: on the FPGA the whole card
is the disk (`Inputs/Wish5380/doc/block.md` — "No offset and no extent. LBA 0
is media block 0"). For the simulator, use `build/small.img`:

```sh
make -C sim xsim XY450=1 MEM_MIB=4 ROM=fast \
     XSIMARGS="-testplusarg blk_image=/path/to/small.img"
```

Failure decode, from that project's `BRINGUP.md`: `xy: error 5 cmd 2` is
`CC_HDNF`, the image smaller than the label claims; `No label found` is byte
order, since a label read with the sector bytes swapped still passes the
checksum and fails only on the magic; `Waiting for disk to spin up...` is media
not ready.
