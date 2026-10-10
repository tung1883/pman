"""Builds docs/node/ from the Node.js API documentation (nodejs/node, doc/api/*.md, MIT).
Needs git + network (sparse clone into .cache/node).

Pages: node.fs, node.http, node.path, ... one per module (`pman node fs readFile`)."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "node", "man", "node")
REPO = os.path.join(ROOT, ".cache", "node")
SKIP = {"index", "all", "documentation", "synopsis_placeholder"}


def ensure_repo():
    if not os.path.isdir(REPO):
        os.makedirs(os.path.dirname(REPO), exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/nodejs/node.git", REPO], check=True)
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "set", "doc/api"], check=True)


def clean(src):
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)          # YAML metadata, type markers
    src = re.sub(r"^\[[^\]]+\]:.*$", "", src, flags=re.M)     # link reference definitions
    return src


def main():
    ensure_repo()
    shutil.rmtree(os.path.join(ROOT, "docs", "node"), ignore_errors=True)
    os.makedirs(OUT)
    api = os.path.join(REPO, "doc", "api")
    n = 0
    for name in sorted(os.listdir(api)):
        stem, ext = os.path.splitext(name)
        if ext != ".md" or stem in SKIP:
            continue
        src = clean(open(os.path.join(api, name), encoding="utf-8").read())
        title = next((l[2:].strip() for l in src.split("\n") if l.startswith("# ")), stem)
        pid = re.sub(r"[^a-z0-9_.+-]+", "-", stem.lower())
        text = mdtext.convert(src, f"node.{pid}", "Node.js", name_line=f"{pid} - {title}")
        if len(text) < 300:
            continue
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("node pages", n)


if __name__ == "__main__":
    main()
