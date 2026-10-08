"""Adds the local `Get-Help -Full` text of this machine's PowerShell (pwsh 7 first, then Windows PowerShell 5.1)
to docs/powershell/ for commands the online-docs import does not have (Windows-only modules such as NetTCPIP,
Storage, Hyper-V, ...). Run after import_powershell.py:

    pwsh -NoProfile -File tools/dump_gethelp.ps1 -OutDir .cache/gethelp/pwsh
    powershell -NoProfile -File tools/dump_gethelp.ps1 -OutDir .cache/gethelp/winps
    python tools/import_gethelp.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import IND, heading_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "powershell", "man", "powershell")
SOURCES = [os.path.join(ROOT, ".cache", "gethelp", "pwsh"), os.path.join(ROOT, ".cache", "gethelp", "winps")]
HEADING = re.compile(r"^[A-Z][A-Z ]{2,}$")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("_", "-")).strip("-")


def section(lines, name):
    """Text lines of the section called `name`."""
    out, on = [], False
    for l in lines:
        if HEADING.match(l):
            on = l.strip() == name
            continue
        if on:
            out.append(l.strip())
    return [x for x in out if x]


def convert(name, text):
    lines = text.replace("\r", "").split("\n")
    synopsis = " ".join(section(lines, "SYNOPSIS")) or " ".join(section(lines, "SHORT DESCRIPTION"))
    if not synopsis or synopsis.lower().startswith(name.lower() + " ") or synopsis.startswith(name + "\n"):
        return None  # help files were not installed: only the syntax echo is there
    if not any(HEADING.match(l) and l.strip() in ("DESCRIPTION", "LONG DESCRIPTION", "TOPIC") for l in lines) \
            and len(section(lines, "SYNTAX")) < 1:
        return None
    h = f"POWERSHELL.{slug(name).upper()}(1)"
    pad = max(2, 80 - len(h) * 2 - len("Sandbox manual"))
    out = [f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}", "",
           IND + "NAME", "", IND + f"{name} - {synopsis}"[:200], ""]
    skip_name = False
    for l in lines:
        l = l.rstrip()
        if HEADING.match(l):
            skip_name = l == "NAME"
            if skip_name:
                continue
            out += ["", IND + l, ""]
            continue
        if skip_name:
            continue
        m = re.match(r"^\s*-{5,}\s*(EXAMPLE \d+)\s*-{5,}\s*$", l)
        if m:
            out += ["", IND + heading_text(m.group(1)), ""]
            continue
        if not l.strip():
            out.append("")
            continue
        t = l[4:] if l.startswith("    ") else l.lstrip()
        verbatim = (t.startswith((" ", "-")) or t.startswith(("PS ", "C:\\", "PS>")) or "\\>" in t[:6])
        out.append(IND + ("  " + t if verbatim else t))
    while out and out[-1] == "":
        out.pop()
    out += ["", "PowerShell manual".ljust(40) + "from Get-Help", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def main():
    os.makedirs(OUT, exist_ok=True)
    existing = {f[:-4] for f in os.listdir(OUT)}
    added = 0
    for src in SOURCES:
        if not os.path.isdir(src):
            continue
        for f in sorted(os.listdir(src)):
            name = f[:-4]
            pid = slug(name)
            if pid in existing or not pid:
                continue
            text = open(os.path.join(src, f), encoding="utf-8", errors="replace").read()
            page = convert(name, text)
            if not page:
                continue
            with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as o:
                o.write(page)
            existing.add(pid)
            added += 1
        print(os.path.basename(src), "->", added, "pages so far")
    print("added", added)


if __name__ == "__main__":
    main()
