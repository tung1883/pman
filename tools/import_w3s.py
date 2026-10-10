"""Builds docs/w3s/ and dist-local/w3s.zip from the W3Schools tutorials and references.

PERSONAL USE ONLY. W3Schools content is copyrighted and its terms do not allow redistribution, so this pack is
never added to build_packs.py / the public release. Run it yourself; it fetches politely (cached in .cache/,
resumable) and writes a zip you install on your own machine with `pman add dist-local/w3s.zip`.

    python tools/import_w3s.py            all tutorials and references
    python tools/import_w3s.py html css   only these (seed directory names)
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "w3s", "man", "w3s")
ZIP = os.path.join(ROOT, "dist-local", "w3s.zip")
SITE = "https://www.w3schools.com/"

# directory -> start page; the page's side menu lists every other page of that tutorial or reference
SEEDS = """html/default.asp css/default.asp js/default.asp python/default.asp sql/default.asp php/default.asp
java/default.asp c/index.php cpp/default.asp cs/index.php react/default.asp nodejs/default.asp django/index.php
bootstrap5/index.php w3css/default.asp jquery/default.asp xml/default.asp ajax/default.asp json/default.asp
typescript/index.php git/default.asp mysql/default.asp mongodb/index.php postgresql/index.php r/default.asp
go/index.php kotlin/index.php rust/index.php swift/default.asp python/numpy/default.asp python/pandas/default.asp
python/scipy/index.php python/matplotlib_intro.asp dsa/index.php ai/default.asp gen_ai/index.php
datascience/default.asp statistics/index.php excel/index.php cybersecurity/index.php bash/index.php
sass/default.asp vue/index.php angular/default.asp angularjs/default.asp asp/default.asp aws/index.php
graphics/default.asp svg/default.asp howto/default.asp tags/default.asp cssref/index.php jsref/default.asp
colors/default.asp charsets/default.asp browsers/default.asp htmlcss/default.asp""".split()

SKIP_URL = re.compile(r"exercise|quiz|compiler|challenge|syllabus|study_plan|training|practice|bootcamp|certif|"
                      r"tryit|trypython|trycss|spaces|pathfinder|server\.asp|interview|get_started_ai|/c/c_ex|"
                      r"howto_.*\.asp$", re.I)
KEEP_HOWTO = re.compile(r"/howto/", re.I)


def menu_links(seed_url, html):
    """Page URLs in the side menu of a tutorial/reference page."""
    i = html.find("id='leftmenuinnerinner'")
    if i < 0:
        i = html.find('id="leftmenuinnerinner"')
    j = html.find("id='belowtopnav'", i)
    block = html[i:j if j > i else i + 400000]
    out = []
    for href in re.findall(r"href=[\"']([^\"'#]+)[\"']", block):
        url = urljoin(seed_url, href).split("#")[0].split("?")[0]
        p = urlparse(url)
        if p.netloc != "www.w3schools.com" or not re.search(r"\.(asp|php)$", p.path):
            continue
        if SKIP_URL.search(url) and not KEEP_HOWTO.search(url):
            continue
        if re.search(r"/(default\.asp|index\.php)$", p.path) and url != seed_url and p.path.count("/") <= 2 \
                and urlparse(seed_url).path.split("/")[1] != p.path.split("/")[1]:
            continue  # link to another tutorial's front page
        out.append(url)
    return out


def code_blocks(html):
    def one(m):
        inner = re.sub(r"<br\s*/?>[ \t]*\r?\n?", "\n", m.group(1))
        return "<pre>" + inner + "</pre>"
    return re.sub(r"<div class=\"w3-code(?!line)[^\"]*\">(.*?)</div>", one, html, flags=re.S)


def page_text(url, html, pid):
    html = code_blocks(html)
    html = re.sub(r"<h3>\s*Example\s*</h3>", "", html)
    text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "main", pid.replace("_", " "), pid, "W3Schools",
                   skip_classes={"nextprev", "w3-btn", "w3-bar", "ws-hide", "w3-hide-large", "tut_overview", "w3-codeline", "ws-share"},
                   skip_ids={"mainLeaderboard", "midcontentadcontainer", "bottomadcontainer", "snigel-leaderboard"})
    # progress widget / account promo leftovers
    text = re.sub(r"[ \t]*TRACK YOUR PROGRESS\n.*?without creating an account\.\n", "", text, flags=re.S)
    text = re.sub(r"[ \t]*(?:★ \+\d+|Sign in to track progress)", "", text)
    return re.sub(r"\n[ \t]+\n(?=[ \t]*\n)", "\n", re.sub(r"[ \t]+$", "", text, flags=re.M))


def main():
    want = set(sys.argv[1:])
    shutil.rmtree(os.path.join(ROOT, "docs", "w3s"), ignore_errors=True)
    os.makedirs(OUT)
    pages = {}  # url -> pid
    for seed in SEEDS:
        top = seed.split("/")[0] if not seed.startswith("python/") else seed.split("/")[1] if seed.count("/") > 1 else "python"
        if want and seed.split("/")[0] not in want and top not in want:
            continue
        url = SITE + seed
        try:
            html = fetch(url, 0.4)
        except Exception as e:
            print("seed failed", seed, str(e)[:60])
            continue
        links = [url] + menu_links(url, html)
        n = 0
        for u in links:
            if u not in pages:
                stem = os.path.splitext(os.path.basename(urlparse(u).path))[0]
                if stem in ("default", "index"):
                    stem = urlparse(u).path.strip("/").split("/")[-2] + "_home"
                pid = re.sub(r"[^a-z0-9_.+-]+", "-", stem.lower())
                if pid in pages.values():
                    pid = re.sub(r"[^a-z0-9_.+-]+", "-", urlparse(u).path.strip("/").lower().rsplit(".", 1)[0].replace("/", "_"))
                pages[u] = pid
                n += 1
        print(f"{seed}: {n} new pages")
    print("pages to fetch:", len(pages))

    written = 0
    for i, (u, pid) in enumerate(pages.items(), 1):
        try:
            html = fetch(u, 0.4)
        except Exception as e:
            print("failed", u, str(e)[:50])
            continue
        text = page_text(u, html, pid)
        if len(text) < 500:
            continue
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written += 1
        if i % 200 == 0:
            print(i, "/", len(pages), "written", written, flush=True)
    print("w3s pages", written)

    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, name), f"man/w3s/{name}")
    print("zip", ZIP, os.path.getsize(ZIP), "bytes")


if __name__ == "__main__":
    main()
