"""Builds docs/linux/ from the real Debian man pages: the Linux man-pages project (manpages, manpages-dev:
sections 2-7) plus the section 1/8 pages of the usual command-line packages (coreutils, util-linux, grep,
sed, systemd...). Downloads the .deb files from deb.debian.org into .cache/debs/.

A name that exists in several sections gets the lowest section (kill = kill(1)); the others get a suffix
(kill-2). `pman linux <name>` or just `pman <name>` opens it."""
import gzip
import io
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from man2txt import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "linux", "man", "linux")
CACHE = os.path.join(ROOT, ".cache")
MIRROR = "https://deb.debian.org/debian/"

PACKAGES = """manpages manpages-dev coreutils util-linux bsdextrautils mount login passwd findutils grep sed gawk tar gzip
bzip2 xz-utils zip unzip procps psmisc lsof strace iproute2 net-tools iptables tcpdump kmod e2fsprogs systemd
openssh-client curl wget rsync less nano diffutils patch make file cron sudo debianutils dpkg apt man-db""".split()
# lower section number wins a shared name
SECTION_ORDER = ["1", "8", "2", "3", "5", "7", "4", "6", "9"]


def packages_index():
    f = os.path.join(CACHE, "Packages.xz")
    if not os.path.exists(f):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.run(["curl", "-sSL", "-m", "120", "-o", f, MIRROR + "dists/stable/main/binary-amd64/Packages.xz"],
                       check=True)
    text = lzma.open(f, "rt", encoding="utf-8").read()
    out = {}
    for blk in text.split("\n\n"):
        m = re.search(r"^Package: (.+)$", blk, re.M)
        if m and m.group(1) in PACKAGES:
            out[m.group(1)] = re.search(r"^Filename: (.+)$", blk, re.M).group(1)
    return out


def download(pkg, filename):
    d = os.path.join(CACHE, "debs")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, os.path.basename(filename))
    if not os.path.exists(f):
        subprocess.run(["curl", "-sSL", "--fail", "-m", "280", "-o", f, MIRROR + filename], check=True)
    return f


def data_tar(deb_path):
    """The data.tar.* member of a .deb (an ar archive)."""
    b = open(deb_path, "rb").read()
    assert b.startswith(b"!<arch>\n")
    i = 8
    while i + 60 <= len(b):
        name = b[i:i + 16].decode().strip()
        size = int(b[i + 48:i + 58].decode().strip())
        body = b[i + 60:i + 60 + size]
        if name.startswith("data.tar"):
            if name.endswith(".xz"):
                return tarfile.open(fileobj=io.BytesIO(lzma.decompress(body)))
            if name.endswith(".gz"):
                return tarfile.open(fileobj=io.BytesIO(gzip.decompress(body)))
            raise RuntimeError("unsupported " + name)
        i += 60 + size + (size & 1)
    raise RuntimeError("no data member in " + deb_path)


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "linux"), ignore_errors=True)
    os.makedirs(OUT)
    index = packages_index()
    pages = {}  # (sec, name) -> troff text
    links = {}  # (sec, target name) -> alias names
    for pkg in PACKAGES:
        if pkg not in index:
            print("not in Debian index:", pkg)
            continue
        tar = data_tar(download(pkg, index[pkg]))
        n = 0
        for m in tar.getmembers():
            mm = re.fullmatch(r"\.?/?usr/share/man/man(\d)/(.+)\.(\d)[a-z]*\.gz", m.name)
            if mm and (m.issym() or m.islnk()):
                # alias page (mkfs.ext4 -> mke2fs): remember it, the target's NAME line gets the extra name
                tm = re.fullmatch(r"(?:.*/)?(.+)\.(\d)[a-z]*\.gz", m.linkname)
                if tm:
                    links.setdefault((tm.group(2), tm.group(1)), []).append(mm.group(2))
                continue
            if not mm or not m.isfile():
                continue
            sec, name = mm.group(1), mm.group(2)
            if (sec, name) in pages:
                continue
            text = gzip.decompress(tar.extractfile(m).read()).decode("utf-8", "replace")
            if text.lstrip().startswith(".so "):
                continue
            pages[(sec, name)] = text
            n += 1
        print(f"{pkg}: {n} pages")
    used = set()
    written = 0
    for sec in SECTION_ORDER:
        for (s, name), text in sorted(pages.items()):
            if s != sec:
                continue
            pid = re.sub(r"[^a-z0-9_.+-]+", "-", name.lower())
            if pid in used:
                pid = f"{pid}-{sec}"
            if pid in used:
                continue
            used.add(pid)
            out = convert(text, pid, sec)
            if len(out) < 400:
                continue
            extra = [a for a in links.get((sec, name), []) if a != name]
            if extra:
                # NAME line "mke2fs - create ..." -> "mke2fs, mkfs.ext4 - create ..."
                out = re.sub(r"(NAME\n\n {7})([^\n]*?) - ",
                             lambda m: m.group(1) + m.group(2) + ", " + ", ".join(extra) + " - ", out, count=1)
            with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
            written += 1
    print("linux pages", written)


if __name__ == "__main__":
    main()
