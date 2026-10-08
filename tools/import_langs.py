"""Builds docs/java/ (JLS 21), docs/ruby/ (core classes, Ruby 3.4) and docs/kotlin/ (Kotlin docs, markdown).
Usage: python tools/import_langs.py [java] [ruby] [kotlin]   (default: all). Needs network (+git for kotlin)."""
import glob
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402
from fetchutil import fetch  # noqa: E402
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write(topic, pid, text, sub=None):
    d = os.path.join(ROOT, "docs", topic, "man", sub or topic)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def java():
    shutil.rmtree(os.path.join(ROOT, "docs", "java"), ignore_errors=True)
    n = 0
    for i in range(1, 19):
        url = f"https://docs.oracle.com/javase/specs/jls/se21/html/jls-{i}.html"
        try:
            html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print("skip", url, e)
            continue
        text = convert(html, lambda tag, a: tag == "div" and a.get("class") == "chapter", f"JLS {i}",
                       f"java.jls-{i}", "Java", skip_classes={"navheader", "navfooter", "toc"})
        write("java", f"jls-{i}", text)
        n += 1
    print("java jls chapters", n)


RUBY_CORE = """Array BasicObject Class Comparable Complex Data Dir Encoding Enumerable Enumerator Exception FalseClass File
FileTest Float Hash Integer IO Kernel MatchData Math Method Module NilClass Numeric Object ObjectSpace Proc Process
Random Range Rational Regexp Set Signal String Struct Symbol Thread Time TrueClass UnboundMethod Marshal Fiber
Mutex Queue ENV GC Comparable StandardError ArgumentError TypeError NameError NoMethodError RuntimeError
StopIteration KeyError IndexError IOError ZeroDivisionError FrozenError""".split()


def ruby():
    shutil.rmtree(os.path.join(ROOT, "docs", "ruby"), ignore_errors=True)
    n = 0
    for name in dict.fromkeys(RUBY_CORE):
        url = f"https://docs.ruby-lang.org/en/3.4/{name}.html"
        try:
            html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        text = convert(html, lambda tag, a: tag == "main", name, f"ruby.{name.lower()}", "Ruby",
                       skip_classes={"method-source-code", "method-click-advice", "permalink", "anchor-link"},
                       dt_headings=False)
        if len(text) < 500:
            print("thin", name)
            continue
        write("ruby", name.lower(), text)
        n += 1
    print("ruby classes", n)


def kotlin():
    shutil.rmtree(os.path.join(ROOT, "docs", "kotlin"), ignore_errors=True)
    repo = os.path.join(ROOT, ".cache", "kotlin-site")
    if not os.path.isdir(repo):
        os.makedirs(os.path.dirname(repo), exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/JetBrains/kotlin-web-site.git", repo], check=True)
    subprocess.run(["git", "-C", repo, "sparse-checkout", "set", "docs/topics"], check=True)
    n = 0
    for path in sorted(glob.glob(os.path.join(repo, "docs", "topics", "*.md"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        src = open(path, encoding="utf-8", errors="replace").read()
        src = re.sub(r"(?m)^(#+ .*?)\s*\{[^}]*\}\s*$", r"\1", src)            # heading ids
        src = re.sub(r"```(\w+)\s*\{[^}]*\}", r"```\1", src)                  # code fence attributes
        src = re.sub(r"(?m)^\s*\{[^}]*\}\s*$", "", src)                       # attribute-only lines
        src = re.sub(r"(?m)^\s*<(?:/)?(?:tldr|deflist|def|title|tabs|tab|procedure|step|note|tip|warning|"
                     r"snippet|code-block|list|li|p|table|tr|td|th|include|img|control|format)[^>]*>\s*$", "", src)
        title_m = re.search(r"(?m)^# (.+)$", src)
        title = title_m.group(1).strip() if title_m else stem
        text = mdtext.convert(src, f"kotlin.{stem}", "Kotlin", name_line=f"{title}")
        if len(text) < 500:
            continue
        write("kotlin", re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-"), text)
        n += 1
    print("kotlin topics", n)


def main():
    which = sys.argv[1:] or ["java", "ruby", "kotlin"]
    for w in which:
        {"java": java, "ruby": ruby, "kotlin": kotlin}[w]()


if __name__ == "__main__":
    main()
