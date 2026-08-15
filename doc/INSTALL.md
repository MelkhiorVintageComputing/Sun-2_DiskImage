# Installing SunOS on the emulated Sun 2/120

This is the prose half of the build. The executable half is
`tools/scripts/install.txt`, which replays exactly the answers described here;
if the two ever disagree, the script is what runs.

Everything happens under `tools/run-sun2`, which gives the machine a pty of its
own and logs it. Type `~.` to quit, `~b` for a BREAK, `~c CMD` to hand a
command to tmesh; or drive a running session from another shell with
`echo 'ls -l /' > build/console-<image>.in`.

## The machine

`tools/SUN2-MULTIBUS.in` is tme's own `machine/sun2/SUN2-MULTIBUS` with the
video board, keyboard, mouse and GTK display removed and the console on ttya.
The rev-R PROM comes up as:

```
Self Test completed successfully.

Sun Workstation, Model Sun-2/120 or Sun-2/170, Sun-2 keyboard
ROM Rev R, 4MB memory installed
Serial #39253, Ethernet address 8:0:20:0:2F:A

Probing Multibus: sd
Using RS232 A input.
```

`Probing Multibus: sd` is the whole problem in three words. On the FPGA that
line says `xy`. No version of tme emulates a Xylogics 450, so the install runs
on the SCSI board and the image is made xy's along the way.

## Two releases

| | `sunos400/` | `sunos403/` |
|---|---|---|
| TOC says | `4.0`, Sat Apr 9 1988 | `4.0.3`, Thu May 11 1989 |
| built from | `/proto` | `/rel.403.upgrade/spec/proto` |
| miniroot kernel | `SunOS Release 4.0 (GENERIC) #3` | `SunOS Release 4.0.3 (SUNUPGRADE) #1` |
| root package | a real root, 135 entries, with `bin -> usr/bin` | 13 files |
| `/usr` package | 1556 entries, `sh` `mv` `ln` `ld.so` `init` `getty` | 582 entries, **no `sh`** |
| layout | `/usr/boot`, `/usr/mdec`, `/usr/stand` | all three under `/usr/kvm` |

4.0 is a full release; 4.0.3 is an upgrade meant to be unpacked over one. So
the build installs 4.0 and lays 4.0.3 over it, and the result is a complete
SunOS 4.0.3 — the last release that supports a Sun-2.

Tape files, 0-based, from each tape's own XDR table of contents. The first six
packages are the same in both; they diverge after:

| file | 4.0 | 4.0.3 |
|---|---|---|
| 0–5 | `tpboot`, XDRTOC, `copy`, miniroot, `munix`, `munixfs` | same |
| 6 | Root File System | Root File System (13 files) |
| 7 | `/usr` | `/usr` |
| 8 | Sys | `/usr/kvm` |
| 9 | Networking | install tools |
| 10 | Debugging | copyright |
| 11 | SunView_Users | |
| 12 | copyright | |

## Getting to a shell

The documented path is `b st()` → `tpboot` → `st(0,0,4)` (MUNIX) → answer
`st0` and tape file `5` to the ram-disk prompt. That works, and it is worth
knowing it works, but MUNIX's ram-disk root has `dd`, `mt`, `tar` and almost
nothing else: its whole job is to copy the miniroot onto the swap partition.

We skip it. `tools/putminiroot.py` writes the miniroot into partition b from
the host, and then:

```
> b st()
Boot: st(0,0,0)
Boot: sd(0,0,1)vmunix -s
```

The first `Boot:` is the PROM's. The second is `tpboot`'s — tape file 0 is a
raw image, which is all the PROM can load, and `tpboot` is the thing that
understands a.out. It prompts (`sunstand/boot.c`, `RB_ASKNAME`) and re-prompts
on empty input, so it needs a real answer.

**The PROM cannot boot partition b itself.** It boots a partition by reading
blocks 1..15 of it, and the miniroot as shipped has filesystem in those blocks,
not a boot block. `tpboot` can, because it is a standalone boot with the whole
saio filesystem layer behind it: give it a device *and a path* and it will find
the file. The kernel then takes its root from the device it was booted from, so
root lands on sd0b where the miniroot is.

That gives a single-user shell with `newfs`, `mkfs`, `fsck`, `mount`, `tar`,
`mt`, `format`, and — the important ones — `bootxy` and `installboot`.

```
sd0:  <Fujitsu-M2351 Eagle cyl 840 alt 2 hd 20 sec 46>
```

