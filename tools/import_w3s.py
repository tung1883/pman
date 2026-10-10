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


def add_nav(text, prev, nxt, contents=None):
    """Previous/Next lines in tutorial order, before the manual footer; the pager binds [ and ] to them."""
    lines = [f"{label} w3s.{p}" for label, p in (("Previous:", prev), ("Next:", nxt), ("Contents:", contents)) if p]
    if not lines:
        return text
    i = text.rfind("\nW3Schools manual")
    i = i if i >= 0 else len(text)
    return text[:i].rstrip("\n") + "\n\n" + "".join("       " + l + "\n" for l in lines) + text[i:]


def main():
    want = set(sys.argv[1:])
    shutil.rmtree(os.path.join(ROOT, "docs", "w3s"), ignore_errors=True)
    os.makedirs(OUT)
    pages = {}  # url -> pid
    tutorials = []  # (name, pids) per seed, in side-menu order

    def new_pid(u):
        stem = os.path.splitext(os.path.basename(urlparse(u).path))[0]
        if stem in ("default", "index"):
            parts = urlparse(u).path.strip("/").split("/")
            stem = (parts[-2] if len(parts) > 1 else "site") + "_home"
        pid = re.sub(r"[^a-z0-9_.+-]+", "-", stem.lower())
        if pid in pages.values():
            pid = re.sub(r"[^a-z0-9_.+-]+", "-", urlparse(u).path.strip("/").lower().rsplit(".", 1)[0].replace("/", "_"))
        return pid

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
        links = list(dict.fromkeys([url] + menu_links(url, html)))
        n = 0
        order = []
        for u in links:
            if u not in pages:
                pages[u] = new_pid(u)
                n += 1
                order.append(pages[u])
        parts = seed.split("/")
        name = parts[-2] if parts[-1] in ("default.asp", "index.php") else os.path.splitext(parts[-1])[0].split("_")[0]
        tutorials.append((name, order))
        print(f"{seed}: {n} new pages")
    print("pages to fetch:", len(pages))

    texts = {}
    site_nav = {}  # pid -> (previous url, next url) from the page's own Previous/Next buttons
    work = list(pages.items())
    i = 0
    while i < len(work):
        u, pid = work[i]
        i += 1
        try:
            html = fetch(u, 0.4)
        except Exception as e:
            print("failed", u, str(e)[:50])
            continue
        text = page_text(u, html, pid)
        if len(text) < 500:
            continue
        texts[pid] = text
        links = []
        for side, word in (("left", "Previous"), ("right", "Next")):
            m = re.search(r'<a class="w3-%s w3-btn" href="([^"]+)">[^<]*%s' % (side, word), html)
            t = urljoin(u, m.group(1)).split("#")[0].split("?")[0] if m else None
            if t and urlparse(t).netloc == "www.w3schools.com" and re.search(r"\.(asp|php)$", t) \
                    and not (SKIP_URL.search(t) and not KEEP_HOWTO.search(t)):
                links.append(t)
                if t not in pages:  # a page the side menu does not list
                    pages[t] = new_pid(t)
                    work.append((t, pages[t]))
            else:
                links.append(None)
        site_nav[pid] = tuple(links)
        if i % 200 == 0:
            print(i, "/", len(work), "fetched", len(texts), flush=True)
    # Previous/Next: the site's own buttons when that page exists here, else the neighbour in menu order
    menu = {}
    toc_of = {}
    for name, order in tutorials:
        order = [p for p in order if p in texts]
        for k, pid in enumerate(order):
            menu[pid] = (order[k - 1] if k else None, order[k + 1] if k + 1 < len(order) else None)
            toc_of.setdefault(pid, f"{name}_contents")
        toc = f"{name}_contents"
        if len(order) < 2 or toc in texts:
            continue
        rows = []
        for pid in order:
            title = next((l.strip() for l in texts[pid].split("\n")[1:] if l.strip()), pid)
            rows.append(f"        * w3s.{pid}  {title.title()}")
        head = f"{toc.upper()}(1)"
        texts[toc] = (f"{head:<30}Sandbox manual{head:>30}\n\n       {name.upper()} CONTENTS\n\n" + "\n".join(rows)
                      + "\n\nW3Schools manual                        bundled documentation\n")
    for pid in [p for p in texts if not p.endswith("_contents") or p in menu]:
        nav = []
        for j in (0, 1):
            t = site_nav.get(pid, (None, None))[j]
            target = pages.get(t) if t else None
            nav.append(target if target in texts and target != pid else menu.get(pid, (None, None))[j])
        texts[pid] = add_nav(texts[pid], *nav, toc_of.get(pid) if toc_of.get(pid) in texts else None)
    for pid, text in texts.items():
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    written = len(texts)
    print("w3s pages", written)

    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, name), f"man/w3s/{name}")
    print("zip", ZIP, os.path.getsize(ZIP), "bytes")


if __name__ == "__main__":
    main()
