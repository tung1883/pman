"""Builds docs/go/ from go.dev: the language spec, Effective Go, FAQ, memory model and the
documentation of common standard-library packages (pkg.go.dev). Needs network; pages are cached in .cache/."""
import hashlib
import os
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "go", "man", "go")
CACHE = os.path.join(ROOT, ".cache")

DOCS = {
    "spec": "https://go.dev/ref/spec",
    "effective": "https://go.dev/doc/effective_go",
    "faq": "https://go.dev/doc/faq",
    "mem": "https://go.dev/ref/mem",
}
PKGS = """fmt strings strconv os io bufio errors sort time sync sync/atomic context math math/rand bytes regexp
path path/filepath flag log log/slog testing unicode unicode/utf8 slices maps cmp iter container/list container/heap
os/exec io/fs net net/http net/url encoding/json encoding/csv encoding/base64 encoding/binary text/template
html/template crypto/sha256 crypto/rand hash/fnv runtime reflect embed os/signal bufio archive/zip compress/gzip
database/sql net/netip time/tzdata unsafe""".split()


def fetch(url):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pman-docs-import"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    open(f, "w", encoding="utf-8").write(html)
    time.sleep(0.4)
    return html


def main_region(tag, a):
    return tag == "main"


def pkg_region(tag, a):
    return tag == "div" and "Documentation-content" in (a.get("class") or "")


def write(pid, text):
    with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "go"), ignore_errors=True)
    os.makedirs(OUT)
    skip = {"nav", "SiteNav", "go-Main-header", "Documentation-sidenav", "Documentation-exampleButtonsContainer",
            "Documentation-indexHeader", "go-Message", "UnitMeta", "Documentation-sourceLink", "js-sourceLink"}
    for name, url in DOCS.items():
        text = convert(fetch(url), main_region, name, f"go.{name}", "Go",
                       skip_classes=skip, skip_ids={"nav", "TOC", "Contents"})
        write(name, text)
        print(name, len(text))
    for pkg in PKGS:
        pid = pkg.replace("/", "-")
        try:
            html = fetch("https://pkg.go.dev/" + pkg)
        except Exception as e:  # noqa: BLE001
            print("skip", pkg, e)
            continue
        text = convert(html, pkg_region, pkg, f"go.{pid}", "Go", skip_classes=skip)
        if len(text) < 500:
            print("thin", pkg, len(text))
            continue
        write(pid, text)
        print(pkg, len(text))


if __name__ == "__main__":
    main()
