"""Builds docs/bash/: `bash` (the bash(1) man page from the source tarball) and `bash.ref` (the Bash
Reference Manual, with builtins and variables as jumpable sections). Needs network."""
import os
import re
import shutil
import sys
import tarfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert as html_convert  # noqa: E402
from man2txt import convert as man_convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "bash", "man")
CACHE = os.path.join(ROOT, ".cache")
VERSION = "5.3"
TARBALL = f"https://ftp.gnu.org/gnu/bash/bash-{VERSION}.tar.gz"
REF = "https://tiswww.case.edu/php/chet/bash/bashref.html"


def get(url, name):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, name)
    if not os.path.exists(f):
        print("downloading", url)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pman-docs-import"})
        with urllib.request.urlopen(req, timeout=120) as r, open(f, "wb") as o:
            shutil.copyfileobj(r, o)
    return f


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "bash"), ignore_errors=True)
    os.makedirs(os.path.join(OUT, "bash"))

    with tarfile.open(get(TARBALL, f"bash-{VERSION}.tar.gz")) as tar:
        member = tar.getmember(f"bash-{VERSION}/doc/bash.1")
        troff = tar.extractfile(member).read().decode("utf-8", "replace")
    text = man_convert(troff, "bash", "1", label="Bash")
    # inline font macros that leaked into text lines (".B INVOCATION", '.B "SEE ALSO"')
    text = re.sub(r'\.(?:BR|B|I|SM)\s+(?:"([^"]*)"|(\S+))', lambda m: m.group(1) or m.group(2), text)
    with open(os.path.join(OUT, "bash.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("bash(1)", len(text))

    html = open(get(REF, "bashref.html"), encoding="utf-8", errors="replace").read()
    text = html_convert(html, lambda tag, a: tag == "body", "Bash Reference Manual", "bash.ref", "Bash",
                        skip_classes={"nav-panel", "contents", "region-contents", "copiable-link", "header"},
                        skip_ids={"SEC_Contents"}, dt_headings=True)
    with open(os.path.join(OUT, "bash", "ref.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("bashref", len(text))


if __name__ == "__main__":
    main()
