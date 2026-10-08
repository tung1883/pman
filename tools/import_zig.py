"""Builds docs/zig/ from the Zig language reference, one page per chapter (zig.comptime, zig.structs...).
The reference is a single HTML page; it is split at its <h2> chapter headings. Needs network."""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "zig", "man", "zig")
VERSION = "0.15.1"
URL = f"https://ziglang.org/documentation/{VERSION}/"
SKIP_CHAPTERS = {"zig-version", "table-of-contents"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "zig"), ignore_errors=True)
    os.makedirs(OUT)
    html = fetch(URL)
    m = re.search(r'<main id="contents">(.*)</main>', html, re.S)
    body = m.group(1) if m else html
    chunks = re.split(r'(?=<h2 id=")', body)
    used = set()
    n = 0
    for chunk in chunks:
        h = re.match(r'<h2 id="([^"]+)"', chunk)
        if not h:
            continue  # text before the first chapter (page title)
        cid = h.group(1)
        if slug(cid) in SKIP_CHAPTERS:
            continue
        pid = slug(cid)
        if pid in used:
            pid += "-2"
        used.add(pid)
        text = convert(f'<div id="cap">{chunk}</div>', lambda tag, a: tag == "div" and a.get("id") == "cap",
                       cid, f"zig.{pid}", "Zig")
        if len(text) < 300:
            continue
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("zig chapters", n)


if __name__ == "__main__":
    main()
