"""Builds docs/powershell/ from the MicrosoftDocs/PowerShell-Docs repo (reference/7.5): the about_*
topics and the cmdlet reference of the core modules. Needs git + network (sparse clone into .cache/)."""
import glob
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "powershell", "man", "powershell")
REPO = os.path.join(ROOT, ".cache", "psdocs")
VERSION = "7.5"
MODULES = ["Microsoft.PowerShell.Core", "Microsoft.PowerShell.Management", "Microsoft.PowerShell.Utility",
           "Microsoft.PowerShell.Security", "Microsoft.PowerShell.Diagnostics", "Microsoft.PowerShell.Host",
           "Microsoft.PowerShell.Archive", "PSReadLine", "ThreadJob"]


def ensure_repo():
    if not os.path.isdir(REPO):
        os.makedirs(os.path.dirname(REPO), exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/MicrosoftDocs/PowerShell-Docs.git", REPO], check=True)
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "set", f"reference/{VERSION}"], check=True)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def synopsis(body):
    m = re.search(r"##\s+SYNOPSIS\s*\n+(.*?)(?:\n\s*\n|\n##)", body, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def main():
    ensure_repo()
    shutil.rmtree(os.path.join(ROOT, "docs", "powershell"), ignore_errors=True)
    os.makedirs(OUT)
    base = os.path.join(REPO, "reference", VERSION)
    used = set()
    n = 0
    for mod in MODULES:
        files = sorted(glob.glob(os.path.join(base, mod, "*.md")) + glob.glob(os.path.join(base, mod, "About", "*.md")))
        for path in files:
            stem = os.path.splitext(os.path.basename(path))[0]
            if stem.lower() in ("index", "readme"):
                continue
            src = open(path, encoding="utf-8", errors="replace").read()
            meta, body = mdtext.parse_front_matter(src)
            title = meta.get("title") or stem
            if isinstance(title, list):
                title = stem
            pid = slug(stem.replace("_", "-"))
            if pid in used:
                continue
            used.add(pid)
            aliases = meta.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            names = ", ".join([title] + aliases)
            syn = synopsis(body)
            name_line = f"{names} - {syn}" if syn else names
            text = mdtext.convert(src, f"powershell.{pid}", "PowerShell", name_line=name_line)
            if len(text) < 300:
                continue
            with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            n += 1
    print("powershell pages", n)


if __name__ == "__main__":
    main()
