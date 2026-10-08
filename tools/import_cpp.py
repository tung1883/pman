"""Builds docs/cpp/ from the cppreference.com offline HTML book (CC BY-SA 3.0 / GFDL): the C++ library and
language pages (cpp.vector, cpp.vector-push_back, cpp.sort, cpp.language-class...). Needs the 55 MB zip in .cache/."""
import os
import re
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "cpp", "man", "cpp")
ZIP = os.path.join(ROOT, ".cache", "cppref.zip")
URL = "https://github.com/PeterFeicht/cppreference-doc/releases/download/v20250209/html-book-20250209.zip"
SKIP_DIRS = {"experimental", "locale", "compiler_support", "named_req", "freestanding", "links", "regex", "symbol_index",
             "index", "ranges_ext", "feature_test"}
PREFIXED = {"language": "language", "keywords": "keyword", "preprocessor": "preprocessor", "concepts": "concept",
            "header": "header", "types": "types", "error": "error", "numeric": "numeric", "io": "io",
            "thread": "thread", "filesystem": "fs", "chrono": "chrono", "atomic": "atomic", "memory": "memory"}


def slug(s):
    return re.sub(r"[^a-z0-9_+]+", "-", s.lower()).strip("-")


def page_id(parts):
    top = parts[0]
    if len(parts) == 1:
        return slug(top)
    if top in PREFIXED and len(parts) == 2:
        return f"{PREFIXED[top]}-{slug(parts[1])}"
    if len(parts) >= 3:
        return slug(parts[-2]) + "-" + slug(parts[-1])
    return slug(parts[-1])


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "cpp"), ignore_errors=True)
    os.makedirs(OUT)
    if not os.path.exists(ZIP):
        subprocess.run(["curl", "-sSL", "-m", "290", "-o", ZIP, URL], check=True)
    z = zipfile.ZipFile(ZIP)
    used = set()
    n = 0
    names = sorted(x for x in z.namelist() if x.startswith("reference/en/cpp/") and x.endswith(".html"))
    for name in names:
        rel = name[len("reference/en/cpp/"):-5]
        parts = rel.split("/")
        if parts[0] in SKIP_DIRS:
            continue
        pid = page_id(parts)
        if not pid or pid in used:
            continue
        html = z.read(name).decode("utf-8", "replace")
        text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "mw-content-text", rel, f"cpp.{pid}", "C++",
                       skip_classes={"t-navbar", "editsection", "toc", "mw-editsection", "noprint", "t-example-live-link",
                                     "t-lines", "t-page-template", "t-dsc-see", "t-sdsc-sep"})
        if len(text) < 500:
            continue
        used.add(pid)
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("cpp pages", n)


if __name__ == "__main__":
    main()
