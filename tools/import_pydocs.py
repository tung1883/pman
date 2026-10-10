"""Builds docs/python/ from the official Python 3.12 documentation (PSF license), using the plain-text build
that docs.python.org publishes (python-3.12-docs-text.zip, produced by Sphinx).

Pages: python.<module> (library reference: python.json, python.os.path), python.tutorial-*, python.ref-*
(language reference), python.howto-*, python.using-*, python.faq-*. `pman python json dumps` jumps to a section.
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import IND, heading_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "python", "man", "python")
CACHE = os.path.join(ROOT, ".cache", "pydocs")
URL = "https://docs.python.org/3.12/archives/python-3.12-docs-text.zip"
SECTIONS = {"library": "", "tutorial": "tutorial-", "reference": "ref-", "howto": "howto-", "using": "using-",
            "faq": "faq-"}
UNDERLINE = re.compile(r"^([=\-~^*#\"'`+:._])\1{2,}\s*$")
SIGNATURE = re.compile(r"^(?:class |exception |async |@)*([A-Za-z_][\w.]*)\(")


def source_dir():
    root = os.path.join(CACHE, "python-3.12-docs-text")
    if not os.path.isdir(root):
        os.makedirs(CACHE, exist_ok=True)
        z = os.path.join(CACHE, "py.zip")
        subprocess.run(["curl", "-sSL", "--fail", "-o", z, URL], check=True)
        with zipfile.ZipFile(z) as f:
            f.extractall(CACHE)
    return root


def convert(text, pid, title):
    lines = text.replace("\r\n", "\n").split("\n")
    head = f"{pid.upper()}(1)"
    pad = max(2, 80 - len(head) * 2 - len("Sandbox manual"))
    out = [f"{head}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{head}", "",
           IND + "NAME", "", IND + f"{pid} - {title}", ""]
    i = 0
    first = True
    while i < len(lines):
        line = lines[i].rstrip()
        nxt = lines[i + 1].rstrip() if i + 1 < len(lines) else ""
        if line and not line.startswith(" ") and UNDERLINE.match(nxt) and not UNDERLINE.match(line) and abs(len(nxt) - len(line)) <= 4:
            h = heading_text(line)
            if first:  # the page title repeats the NAME line
                first = False
            elif h:
                if out[-1] != "":
                    out.append("")
                out += [IND + h, ""]
            i += 2
            continue
        m = SIGNATURE.match(line) if line and not line.startswith(" ") else None
        if m:
            # an API entry: the name is the heading, the signature (possibly wrapped) stays as text
            h = heading_text(m.group(1))
            if h and len(h) >= 3:
                if out[-1] != "":
                    out.append("")
                out += [IND + h, ""]
        if UNDERLINE.match(line):  # rule lines under "Source code" and the like
            i += 1
            continue
        if line == "" and out[-1] == "":
            i += 1
            continue
        out.append(IND + line if line else "")
        i += 1
    out += ["", "Python documentation                     PSF license"]
    return "\n".join(out) + "\n"


def main():
    src = source_dir()
    shutil.rmtree(os.path.join(ROOT, "docs", "python"), ignore_errors=True)
    os.makedirs(OUT)
    n = 0
    used = set()
    for sec, prefix in SECTIONS.items():
        base = os.path.join(src, sec)
        for dirpath, _dirs, files in os.walk(base):
            for name in sorted(files):
                if not name.endswith(".txt"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), base)[:-4].replace(os.sep, "-")
                if rel in ("index", "contents") or rel.endswith("-index"):
                    continue
                pid = re.sub(r"[^a-z0-9_.+-]+", "-", (prefix + rel).lower())
                if pid in used:
                    continue
                used.add(pid)
                text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                title = re.sub(r'"([^"]*)"', r"\1", text.split("\n", 1)[0].strip(), count=1)
                page = convert(text, "python." + pid, title)
                if len(page) < 400:
                    continue
                with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                    f.write(page)
                n += 1
    print("python pages", n)


if __name__ == "__main__":
    main()