That line is the point of the geometry exercise: SunOS has read our label and
agrees it is looking at an Eagle. The `zsprobe on N failed` lines that follow
are the kernel finding only one serial chip, and are harmless.

### It has to be the 4.0.3 miniroot, loaded by the 4.0.3 tpboot

Both halves of that matter, and each was found by hitting it.

**The loader.** The *same* 4.0.3 miniroot, on the same disk, booted with the
same `sd(0,0,1)vmunix -s`, comes up cleanly when 4.0.3's `tpboot` loads it and
panics when 4.0's does:

```
whoami: in_control 0x16 if_flags 0x49
panic: bad SIOCGIFBRDADDR in_control
```

Whatever 4.0's `tpboot` leaves in the boot parameters sends the kernel off to
identify itself over the network before it mounts a root. `0x49` is
`UP|LOOPBACK|RUNNING` — with only `lo0` to ask for a broadcast address, it asks
`lo0`, and asking a loopback for a broadcast address panics this kernel. So the
machine powers up with the 4.0.3 tape loaded and swaps to the 4.0 tape (`~t
400-1`) once there is a shell; by then `tpboot` is out of the picture and the
tape is only a `tar` source.

**The kernel.** A 4.0 kernel goes down the same road even when nothing is wrong
with the loader. Fit a 3C400 with no host backend (`tools/run-sun2 --ether`,
which works because `3c400.c` calls its ethernet connection only when there is
one) and the panic turns into

```
revarp: Requesting Internet address for 8:0:20:0:2f:a
```

retried for ever, because nothing can answer. So no 4.0 kernel is ever run or
installed: the miniroot is 4.0.3's, and the kernel that ends up on the disk is
4.0.3's — which was verified to boot through `tpboot` with no network at all,
going straight to `root on sd0a`.

## Three things about the miniroot that shape every command

1. **Its root filesystem is read-only.** `mount` fails trying to append to
   `/etc/mtab` — but the mount itself still happens, so ignore the error and
   check with `ls`. `umount` fails outright and does nothing; `sync` before
   shutting down and let the next boot's `fsck` tidy up.
2. **No here-documents.** The shell wants to write the here-doc body to `/tmp`,
   which is read-only, and you get `/tmp/sh40: Read-only file system`. Build
   files with `echo` and `>>`, the way `/etc/install/script/create_root` does.
3. **Type after the prompt, not before.** A program that has just opened
   `/dev/console` flushes what is queued on it, so anything sent while the
   kernel is still printing is thrown away. `tools/run-sun2` waits a second
   after each pattern match for the same reason, and the script's cues are
   prompts and markers rather than kernel messages.

## Why / and /usr are one filesystem

The kernel looks for `init` in `/sbin`, `/etc`, `/bin`, `/usr/etc` and
`/usr/bin` — the string table in `vmunix` lists exactly those. Neither release
ships an `init` in the root; both have it at `/usr/etc/init`. So `/usr` has to
be present before the first process starts, which rules out mounting it from
`/etc/rc`. Split them and the boot ends:

```
root on sd0a fstype 4.2
Can't invoke init, error 2
panic: icode
```

So partition `a` holds both, and `/etc/fstab` names only `/` and swap.

## Laying 4.0.3 over 4.0

The upgrade is three `tar`s — root, `/usr`, `/usr/kvm` — unpacked over the 4.0
tree. Everything the 4.0.3 packages do not mention stays as 4.0 left it, which
is the whole point. Two things need saying afterwards:

* **The layout moved.** 4.0 keeps the kernel, the boot blocks and the
  standalone programs in `/usr/boot`, `/usr/mdec` and `/usr/stand`; 4.0.3 puts
  all three under `/usr/kvm`. The 4.0 copies are left behind by the overlay —
  a stale kernel and a stale `bootxy` for anyone reading the disk later — so
  the install removes them.
* **`ld.so` moved with it.** `crt0` opens `/usr/lib/ld.so` by absolute path
  (the string is right there: `crt0: no /usr/lib/ld.so`). 4.0 shipped a real
  file there; 4.0.3 ships its `ld.so` as `/usr/kvm/ld.so` and expects the
  symlink, which is why its `/usr` package has no `./lib/ld.so` at all. The
  install makes `/usr/lib/ld.so -> ../kvm/ld.so`.

