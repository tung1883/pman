"""Builds docs/csharp/ from the C# docs in dotnet/docs (CC BY 4.0, MIT code samples): language reference
(keywords, operators, statements, types), fundamentals, programming guide, tour, LINQ, async. Pages: csharp.<name>
(csharp.lock, csharp.async, csharp.guide-...). Code sample files referenced by :::code directives are inlined.
Needs git + network (sparse clone into .cache/dotnet)."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(ROOT, ".cache", "dotnet")
CS = os.path.join(REPO, "docs", "csharp")
OUT = os.path.join(ROOT, "docs", "csharp", "man", "csharp")
AREAS = [("language-reference", ""), ("fundamentals", "fundamentals-"), ("programming-guide", "guide-"),
         ("tour-of-csharp", "tour-"), ("linq", "linq-"), ("asynchronous-programming", "async-")]
SKIP = re.compile(r"(^|/)(toc|index|snippets|includes|media)(/|$)|compiler-messages|^language-reference/proposals|"
                  r"specification|whats-new", re.I)


def ensure_repo():
    if not os.path.isdir(REPO):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/dotnet/docs.git", REPO], check=True)
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "set", "docs/csharp"], check=True)


CODE = re.compile(r'^:::code\s+(.*?):::\s*$', re.M)


def code_block(m, base):
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    src = attrs.get("source")
    if not src:
        return ""
    path = os.path.normpath(os.path.join(base, src))
    if not os.path.isfile(path):
        return ""
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    sid = attrs.get("id")
    if sid:
        start = next((i for i, l in enumerate(lines) if re.search(r"<\s*" + re.escape(sid) + r"\s*>", l)), None)
        end = next((i for i, l in enumerate(lines) if re.search(r"</\s*" + re.escape(sid) + r"\s*>", l)), None)
        if start is None or end is None or end < start:
            return ""
        lines = lines[start + 1:end]
    elif len(lines) > 80:
        lines = lines[:80]
    lines = [l for l in lines if not re.search(r"</?\s*\w+\s*>\s*$", l) or not re.match(r"\s*(//|#|')\s*</?\w+>", l)]
    indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    body = "\n".join(l[indent:].rstrip() for l in lines)
    return f"```{attrs.get('language', 'csharp')}\n{body}\n```"


def clean(src, base):
    src = CODE.sub(lambda m: code_block(m, base), src)
    src = re.sub(r"\[!INCLUDE\s*\[[^\]]*\]\([^)]*\)\]", "", src)
    src = re.sub(r"<xref:([^>?]+)(?:\?[^>]*)?>", lambda m: m.group(1).split(".")[-1].replace("%60", "`"), src)
    src = re.sub(r"^:::.*$", "", src, flags=re.M)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"\(\s*~/[^)]*\)", "", src)
    return src


def main():
    ensure_repo()
    shutil.rmtree(os.path.join(ROOT, "docs", "csharp"), ignore_errors=True)
    os.makedirs(OUT)
    used = set()
    n = 0
    for area, prefix in AREAS:
        base = os.path.join(CS, area)
        for dirpath, _dirs, files in sorted(os.walk(base)):
            for name in sorted(files):
                if not name.endswith(".md"):
                    continue
                rel = area + "/" + os.path.relpath(os.path.join(dirpath, name), base)[:-3].replace(os.sep, "/")
                if SKIP.search(rel):
                    continue
                src = open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
                meta, body = mdtext.parse_front_matter(src)
                body = clean(body, dirpath)
                title = next((l[2:].strip() for l in body.split("\n") if l.startswith("# ")), None) or \
                    (meta.get("title") if isinstance(meta.get("title"), str) else name[:-3])
                parts = rel.split("/")[1:]
                pid = re.sub(r"[^a-z0-9_.+-]+", "-", (prefix + parts[-1]).lower()).strip("-")
                if pid in used and len(parts) > 1:
                    pid = re.sub(r"[^a-z0-9_.+-]+", "-", (prefix + parts[-2] + "-" + parts[-1]).lower()).strip("-")
                k, base_pid = 2, pid
                while pid in used:
                    pid = f"{base_pid}-{k}"
                    k += 1
                used.add(pid)
                desc = (meta.get("description") if isinstance(meta.get("description"), str) else "").strip("\"' ")
                text = mdtext.convert(body, f"csharp.{pid}", "C#", name_line=f"{title.strip(chr(34))} - {desc[:140]}".rstrip(" -"))
                if len(text) < 400:
                    continue
                with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                n += 1
    print("csharp pages", n)


if __name__ == "__main__":
    main()
