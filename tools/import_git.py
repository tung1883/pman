"""Builds docs/git/ from git-scm.com: the command reference (git.commit, git.rebase, ...) and the Pro Git
book (git.book-*; CC BY-NC-SA 3.0, Scott Chacon and Ben Straub). Needs network; cached in .cache/."""
import hashlib
import os
import re
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "git", "man", "git")
CACHE = os.path.join(ROOT, ".cache")
BASE = "https://git-scm.com"


def fetch(url):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pman-docs-import"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    open(f, "w", encoding="utf-8").write(html)
    time.sleep(0.3)
    return html


def main_div(tag, a):
    return tag == "div" and a.get("id") == "main"


def write(pid, text):
    with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "git"), ignore_errors=True)
    os.makedirs(OUT)
    names = set(re.findall(r'href="/docs/([A-Za-z0-9_.-]+)"', fetch(BASE + "/docs")))
    names |= set(re.findall(r'href="/docs/([A-Za-z0-9_.-]+)"', fetch(BASE + "/docs/git-commit")))
    names = sorted(n for n in names if not n.endswith((".html", ".txt")) and n not in ("user-manual",))
    skip = {"sidebar-btn", "version-info", "sidebar"}
    count = 0
    for name in names:
        try:
            html = fetch(f"{BASE}/docs/{name}")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        if name == "git":
            pid = "git"
        elif name.startswith("git-"):
            pid = name[4:]
        else:
            pid = re.sub(r"^git", "", name) or name  # gitworkflows -> workflows
        text = convert(html, main_div, name, f"git.{pid}", "Git", skip_classes=skip)
        if len(text) < 400:
            continue
        write(pid if pid != "git" else "git", text)
        count += 1
    print("git commands/guides", count)

    # Pro Git book: collect chapter links from the book's own navigation
    first = fetch(BASE + "/book/en/v2/Getting-Started-About-Version-Control")
    links = []
    for l in re.findall(r'href="(/book/en/v2/[^"#?]+)"', first):
        if l not in links and "/ch" not in l.split("/")[-1][:3]:
            links.append(l)
    n = 0
    for l in links:
        stem = l.rsplit("/", 1)[1]
        if stem in ("", "v2"):
            continue
        try:
            html = fetch(BASE + l)
        except Exception as e:  # noqa: BLE001
            print("skip", l, e)
            continue
        pid = "book-" + slug(stem)
        text = convert(html, main_div, stem, f"git.{pid}", "Pro Git", skip_classes=skip)
        if len(text) < 400:
            continue
        write(pid, text)
        n += 1
    print("pro git pages", n)


if __name__ == "__main__":
    main()