`libc` needs no such care: `libc.so.0.10` and `libc.so.0.12` sit side by side
after the overlay, and ld.so binds a request for either to the highest minor it
finds.

## The boot chain, and the two traps in it

```
PROM  --blocks 1..15 of partition a-->  bootxy
bootxy  --block list patched in-------> /boot
/boot   --by name---------------------> /vmunix
```

**`newfs` installs a boot block, and it is the wrong one, installed wrongly.**
`newfs -v` prints `installing boot code / 1st level boot = /usr/mdec/bootsd`;
it picks the name from the device (`rsd0a` → `bootsd`) and copies the file raw.
Raw is fatal: `bootsd` is an a.out, and the PROM jumps to the first byte of
what it loaded, so it executes the 32-byte exec header. The header is not
harmless code — you get

```
Timeout Bus Error, addr: FFFFFFFF at 004014
```

which is `LOADADDR` (0x4000, `sys/mon/sasun.h`) plus 20, exactly the offset of
`a_entry`. The real `installboot` strips the header; after it runs, block 1
starts `4e fa 01 0a` — a `bra.w`, a real first instruction.

**`installboot` needs the filesystem synced first.** It asks the filesystem
where `/boot`'s blocks are and patches the list into the boot block, and a
block that has not reached the disk yet comes back as zero. `/boot` is 120,936
bytes = fifteen 8 KB blocks, twelve direct and three through the indirect
block; without a `sync` the three indirect ones are recorded as block 0:

```
Block locations:
startblk size
450        10
...
5b0        10
3c80       10      <-- these three are 00 00 00 10 without the sync
3cb0       10
3ce0       10
Boot size: 0x1d868
Boot checksum: 0xc1488b4b
```

and the symptom is one line at boot before it dies in whatever it jumped into:

```
checksum 8F16191 != C1488B4B, trying to boot anyway
```

The proto is taken from the target's own `/usr/kvm/mdec/bootxy` rather than the
miniroot's, so blocks 1..15 hold the 4.0.3 `bootxy` that goes with the 4.0.3
kernel it will be loading.

The kernel must be `/usr/kvm/boot/vmunix`, the GENERIC one. `vmunix_small` is
tempting on a 4 MB machine and is **not usable here**: it has no `xyc`/`xy`
driver at all, while GENERIC has both (`_xycdriver`, `_xycinfo`,
`xy%d at xyc%d slave %d`).

## The third trap: ypbind

`/etc/rc.local` starts YP unconditionally — every YP action in it is guarded by
`[ -f /usr/etc/<daemon> ]` and nothing else — and then does

```sh
ifconfig ie0 `hostname` netmask +
```

where `netmask +` asks YP for the answer. With `ypbind` running and no server
to bind to, that never returns, and the boot stops dead at

```
starting rpc and net services: portmap ypbind keyserv
```

with no login prompt, ever. suninstall's `create_root` comments the `ypbind`
lines out of `rc.local` when the machine is not a YP client. Moving the binary
aside — `mv /usr/etc/ypbind /usr/etc/ypbind.off` — does the same thing through
the guard the release already wrote, without editing a shipped script.

## The fourth trap: the console is 7 bits

Left alone, `getty` runs the console at 7 bits with even parity, and the login
prompt arrives as

```
363 365 356 262 240 l o 347 i 356 : 240
```

which is `sun2 login: ` with the parity bit set on every character that needs
one — `l`, `o`, `i` and `:` already have an even number of bits, so they come
through clean, and that is the giveaway. A terminal set to 7E1 would render it
correctly and be wrong for everything else on the wire; the FPGA's SCC, and
every serial program anyone will actually attach, are 8N1.

The capability is **`p8`**, not the `np` that BSD `gettytab(5)` documents.
SunOS's `getty` has its own table, and the strings in `/usr/etc/getty` list it:

```
... ep op ap ec co cb ck ce pe rw xc lc uc ig ps hc ub ab dx p8 ...
```

with no `np` anywhere. `np` is read as an unknown capability and silently
ignored, which looks exactly like success until the prompt comes back with
parity on it. The `std.9600` entry the console uses has neither, so the install
adds `p8`:

```sh
sed -e "/std.9600/{n;s/:sp#9600:/:p8:sp#9600:/;}" /a/etc/gettytab > ...
```

The `n` is there to edit the line *after* the entry name, because the
capability line begins with a tab and a tab is an awkward thing to send down a
console. `make verify` stops on a literal `login:`, so it also fails if this
regresses.

