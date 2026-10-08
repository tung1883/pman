"""Builds docs/cmd/ from tldr-pages (common + linux): short example-driven pages for ~6000 commands.
Needs git + network (sparse clone into .cache/tldr)."""
import glob
import os
import re
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "cmd", "man", "cmd")
REPO = os.path.join(ROOT, ".cache", "tldr")
IND = " " * 7


def ensure_repo():
    if not os.path.isdir(REPO):
        os.makedirs(os.path.dirname(REPO), exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/tldr-pages/tldr.git", REPO], check=True)
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "set", "pages/common", "pages/linux"], check=True)


def placeholders(s):
    return re.sub(r"\{\{(.*?)\}\}", lambda m: m.group(1) if m.group(1).startswith("[") else f"<{m.group(1)}>", s)


def convert(md, name):
    lines = md.split("\n")
    title = name
    desc = []
    more = ""
    examples = []  # (description, command)
    pending = None
    for line in lines:
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
        elif s.startswith(">"):
            t = s.lstrip("> ").strip()
            if t.lower().startswith("more information"):
                more = re.sub(r"<(.*?)>", r"\1", t)
            elif t.lower().startswith("see also") or t.lower().startswith("this command is an alias"):
                desc.append(t)
            elif t:
                desc.append(re.sub(r"`", "", t))
        elif s.startswith("- "):
            pending = re.sub(r"`", "", s[2:].strip())
        elif s.startswith("`") and s.endswith("`") and len(s) > 2:
            examples.append((pending or "", placeholders(s.strip("`"))))
            pending = None
    h = f"{('CMD.' + name).upper()}(1)"
    pad = max(2, 80 - len(h) * 2 - len("Sandbox manual"))
    out = [f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}", ""]
    first = desc[0] if desc else ""
    out += [IND + "NAME", "", IND + f"{name} - {first}".rstrip(" -"), ""]
    if len(desc) > 1 or more:
        out += [IND + "DESCRIPTION", ""]
        for d in desc[1:]:
            out += [IND + d, ""]
        if more:
            out += [IND + more, ""]
    out += [IND + "EXAMPLES", ""]
    for d, cmd in examples:
        if d:
            out += [IND + d, ""]
        out += [IND + "  " + cmd, ""]
    while out and out[-1] == "":
        out.pop()
    out += ["", "tldr manual".ljust(40) + "from tldr-pages", ""]
    return "\n".join(out)


def main():
    ensure_repo()
    shutil.rmtree(os.path.join(ROOT, "docs", "cmd"), ignore_errors=True)
    os.makedirs(OUT)
    seen = set()
    n = 0
    for sub in ("common", "linux"):
        for path in sorted(glob.glob(os.path.join(REPO, "pages", sub, "*.md"))):
            name = os.path.splitext(os.path.basename(path))[0]
            if name in seen:
                continue
            seen.add(name)
            md = open(path, encoding="utf-8", errors="replace").read()
            text = convert(md, name)
            with open(os.path.join(OUT, name.lower() + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            n += 1
    print("cmd pages", n)


if __name__ == "__main__":
    main()
