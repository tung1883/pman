"""Verifies every `Previous:`/`Next:`/`Contents:` footer target exists and that `next(prev(x)) == x`
where both are present. Run against docs/<pack>/man before committing a navlinks change; wired into
the CI workflow (packs.yml) after the importers run.

    python tools/check_nav.py [pack...]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

LABEL_RE = re.compile(r"(Previous|Next|Contents):\s+(\S+)")


def ids_in(man_dir):
    """page id -> text, same `man/js.txt` -> `js`, `man/ts/classes.txt` -> `ts.classes` scheme pman uses."""
    out = {}
    for base, _dirs, files in os.walk(man_dir):
        for f in files:
            if not f.endswith(".txt"):
                continue
            rel = os.path.relpath(os.path.join(base, f), man_dir)
            pid = rel[:-4].replace(os.sep, ".")
            with open(os.path.join(base, f), encoding="utf-8") as fh:
                out[pid] = fh.read()
    return out


def check_pack(pack):
    man_dir = os.path.join(DOCS, pack, "man")
    if not os.path.isdir(man_dir):
        return 0
    pages = ids_in(man_dir)
    nav = {}  # pid -> {"Previous": id, "Next": id, "Contents": id}
    errors = 0
    for pid, text in pages.items():
        tail = "\n".join(text.splitlines()[-12:])
        links = {}
        for label, target in LABEL_RE.findall(tail):
            links[label] = target
            if target not in pages:
                print(f"{pack}: {pid} {label}: '{target}' does not exist")
                errors += 1
        nav[pid] = links
    for pid, links in nav.items():
        nxt = links.get("Next")
        if nxt and nxt in nav:
            back = nav[nxt].get("Previous")
            if back and back != pid:
                print(f"{pack}: {pid} -> Next {nxt}, but its Previous is {back}, not {pid}")
                errors += 1
    return errors


def main():
    want = sys.argv[1:] or sorted(os.listdir(DOCS))
    total = 0
    for pack in want:
        total += check_pack(pack)
    if total:
        print(f"{total} navigation error(s)")
        sys.exit(1)
    print("navigation ok")


if __name__ == "__main__":
    main()
