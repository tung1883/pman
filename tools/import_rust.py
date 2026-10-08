"""Builds docs/rust/ from the offline Rust docs shipped by rustup (rust-docs component).

    python tools/import_rust.py [path-to-rust-html]

Pages: rust.book-*, rust.ref-*, rust.cargo-*, rust.rbe-*, rust.nomicon-*, rust.eNNNN (error codes).
"""
import glob
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "rust", "man", "rust")
OLD_DIRS = {"es", "ja", "ko", "zh", "first-edition", "second-edition", "2018-edition", "css", "fonts", "theme", "img"}
SKIP = {"print", "index", "toc", "404", "not_found", "SUMMARY", "README", "contributors", "CHANGELOG"}


def default_html():
    hits = glob.glob(os.path.expanduser("~/.rustup/toolchains/*/share/doc/rust/html"))
    if not hits:
        sys.exit("rust docs not found; run: rustup component add rust-docs")
    return hits[0]


def is_main(tag, attrs):
    return tag == "main"


def slugify(name):
    name = re.sub(r"^(ch\d+-\d+-|appendix-\d+-|chapter_\d+_|\d+-)", "", name)
    name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return name or "index"


def import_book(html_root, sub, prefix, label, used, recursive=True):
    base = os.path.join(html_root, sub)
    pattern = "**/*.html" if recursive else "*.html"
    n = 0
    for path in sorted(glob.glob(os.path.join(base, pattern), recursive=recursive)):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in SKIP:
            continue
        rel = os.path.relpath(path, base)
        if set(rel.split(os.sep)[:-1]) & OLD_DIRS:
            continue
        if os.sep in rel and sub == "cargo":
            parts = rel.split(os.sep)
            if parts[0] == "commands" and not stem.startswith("cargo"):
                continue
        slug = slugify(stem)
        pid = f"{prefix}-{slug}"
        k = 2
        while pid in used:
            pid = f"{prefix}-{slug}-{k}"
            k += 1
        used.add(pid)
        html = open(path, encoding="utf-8", errors="replace").read()
        text = convert(html, is_main, stem, f"rust.{pid}", label,
                       skip_classes={"nav-chapters", "mobile-nav-chapters", "buttons", "boring", "menu-bar",
                                     "play-button", "clip-button", "header-link"})
        if len(text) < 300 or "no longer distributed" in text:
            continue
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    return n


def import_errors(html_root):
    n = 0
    for path in sorted(glob.glob(os.path.join(html_root, "error_codes", "E*.html"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        html = open(path, encoding="utf-8", errors="replace").read()
        text = convert(html, is_main, stem, f"rust.{stem.lower()}", "Rust",
                       skip_classes={"nav-chapters", "mobile-nav-chapters", "buttons", "boring", "menu-bar"})
        with open(os.path.join(OUT, stem.lower() + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    return n


def main():
    html_root = sys.argv[1] if len(sys.argv) > 1 else default_html()
    shutil.rmtree(os.path.join(ROOT, "docs", "rust"), ignore_errors=True)
    os.makedirs(OUT)
    used = set()
    total = 0
    for sub, prefix, label in [("book", "book", "Rust book"), ("reference", "ref", "Rust reference"),
                               ("cargo", "cargo", "Cargo book"), ("rust-by-example", "rbe", "Rust by Example"),
                               ("nomicon", "nomicon", "Rustonomicon")]:
        n = import_book(html_root, sub, prefix, label, used)
        print(sub, n)
        total += n
    n = import_errors(html_root)
    print("error codes", n)
    print("total", total + n)


if __name__ == "__main__":
    main()
