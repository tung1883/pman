"""Builds docs/sql/: SQLite (sqlite.*) and PostgreSQL (pg.*) documentation. Needs network; cached in .cache/."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "sql", "man")
CACHE = os.path.join(ROOT, ".cache")

SQLITE = "https://sqlite.org/"
SQLITE_EXTRA = ["pragma", "datatype3", "lang_datefunc", "lang_corefunc", "lang_aggfunc", "windowfunctions", "json1",
                "fts5", "fts3", "rtree", "withoutrowid", "foreignkeys", "lang_transaction", "isolation", "wal",
                "optoverview", "queryplanner", "cli", "limits", "stricttables", "gencol", "partialindex",
                "expridx", "lang_upsert", "lang_returning", "lockingv3", "sqlite", "builddir", "cmdline-opts"]
PG = "https://www.postgresql.org/docs/current/"
PG_CHAPTERS = ["ddl", "dml", "queries", "datatype", "functions", "indexes", "mvcc", "perform", "sql-syntax",
               "textsearch", "plpgsql", "sql-commands", "app-psql", "high-availability"]


def fetch(url):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read()
    # curl: python's bundled CA store rejects some of these sites' certificate chains
    html = subprocess.run(["curl", "-sSL", "--fail", "-m", "90", "-A", "Mozilla/5.0 pman-docs-import", url],
                          capture_output=True, check=True).stdout.decode("utf-8", "replace")
    open(f, "w", encoding="utf-8").write(html)
    time.sleep(0.25)
    return html


def write(topic, pid, text):
    d = os.path.join(OUT, topic)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sqlite():
    names = set(re.findall(r"href=[\"']?(lang_[a-z0-9_]+)\.html", fetch(SQLITE + "lang.html")))
    names |= set(SQLITE_EXTRA)
    n = 0
    for name in sorted(names):
        try:
            html = fetch(f"{SQLITE}{name}.html")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        pid = re.sub(r"^lang_", "", name).replace("_", "-")
        text = convert(html, lambda tag, a: tag == "div" and a.get("class") == "fancy", name, f"sqlite.{pid}", "SQLite",
                       skip_classes={"nosearch", "fancy-toc1", "fancy-toc2", "fancy_title", "toc"}, skip_ids={"toc_sub"})
        if len(text) < 500:
            print("thin", name, len(text))
            continue
        write("sqlite", pid, text)
        n += 1
    print("sqlite", n)


def postgres():
    pages = []
    for ch in PG_CHAPTERS:
        try:
            html = fetch(f"{PG}{ch}.html")
        except Exception as e:  # noqa: BLE001
            print("skip", ch, e)
            continue
        pages.append(ch)
        for l in re.findall(r'href="([a-z0-9-]+)\.html"', html):
            ok = l.startswith(("sql-", "functions-", "datatype-", "ddl-", "dml-", "queries-", "indexes-", "mvcc-",
                               "textsearch-", "plpgsql-", "app-psql", "performance-", "using-explain", "sql-syntax",
                               "transaction-iso", "explicit-locking", "high-availability", "warm-standby"))
            if ok and l not in pages:
                pages.append(l)
    n = 0
    for name in pages:
        try:
            html = fetch(f"{PG}{name}.html")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        pid = re.sub(r"^sql-", "", name)
        text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "docContent", name, f"pg.{pid}", "PostgreSQL",
                       skip_classes={"navheader", "navfooter", "toc", "breadcrumb"})
        if len(text) < 500:
            continue
        write("pg", pid, text)
        n += 1
    print("postgres", n)


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "sql"), ignore_errors=True)
    os.makedirs(OUT)
    sqlite()
    postgres()


if __name__ == "__main__":
    main()
