# Netbooting a Sun-2, from the machine's point of view

Three programs run on the client, one after another, each fetched over the
network by the one before it. They are in this directory, and nothing else here
is needed on the client — a netbooting Sun-2 has no local disk in the story at
all.

| | what runs | how it arrived | size |
|---|---|---|---|
| 1 | the boot PROM | it is the machine | — |
| 2 | `sun2.bb` | **ND**, from `ndbootd` | 5,976 |
| 3 | `boot.sun2` | **TFTP**, as `<HEXIP>.SUN2` | 120,936 |
| 4 | `vmunix` | **NFS**, from the client's root | 822,486 |

All three are SunOS 4.0.3 for sun2, taken from tape 1 file 8 of
`Inputs/sunos403/` (`/usr/kvm/stand/sun2.bb`, `/usr/kvm/stand/boot.sun2`,
`/usr/kvm/boot/vmunix`). `make -C .. netboot` re-extracts them; the checksums
are at the bottom.

## 1. The PROM: an ND request, and nothing else

`b ie()` or `b ec()` — and note what the PROM's own boot table calls those
devices:

```
"ie",  ieprobe, xxboot, ieopen, ieclose, ndstrategy,  "ie: Sun/Intel network disk",
"ec",  ecprobe, xxboot, ecopen, NONE,    ndstrategy,  "ec: 3Com network disk",
```

A Sun-2 does not RARP and it does not speak TFTP. It has one network boot
protocol, **ND** — Sun's network *disk* — and it uses it exactly the way it
uses a local disk: `xxboot` is the same generic block-device boot as `sd` and
`xy` use, with `ndstrategy` underneath instead of a controller. The machine
believes it is reading blocks 1 to 15 of a disk that happens to be somewhere
else.

ND is IP protocol 77 (`in.h`: `IPPROTO_ND 77 /* UNOFFICIAL net disk proto */`),
a 32-byte header — `op`, `min`, `error`, `ver`, `seq`, `blkno`, `bcount`,
`resid`, `caddr`, `ccount` — and then data. The request goes out to the
Ethernet broadcast address carrying the machine's own Ethernet address, because
at this point the machine has no IP address and no way to learn one. Whatever
answers has to do the Ethernet-address-to-client mapping itself; that is why
`ndbootd(8c)` wants the client in `ethers(5)` and `hosts(5)`.

What comes back is `sun2.bb`, which the PROM loads at `0x4000` and jumps to,
exactly as it would a boot block off a local disk. There is no `bootnd` and
none is needed: `/usr/mdec` on the 4.0.3 tape has `bootsd`, `bootxy`,
`installboot` and `rawboot`, and that is all.

The rev-R PROM in `Inputs/sun2-multi-rev-R.bin` has both drivers; `strings` on
it gives `ie: Sun/Intel network disk` and `ec: 3Com network disk`. Its failure
messages are `ie: cannot initialize` and `ie: Ethernet cable problem`.

## 2. `sun2.bb`: RARP, then TFTP

5,976 bytes, raw m68k starting `4e fa 01 0a` — a `bra.w`, no a.out header,
because the PROM jumps to the first byte of what it loaded. It fits the 7,680
bytes of blocks 1 to 15 with room to spare.

ND has now done its entire job. `sun2.bb` never uses it again; boot(8S) puts it
as "a Sun-2 system boots from its server using one extra step … This server
sends back a standalone program that carries out the same TFTP request sequence
as is done for all the other systems."

What it does, in its own words — every string below is in the binary:

```
ERROR: missing or invalid ID prom
Requesting Internet address for
Internet address is
Using IP Address
Booting from tftp server at
Downloaded %d bytes from tftp server.
tftp: timeout
```

* reads its Ethernet address out of the IDPROM, and says so if the IDPROM is
  unreadable — on the FPGA that is the IDPROM contents, not the network;
* broadcasts **RARP** and waits to be told its own IP address;
* **TFTP**s one file from whoever answered, and the name it asks for is its own
  IP in uppercase hex with an architecture suffix. The template is in the
  binary as `01234567.SUN2`, and boot(8S) gives the rule: `ip-address.arch`,
  uppercase, the whole name limited to 14 characters, `SUN2` for a Sun-2. So
  192.9.1.17 asks for `C0090111.SUN2`.

Only Sun-3 may leave the suffix off. If the server has `C0090111` and not
`C0090111.SUN2`, a Sun-3 boots and this machine sits in `tftp: timeout`.

## 3. `boot.sun2`: bootparams, then NFS

120,936 bytes, also raw and also entered at its first byte. This is the same
`/boot` a disk-booted machine runs; nothing about it is network-specific except
which of its drivers get used.

It starts over rather than inheriting anything: another **RARP** for its IP
(`Requesting Internet address for`), then two broadcast **bootparams** calls —

