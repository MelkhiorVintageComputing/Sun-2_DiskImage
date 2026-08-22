#! /usr/bin/env python3
"""Turn a captured tree into a netbootable root archive.

`make netboot-root` tars the installed tree onto a blank disk from inside the
emulator, using SunOS's own tar so that ownership, modes, setuid bits, symlinks
and hard links are exactly what SunOS itself would write.  What that tar cannot
write is device nodes: Inputs/sunos-34-src/bin/tar.c switches on S_IFMT and
handles S_IFDIR, S_IFLNK and regular files, and everything else falls to

    default: fprintf(stderr, "tar: %s is not a file. Not dumped\\n", longname);

so /dev arrives as an empty directory and nothing says so afterwards.  The
capture works around that by writing `ls -l /dev' into the tree first, and this
turns those lines back into real CHRTYPE/BLKTYPE members.

  mkroottar.py CAPTURE.img --out root.tar.gz [--dev-table dev.table]
  mkroottar.py CAPTURE.img --list            (what is in the capture, no output)
  mkroottar.py --verify root.tar.gz --dev-table dev.table
"""

import argparse
import gzip
import io
import os
import re
import sys
import tarfile

# Written by setup_client into a diskless client's /sbin, from /usr/kvm/boot:
# "cp init sh mount ifconfig hostname ${ROOTPATH}/${NAME}/sbin".  The kernel
# searches /sbin before /etc, /bin, /usr/etc and /usr/bin, so this is what lets
# a client start before anything is mounted over NFS.  A combined export has
# /usr/etc/init anyway; these cost 250 KB and make the tree work either way.
SBIN_BOOTSTRAP = ["init", "sh", "mount", "ifconfig", "hostname"]
KVM_BOOT = "./usr/kvm/boot/"

# Files the capture makes for its own purposes, which have no business in a root.
CAPTURE_ARTEFACTS = ("./dev.table", "./tar.errors")

# `ls -l' as SunOS writes it for a device:
#   crw-r-----  1 root      17,   0 May 17 17:51 rsd0a
LS_DEV = re.compile(r"""^([bc])           # block or character
                        ([rwxsStT-]{9})   # the mode
                        \s+\d+            # link count
                        \s+(\S+)          # owner
                        (?:\s+(\S+))??    # group, when ls prints one
                        \s+(\d+),\s*(\d+) # major, minor
                        \s+\S+\s+\S+\s+\S+  # date
                        \s+(\S+)$         # name
                     """, re.VERBOSE)

MODE_BITS = {"r": 0o4, "w": 0o2, "x": 0o1}


def parse_mode(field):
    """The nine rwx characters, plus the setuid/setgid/sticky they overload."""
    mode = 0
    for i, ch in enumerate(field):
        who = 2 - i // 3
        if ch in MODE_BITS:
            mode |= MODE_BITS[ch] << (3 * who)
        elif ch in "sS":            # setuid on user, setgid on group
            mode |= (0o4000 if who == 2 else 0o2000)
            if ch == "s":
                mode |= 1 << (3 * who)
        elif ch in "tT":            # sticky
            mode |= 0o1000
            if ch == "t":
                mode |= 1 << (3 * who)
    return mode


def read_dev_table(text):
    """Every device node ls -l described, as (name, isblk, mode, major, minor)."""
    out, skipped = [], []
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("total"):
            continue
        m = LS_DEV.match(line)
        if m:
            kind, modestr, _owner, _group, major, minor, name = m.groups()
            out.append((name, kind == "b", parse_mode(modestr),
                        int(major), int(minor)))
        elif line[0] in "-dl":
            pass                    # a plain file in /dev; the tar has it
        else:
            skipped.append(line)
    return out, skipped


def open_capture(path):
    """The archive starts at block 0 of the disk; tar stops at its own end."""
    return tarfile.open(path, "r|")