Sun's default is not a mistake on Sun's part: on a Sun-2 with a frame buffer
`/dev/console` is the screen and parity never arises, and 7E1 was a reasonable
guess for a terminal on a serial port in 1988. It is wrong for this machine,
where the console *is* the serial port.

## Space, and why the small profile trims early

The eagle image has 348.6 MB and needs about 28 MB, so it takes everything:
both releases in full, plus 4.0's Sys, Networking, Debugging and SunView_Users.

The small image has 24.9 MB, and 4.0's `/usr` alone is 18.9 MB. Trimming after
the overlay -- which is where the trim sat when the profile was 4.0.3-only --
means the filesystem fills in the middle of it:

```
/a: file system full
tar: boot/vmunix_small: HELP - extract write error: No space left on device
```

and the install runs on to its end regardless, echoing its completion marker
with no `/boot` written and `installboot` reporting
`bootfile open: No such file or directory`. So `tools/scripts/install-small.txt`
trims between the base and the overlay instead: 4.0's static libraries (2.5 MB
of `/usr/lib`), its headers, its SCCS and pre-4.0 trees, and its
`/usr/{boot,mdec,stand}`, which 4.0.3 supersedes anyway. It also skips the four
optional 4.0 packages entirely rather than unpacking 8 MB to delete it again.
That leaves 13.9 MB before the overlay and 18.7 MB after, with a second small
trim for what 4.0.3 brings that the profile has no room for.

The completion marker is not evidence of anything on its own, which is why
`make install` now runs `installed-ok`: it greps the log for write failures and
then asks `sunlabel.py bootblk` whether blocks 1..15 hold a stripped xy boot
block. On the failed build that check said `first instruction is 0001` -- the
raw a.out header `newfs` had left there.

## The steps

`tools/scripts/install.txt`, in order, each waiting on the previous one's
marker:

| step | what |
|---|---|
| `newfs -v /dev/rsd0a` | 680,800 sectors in 740 cylinders of 20 tracks, 46 sectors |
| `mount /dev/sd0a /a` | ignore the `/etc/mtab` error |
| `~t 400-1` | swap to the 4.0 tape, now that tpboot has done its work |
| 4.0 tape 6 → `/a` | the root filesystem, `bin`/`lib` symlinks and all |
| 4.0 tape 7 → `/a/usr` | `/usr`, after `mkdir` — the root package has no `./usr` |
| 4.0 tapes 8–11 | Sys, Networking, Debugging, SunView_Users |
| `~t 403-1` | swap to the 4.0.3 tape |
| 4.0.3 tapes 6, 7, 8 | root, `/usr`, `/usr/kvm` over the top — the upgrade |
| merge | drop 4.0's `/usr/{boot,mdec,stand}`; `/usr/lib/ld.so -> ../kvm/ld.so` |
| `vmunix`, `boot` | 4.0.3 GENERIC kernel, and `kvm/stand/boot.sun2` as `/boot` |
| `MAKEDEV std pty0 xy0 sd0 st0` | `xy0` is blk 3 / chr 9 |
| `/etc/fstab` | `/dev/xy0a /` and `/dev/xy0b swap` |
| `ypbind` aside, hostname | a standalone machine, called `sun2` |
| `gettytab` `p8` | an 8-bit console |
| `sync; sync; sync` | see above — not optional |
| `installboot -vl /a/boot /a/usr/kvm/mdec/bootxy /dev/rsd0a` | the xy boot block |

After that the image is an xy disk in every respect except that it was written
through a SCSI controller, which the medium cannot tell. `make finish` does the
last two things on the host: check and repair the label, and write the
bad-sector map that `format` would have written and no install ever does.

## Verifying it under tme

The finished image cannot be booted here: its boot block is `bootxy`, which
carries its own Xylogics driver and goes looking for a controller at 0xEE40
that no emulator has. What it does instead is the right answer, and the best
evidence tme can give that the boot block is real and correctly installed:

```
Boot: sd(0,0,0)vmunix
Timeout Bus Error, addr: 00100644 at 240E66
```

To exercise the rest, `make verify` copies the image, swaps the boot block and
fstab for their sd equivalents (`tools/scripts/to-sd.txt`), and boots that.
Nothing else differs, so a login prompt there means the image is sound
everywhere except the four bytes of device name. `tools/scripts/to-xy.txt` is
the inverse, if you want the copy back.
