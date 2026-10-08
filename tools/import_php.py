"""Builds docs/php/ from the official PHP manual tarball (php.net, CC BY 3.0): the language reference, the
functions of the core extensions (php.strlen...), and core classes. Needs network (13 MB download, cached)."""
import os
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import IND, convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "php", "man", "php")
CACHE = os.path.join(ROOT, ".cache")
TAR = os.path.join(CACHE, "php_manual_en.tar.gz")
URL = "https://www.php.net/distributions/manual/php_manual_en.tar.gz"

REFS = """strings array math json pcre filesystem datetime mbstring ctype url var funchand classobj info outcontrol
session random hash password curl pdo spl iconv dir errorfunc misc network mysqli openssl sodium zlib intl""".split()
CLASSES = """exception errorexception error typeerror valueerror closure generator datetime datetimeimmutable
dateinterval dateperiod datetimezone pdo pdostatement arrayobject arrayiterator splstack splqueue splobjectstorage
splfixedarray splminheap splmaxheap spldoublylinkedlist stringable countable iterator iteratoraggregate arrayaccess
jsonserializable weakmap weakreference reflectionclass reflectionfunction random-randomizer""".split()


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "php"), ignore_errors=True)
    os.makedirs(OUT)
    if not os.path.exists(TAR):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.run(["curl", "-sSL", "-m", "280", "-A", "Mozilla/5.0", "-o", TAR, URL], check=True)
    files = {}
    with tarfile.open(TAR) as tar:
        for m in tar:
            if m.isfile() and m.name.endswith(".html"):
                files[os.path.basename(m.name)[:-5]] = tar.extractfile(m).read().decode("utf-8", "replace")
    print("manual pages", len(files))

    wanted = {}  # source name -> page id
    for ref in REFS:
        html = files.get(f"ref.{ref}", "")
        for fn in re.findall(r'href="(function\.[a-z0-9-]+)\.html"', html):
            if fn in files:
                wanted[fn] = fn[len("function."):].replace("-", "_")
    for name in files:
        if name.startswith("language."):
            wanted[name] = "lang-" + name[len("language."):].replace(".", "-")
    for c in CLASSES:
        if f"class.{c}" in files:
            wanted[f"class.{c}"] = "class-" + c
    for extra in ("reserved.keywords", "reserved.variables.argv", "types", "control-structures", "oop5", "functions"):
        pass
    used = set()
    n = 0
    for src, pid in sorted(wanted.items()):
        if pid in used:
            continue
        used.add(pid)
        html = files[src]
        text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "layout-content", pid, f"php.{pid}", "PHP",
                       skip_classes={"navbar", "breadcrumbs", "up", "prev", "next", "manualnavbar", "notes", "contribute",
                                     "phpcode-hidden", "refsect-seealso-hidden"})
        if len(text) < 400:
            continue
        m = re.search(r'<p class="refpurpose">.*?<span class="dc-title">(.*?)</span>', html, re.S)
        if m and src.startswith("function."):
            purpose = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            nm = pid
            lines = text.split("\n")
            lines[2:2] = [IND + "NAME", "", IND + f"{nm} - {purpose}", ""]
            text = "\n".join(lines)
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("php pages", n)


if __name__ == "__main__":
    main()