* `whoami`, which returns the client's hostname, and its domain name if it has
  one: `Boot: hostname '%s'`, `Boot: domainname '%s'`;
* `getfile` for `root`, which returns a server and a pathname.

Then it **NFS-mounts** that root and reads a file out of it by name. The name
came from the PROM's boot line, and defaults to `vmunix`.

Its complaints are specific, which makes them worth knowing:

```
No bootparam server
Boot: bad dialog with bootparam server (error 0x%x)
Boot: null host name returned by bootparam server
Boot: NFS mount of '%s:%s' failed (error 0x%x)
Boot: bad routing request (error %d)
```

The last one is the case where the server is not on the client's subnet:
`getfile` can return a gateway, and `boot.sun2` installs the route itself.

On success it prints the name it is loading and the sizes as they come in —
`Boot: vmunix`, then `Size: %d` — which is the same pair a disk boot prints.

## 4. `vmunix`: SunOS 4.0.3 GENERIC

822,486 bytes, a.out `0x00010107` (mc68010, OMAGIC), text 604,688 + data
111,664 + bss 171,288, entry `0x4000`.

```
SunOS Release 4.0.3 (GENERIC) #1: Mon Apr 24 14:48:42 PDT 1989
```

GENERIC has the drivers this needs — `ie` and `ec` are both in it (`reset ie%d`,
`reset ec%d`, `ec%d: ethernet jammed`) along with NFS. It has **no `nd` driver
at all**, which is the clearest statement of how narrow ND's role is: the PROM
speaks it for 15 blocks and the running system never speaks it again. Root is
NFS from here on.

`vmunix_small` is on the tape beside it and is narrower rather than merely
smaller: no `xy`, and `ie` but no `ec`. It would netboot a machine with a Sun
Ethernet card and could not then be moved to a local Xylogics disk, nor to a
3Com card.

The kernel then does the whole RARP-and-bootparams round **again** for itself —
`boot.sun2` mounted root only so it could read a file, and hands nothing on.
The strings are in the kernel:

```
revarp: Requesting Internet address for %s
whoami: in_control 0x%x if_flags 0x%x
No bootparam server
```

That second string is worth recognising, because it is also how this machinery
announces itself when it fires by mistake. Installing to a *local* disk in this
repository, a 4.0 kernel loaded by 4.0's `tpboot` went looking for a bootparams
server it had no reason to want, found only the loopback interface to ask for a
broadcast address, and died:

```
whoami: in_control 0x16 if_flags 0x49
panic: bad SIOCGIFBRDADDR in_control
```

`0x49` is `UP|LOOPBACK|RUNNING`. It is the same code path as step 4 here; the
difference is only that netbooting means it, and a disk boot does not. See
`../doc/INSTALL.md`.

Having identified itself, the kernel mounts root over NFS, runs
`/usr/etc/init` out of it, and comes up.

## The whole thing in one view

```
   PROM ──ND (IP proto 77, broadcast, ethernet addr)──▶  ndbootd
        ◀──────────────── sun2.bb, as "blocks 1..15" ────────

sun2.bb ──RARP (broadcast)──────────────────────────▶  rarpd
        ◀──────────────────────────── my IP address ────────
        ──TFTP  C0090111.SUN2 ───────────────────────▶  in.tftpd
        ◀──────────────────────────────── boot.sun2 ────────

boot.sun2 ─RARP, then bootparams whoami + getfile ──▶  rpc.bootparamd
          ◀──────── hostname, domain, server:/root ────────
          ──NFS mount, read /vmunix ────────────────▶  nfsd, rpc.mountd
          ◀──────────────────────────────── vmunix ────────

  vmunix ──bootparams + NFS again, then /usr/etc/init ▶  ... multiuser
```

Four network protocols, three of them standard, and each program throws away
what the one before it learned.

## Where these go on the server

The names are the server's business, not the client's, but for reference:

| file here | server side |
|---|---|
| `sun2.bb` | `/tftpboot/sun2.bb` — what `ndbootd` serves |
| `boot.sun2` | `/tftpboot/<HEXIP>.SUN2`, a copy or symlink per client |
| `vmunix` | the client's NFS root, as `/vmunix` |

## Provenance

```
sha256  adaa4ba0935bc5428d64dfc47d9794ca67958cf0cecd01b4fdb836ed6b42fd6f  sun2.bb
sha256  76792c54cd87b2ab6469da3d28255a6480e2fc68dbeabce11681317f7695109d  boot.sun2
sha256  2449b569cbbb14159c01ddf12e967689903dd9e8752745504cf172db6e22aaaa  vmunix
```

All three are `tar xOf Inputs/sunos403/tape1/09.` of `stand/sun2.bb`,
`stand/boot.sun2` and `boot/vmunix`, byte for byte. `make -C .. netboot`
reproduces them and re-checks the hashes.
