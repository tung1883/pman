"""Builds docs/gnu/ from the GNU manuals shipped as Info files in Debian packages (GFDL): coreutils, sed, grep,
findutils, diffutils, binutils, and from non-free: gawk, make, gdb, gcc.
One page per manual (gnu.coreutils, gnu.gdb, ...); every Info node is a section, so `pman gnu gdb breakpoints` jumps.
Downloads the .deb files from deb.debian.org into .cache/debs/."""
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
from htmltext import IND, heading_text  # noqa: E402
from import_linux import data_tar, download  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "gnu", "man", "gnu")
CACHE = os.path.join(ROOT, ".cache")
MIRROR = "https://deb.debian.org/debian/"
# (component, package) -> {info file stem: page id}; None = every manual in the package
PACKAGES = [
    ("main", "coreutils", {"coreutils": "coreutils"}),
    ("main", "sed", {"sed": "sed"}),
    ("main", "grep", {"grep": "grep"}),
    ("main", "findutils", {"find": "find", "find-maint": None}),
    ("main", "diffutils", {"diffutils": "diffutils"}),
    ("main", "binutils-doc", {"as": "as", "ld": "ld", "binutils": "binutils", "gprof": "gprof"}),
    ("non-free", "gawk-doc", {"gawk": "gawk", "gawkinet": "gawkinet", "pm-gawk": None}),
    ("non-free", "make-doc", {"make": "make"}),
    ("non-free", "gdb-doc", {"gdb": "gdb"}),
    ("non-free", "gcc-14-doc", {"gcc-14": "gcc"}),
]
SEP = "\x1f"


def index(comp):
    import_cache = os.path.join(CACHE, f"Packages-{comp}.xz")
    if not os.path.exists(import_cache):
        subprocess.run(["curl", "-sSL", "-m", "120", "-o", import_cache,
                        f"{MIRROR}dists/stable/{comp}/binary-amd64/Packages.xz"], check=True)
    out = {}
    for blk in lzma.open(import_cache, "rt", encoding="utf-8").read().split("\n\n"):
        m = re.search(r"^Package: (.+)$", blk, re.M)
        if m:
            out[m.group(1)] = re.search(r"^Filename: (.+)$", blk, re.M).group(1)
    return out


def info_files(tar):
    """stem -> concatenated text of the (possibly split) Info file."""
    parts = {}
    for m in tar.getmembers():
        mm = re.fullmatch(r"\.?/?usr/share/info/([^/]+?)\.info(?:-(\d+))?(?:\.gz)?", m.name)
        if not mm or not m.isfile():
            continue
        raw = tar.extractfile(m).read()
        if m.name.endswith(".gz"):
            raw = gzip.decompress(raw)
        parts.setdefault(mm.group(1), {})[int(mm.group(2) or 0)] = raw.decode("utf-8", "replace")
    return {stem: "".join(p[k] for k in sorted(p)) for stem, p in parts.items()}


MENU_ITEM = re.compile(r"^\* [^:\n]+:(?::|[^\n]*\.)\s")
NOTE = re.compile(r"\*[Nn]ote ([^:]+?)::|\*[Nn]ote ([^:]+?):\s*[^.]*?(?:\.|,)", re.S)


def node_text(body):
    """Info node body -> plain lines: no menus, cross references as plain words."""
    out = []
    in_entry = False
    for line in body.split("\n"):
        if line.startswith("* "):  # menu entry ("* Name:: text" / "* Name: Node. text") or "* Menu:"
            in_entry = True
            continue
        if in_entry:
            if line.startswith((" ", "\t")) and line.strip():
                continue  # wrapped description of the entry
            in_entry = False
            if line.strip() == "":
                continue  # blank lines between entries
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\*[Nn]ote ([^:]+?)::", r"\1", text)
    text = re.sub(r"\*[Nn]ote ([^:\n]+?):\s+[^\n.]*\.?", lambda m: m.group(1), text)
    return text


def convert(stem, pid, text):
    nodes = []
    for chunk in text.split(SEP + "\n"):
        m = re.match(r"\s*File: [^\n]*?Node: ([^,\n]+)[^\n]*\n(.*)", chunk, re.S)
        if m and not chunk.lstrip().startswith(("Tag Table", "Indirect")):
            nodes.append((m.group(1).strip(), m.group(2)))
    head = f"GNU.{pid.upper()}(1)"
    pad = max(2, 80 - len(head) * 2 - len("Sandbox manual"))
    first = nodes[0][1] if nodes else ""
    title = next((l.strip() for l in first.split("\n") if l.strip() and not l.startswith("*")), stem)
    out = [f"{head}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{head}", "",
           IND + "NAME", "", IND + f"{pid} - {title}"[:150], ""]
    seen = set()
    for name, body in nodes:
        h = heading_text(name)
        if not h or h in seen or h in ("TOP", "NAME"):
            h = h if h and h not in seen and h != "NAME" else None
        body = node_text(body)
        # drop the underline rules and the repeated title lines of the node
        body_lines = []
        for line in body.split("\n"):
            if re.fullmatch(r"[=\-.*~^]{3,}\s*", line):
                continue
            body_lines.append(line.rstrip())
        while body_lines and not body_lines[0]:
            body_lines.pop(0)
        if h and h not in seen:
            seen.add(h)
            if out[-1] != "":
                out.append("")
            out += [IND + h, ""]
        for line in body_lines:
            if line == "" and out[-1] == "":
                continue
            out.append(IND + line if line else "")
    out += ["", "GNU manual                               GFDL"]
    return "\n".join(out) + "\n"


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "gnu"), ignore_errors=True)
    os.makedirs(OUT)
    idx = {c: index(c) for c in ("main", "non-free")}
    n = 0
    for comp, pkg, wanted in PACKAGES:
        if pkg not in idx[comp]:
            print("not in index:", pkg)
            continue
        tar = data_tar(download(pkg, idx[comp][pkg]))
        files = info_files(tar)
        for stem, pid in wanted.items():
            if pid is None or stem not in files:
                continue
            text = convert(stem, pid, files[stem])
            with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            n += 1
            print(f"{pkg}: {pid} {len(text)} chars")
        missing = [s for s, p in wanted.items() if p and s not in files]
        if missing:
            print(f"{pkg}: info not found for {missing}; has {sorted(files)}")
    print("gnu pages", n)


if __name__ == "__main__":
    main()