def verify(archive, table_path):
    """Is the finished archive a root, with every node the table names?

    Checked without root, because the interesting failure -- device nodes that
    came out as empty regular files -- is visible in the archive itself, and
    nobody should need a privileged extraction to find out.
    """
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
    byname = {m.name: m for m in members}
    devs = [m for m in members if m.ischr() or m.isblk()]
    print("%s: %d members, %d device nodes, %d symlinks, %d setuid"
          % (archive, len(members), len(devs),
             sum(1 for m in members if m.issym()),
             sum(1 for m in members if m.isreg() and m.mode & 0o4000)))

    problems = []
    # The bootstrap set, and the things a kernel and an init actually need.
    for needed in ("./sbin/init", "./sbin/sh", "./sbin/mount", "./sbin/ifconfig",
                   "./sbin/hostname", "./usr/etc/init", "./usr/bin/sh",
                   "./vmunix", "./boot", "./etc/rc", "./etc/rc.boot",
                   "./etc/ttytab", "./dev/console", "./dev/null"):
        m = byname.get(needed)
        if m is None:
            problems.append("missing: %s" % needed)
        elif m.isreg() and m.size == 0:
            problems.append("empty: %s" % needed)

    table, _ = read_dev_table(open(table_path).read())
    for name, isblk, mode, major, minor in table:
        m = byname.get("./dev/" + name)
        if m is None:
            problems.append("device missing: %s" % name)
        elif m.isblk() != isblk or m.devmajor != major or m.devminor != minor:
            problems.append("device wrong: %s is %s %d,%d, table says %s %d,%d"
                            % (name, "blk" if m.isblk() else "chr",
                               m.devmajor, m.devminor,
                               "blk" if isblk else "chr", major, minor))
        elif m.mode != mode:
            problems.append("device mode: %s is %04o, table says %04o"
                            % (name, m.mode, mode))
    print("%s: %d nodes checked against the archive" % (table_path, len(table)))

    for p in problems:
        print("  %s" % p)
    if problems:
        return 1
    print("netboot root: complete")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", nargs="?", help="the disk the emulator tarred onto")
    ap.add_argument("--verify", metavar="ARCHIVE",
                    help="check a finished archive instead of building one")
    ap.add_argument("--out", help="the archive to write")
    ap.add_argument("--dev-table", help="also write the parsed table here")
    ap.add_argument("--list", action="store_true",
                    help="just say what is in the capture")
    args = ap.parse_args()

    if args.verify:
        if not args.dev_table:
            ap.error("--verify needs --dev-table")
        return verify(args.verify, args.dev_table)
    if not args.capture:
        ap.error("a capture image is required")
    if not args.list and not args.out:
        ap.error("--out is required unless --list")

    # Pass one: the device table and the /sbin binaries, both of which have to
    # be in hand before the members that need them are written.
    dev_text, bootstrap = None, {}
    counts = {"files": 0, "dirs": 0, "links": 0}
    with open_capture(args.capture) as tf:
        for m in tf:
            if m.isdir():
                counts["dirs"] += 1
            elif m.issym() or m.islnk():
                counts["links"] += 1
            else:
                counts["files"] += 1
            if m.name in ("./dev.table", "dev.table"):
                dev_text = tf.extractfile(m).read().decode("ascii", "replace")
            elif m.isfile() and m.name.startswith(KVM_BOOT):
                base = m.name[len(KVM_BOOT):]
                if base in SBIN_BOOTSTRAP:
                    bootstrap[base] = (m, tf.extractfile(m).read())

    print("%s: %d files, %d directories, %d links"
          % (args.capture, counts["files"], counts["dirs"], counts["links"]))
    if dev_text is None:
        sys.exit("no dev.table in the capture -- see tools/scripts/capture-root.txt")

    devices, skipped = read_dev_table(dev_text)
    print("dev.table: %d device nodes (%d block, %d character)"
          % (len(devices), sum(1 for d in devices if d[1]),
             sum(1 for d in devices if not d[1])))
    for line in skipped[:5]:
        print("  unparsed: %r" % line)
    missing = [b for b in SBIN_BOOTSTRAP if b not in bootstrap]
    if missing:
        sys.exit("missing from %s: %s" % (KVM_BOOT, ", ".join(missing)))

    if args.dev_table:
        with open(args.dev_table, "w") as f:
            f.write(dev_text)
        print("%s: written" % args.dev_table)

    if args.list:
        return 0

    # Pass two: copy everything through, then add what tar could not carry.
    written = 0
    with open_capture(args.capture) as tf, \
         tarfile.open(args.out, "w:gz", format=tarfile.GNU_FORMAT) as out:
        for m in tf:
            if m.name in CAPTURE_ARTEFACTS:
                continue
            if m.name.startswith("./tmp/") and not m.isdir():
                continue
            # Root owns a distribution.  The capture already says so, but the
            # names travel as numbers and this makes it explicit.
            m.uid, m.gid = 0, 0
            m.uname, m.gname = "root", ""
            out.addfile(m, tf.extractfile(m) if m.isreg() else None)
            written += 1

        for name, isblk, mode, major, minor in devices:
            info = tarfile.TarInfo("./dev/" + name)
            info.type = tarfile.BLKTYPE if isblk else tarfile.CHRTYPE
            info.mode = mode
            info.devmajor, info.devminor = major, minor
            info.uid, info.gid = 0, 0
            info.uname, info.gname = "root", ""
            out.addfile(info)
            written += 1

        for base in SBIN_BOOTSTRAP:
            m, data = bootstrap[base]
            info = tarfile.TarInfo("./sbin/" + base)
            info.size, info.mode, info.mtime = len(data), m.mode, m.mtime
            info.uid, info.gid = 0, 0
            info.uname, info.gname = "root", ""
            out.addfile(info, io.BytesIO(data))
            written += 1

    size = os.path.getsize(args.out)
    print("%s: %d members, %.1f MB" % (args.out, written, size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
