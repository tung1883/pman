"""Builds sysadmin doc packs from documentation websites / files (polite crawl, cached in .cache/):

    python tools/import_webops.py                 all of them
    python tools/import_webops.py nginx apache    only these

    nginx    nginx.org/en/docs: guides, module and directive reference (BSD-2-Clause)
    apache   Apache HTTP Server 2.4 manual: modules, directives, programs, how-tos (Apache-2.0)
    haproxy  HAProxy configuration and management manuals, from the source tree (GPL-2.0)
    debref   Debian Reference (GPL-2+): packages, networking, system tips, data management
    freebsd  FreeBSD Handbook (BSD-2-Clause), one big page with every chapter as a section
Pages are <pack>.<name>: pman nginx ngx_http_proxy_module proxy_pass, pman haproxy configuration."""
import os
import re
import shutil
import sys
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import IND, convert, heading_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def links(html, base, prefix, pattern):
    out = []
    for href in re.findall(r'href="([^"#]+)"', html):
        u = urljoin(base, href).split("?")[0]
        if u.startswith(prefix) and re.search(pattern, u) and u not in out:
            out.append(u)
    return out


def writer(pack):
    out = os.path.join(ROOT, "docs", pack, "man", pack)
    shutil.rmtree(os.path.join(ROOT, "docs", pack), ignore_errors=True)
    os.makedirs(out)
    count = [0]

    def write(pid, text):
        pid = re.sub(r"[^a-z0-9_.+-]+", "-", pid.lower()).strip("-")
        if len(text) < 400:
            return
        with open(os.path.join(out, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        count[0] += 1
    return write, count


def unique(used, rel):
    """Page id from a relative path: the file stem, or dir-stem when the stem is taken."""
    parts = rel.replace(os.sep, "/").split("/")
    pid = parts[-1]
    if pid in used and len(parts) > 1:
        pid = parts[-2] + "-" + parts[-1]
    used.add(pid)
    return pid


def nginx():
    write, count = writer("nginx")
    used = set()
    base = "https://nginx.org/en/docs/"
    index = fetch(base, 0.5)
    pages = [u for u in links(index, base, base, r"\.html$") if "/ru/" not in u and "/njs/" not in u]
    pages += [u for u in links(index, base, "https://nginx.org/en/", r"(?:linux_packages|security_advisories|CHANGES)") if False]
    for u in pages:
        try:
            html = fetch(u, 0.5)
        except Exception as e:
            print("failed", u, str(e)[:40])
            continue
        # each directive block gets its name as a heading
        html = re.sub(r'<a name="([^"]+)"></a>\s*<div class="directive">', r'<h3>\1</h3><div class="directive">', html)
        pid = unique(used, os.path.splitext(os.path.relpath(urlparse(u).path, "/en/docs/"))[0])
        text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "content", pid.replace("_", " "), "nginx." + pid, "nginx")
        write(pid, text)
    print("nginx pages", count[0])


def apache():
    write, count = writer("apache")
    used = set()
    base = "https://httpd.apache.org/docs/2.4/"
    pages = []
    for sect in ("mod/", "programs/", "howto/", "misc/", "ssl/", "vhosts/", "rewrite/"):
        try:
            idx = fetch(base + sect, 0.5)
        except Exception:
            continue
        pages += [u for u in links(idx, base + sect, base + sect.split("/")[0], r"\.html$")
                  if not re.search(r"/(index|quickreference|directives|module-dict|directive-dict|mpm_common|prefork|worker|event)\.html$|\.[a-z]{2}\.html|/(de|es|fr|ja|ko|tr|zh-cn|pt-br|ru)/", u_ := u)]
    pages += [base + p for p in ("configuring.html", "sections.html", "caching.html", "content-negotiation.html",
                                 "urlmapping.html", "logs.html", "dso.html", "invoking.html", "stopping.html",
                                 "bind.html", "env.html", "filter.html", "handler.html", "location.html", "mpm.html",
                                 "suexec.html", "expr.html", "glossary.html", "install.html", "upgrading.html")]
    seen = set()
    for u in pages:
        if u in seen:
            continue
        seen.add(u)
        try:
            html = fetch(u, 0.5)
        except Exception:
            continue
        pid = unique(used, os.path.splitext(os.path.relpath(urlparse(u).path, "/docs/2.4/"))[0])
        text = convert(html, lambda tag, a: tag == "div" and a.get("id") == "page-content", pid, "apache." + pid, "Apache HTTP Server",
                       skip_ids={"preamble", "quickview", "toplang", "bottomlang"}, skip_classes={"top", "toplang", "bottomlang"})
        write(pid, text)
    print("apache pages", count[0])


def plain_manual(raw, pid, title):
    """HAProxy-style text: numbered section titles underlined with dashes."""
    lines = raw.replace("\r\n", "\n").split("\n")
    head = f"{pid.upper()}(1)"
    pad = max(2, 80 - len(head) * 2 - len("Sandbox manual"))
    out = [f"{head}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{head}", "",
           IND + "NAME", "", IND + f"{pid} - {title}", ""]
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if line and re.match(r"^\d+(\.\d+)*\.?\s+\S", line) and re.fullmatch(r"[-=~]{3,}", nxt):
            h = heading_text(line)
            if out[-1] != "":
                out.append("")
            out += [IND + h, ""]
            i += 2
            continue
        if line == "" and out[-1] == "":
            i += 1
            continue
        out.append(IND + line if line else "")
        i += 1
    return "\n".join(out) + "\n"


def haproxy():
    write, count = writer("haproxy")
    for name, title in (("configuration", "HAProxy configuration manual"), ("management", "HAProxy management guide"),
                        ("intro", "Starter guide")):
        raw = fetch(f"https://raw.githubusercontent.com/haproxy/haproxy/master/doc/{name}.txt", 0.5)
        write(name, plain_manual(raw, "haproxy." + name, title))
    print("haproxy pages", count[0])


def debref():
    write, count = writer("debref")
    base = "https://www.debian.org/doc/manuals/debian-reference/"
    idx = fetch(base, 0.5)
    for u in links(idx, base, base, r"/(?:ch\d+|apa|pr01)\.en\.html$"):
        html = fetch(u, 0.5)
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else u
        pid = re.sub(r"^(?:chapter|appendix)?\s*[A-Z0-9]+\.?\s*", "", title, flags=re.I)
        pid = re.sub(r"^chapter \d+\.\s*", "", pid, flags=re.I)
        name = os.path.basename(urlparse(u).path).split(".")[0]
        pid = f"{name}-{re.sub(r'[^a-z0-9]+', '-', pid.lower()).strip('-')[:40]}"
        text = convert(html, lambda tag, a: tag == "div" and a.get("class") in ("chapter", "appendix", "preface"), title, "debref." + pid,
                       "Debian Reference", skip_classes={"navheader", "navfooter", "toc"})
        write(pid, text)
    print("debref pages", count[0])


def adoc2md(src):
    """AsciiDoc (FreeBSD docs) -> markdown close enough for mdtext."""
    src = re.sub(r"\A---\n.*?\n---\n", "", src, count=1, flags=re.S)
    out = []
    fence = False
    pending_src = False
    for line in src.split("\n"):
        s = line.rstrip()
        if not fence:
            if re.match(r"^(:[\w-]+:.*|(?:ifdef|ifndef|endif|include)::.*|toc::.*|//.*|\[\[[^\]]+\]\]|\[#[^\]]*\]|\[\.[^\]]*\]|\.[A-Za-z].*|image::.*)$", s) \
                    and not s.startswith(".. "):
                if re.match(r"^\.[A-Za-z]", s) and not s.startswith(".."):
                    out.append(f"**{s[1:]}**")
                continue
            if re.match(r"^\[source[^\]]*\]$", s):
                pending_src = True
                continue
            if re.match(r"^\[(NOTE|TIP|WARNING|IMPORTANT|CAUTION)\]$", s):
                out.append("> " + s[1:-1].capitalize() + ":")
                continue
            if s in ("====", "|===") or re.match(r"^\[(cols|options|%header)[^\]]*\]$", s):
                continue
            if s in ("----", "....") or (s == "--"):
                if s == "--":
                    continue
                fence = True
                out.append("```")
                pending_src = False
                continue
            m = re.match(r"^(=+)\s+(.*)$", s)
            if m:
                out.append("#" * len(m.group(1)) + " " + m.group(2))
                continue
            s = re.sub(r"^(NOTE|TIP|WARNING|IMPORTANT|CAUTION):\s+", lambda m: "> " + m.group(1).capitalize() + ": ", s)
            s = re.sub(r"^\s*\.+\s+", "1. ", s)
            s = re.sub(r"^\*{2,}\s+", "  * ", s)
            s = re.sub(r"^\|", "", s)
            s = re.sub(r"\[\.[\w-]+\]#([^#]*)#", r"\1", s)
            s = re.sub(r"\[\.[\w-]+\]\*([^*]*)\*", r"\1", s)
            s = re.sub(r"crossref:[^\[]*\[(?:[^\],]*,)?\s*([^\]]*)\]", r"\1", s)
            s = re.sub(r"(?:link:)?(?:https?://|ftp://)[^\s\[]*\[([^\]]*)\]", r"\1", s)
            s = re.sub(r"man:([\w.+-]+)\[(\d\w*)\](?:\[[^\]]*\])?", r"\1(\2)", s)
            s = re.sub(r"(?:package|port):([\w./+-]+)\[[^\]]*\]", r"\1", s)
            s = re.sub(r"(?:kbd|btn|menu|manref):\[?([^\]]*)\]?", r"\1", s)
            out.append(s)
        else:
            if s in ("----", "...."):
                fence = False
                out.append("```")
            else:
                out.append(s)
    return "\n".join(out)


def freebsd():
    import subprocess
    write, count = writer("freebsd")
    repo = os.path.join(ROOT, ".cache", "freebsd-doc")
    if not os.path.isdir(repo):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/freebsd/freebsd-doc.git", repo], check=True)
    root = "documentation/content/en/books/handbook"
    names = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "HEAD", "--name-only", root], capture_output=True,
                           text=True, check=True).stdout.split()
    import mdtext
    for path in names:
        if not path.endswith("_index.adoc") or path.count("/") < 6:
            continue
        chapter = path.split("/")[-2]
        if chapter in ("bibliography", "pgpkeys", "mirrors", "eresources", "preface"):
            continue
        raw = fetch("https://raw.githubusercontent.com/freebsd/freebsd-doc/main/" + path, 0.3)
        meta, _ = mdtext.parse_front_matter(raw)
        title = meta.get("title") if isinstance(meta.get("title"), str) else chapter
        title = re.sub(r"^Chapter \d+\.\s*", "", title)
        body = adoc2md(raw)
        desc = meta.get("description") if isinstance(meta.get("description"), str) else ""
        text = mdtext.convert(body, "freebsd." + chapter, "FreeBSD Handbook", name_line=f"{title} - {desc}".rstrip(" -"))
        write(chapter, text)
    print("freebsd pages", count[0])


SOURCES = {"nginx": nginx, "apache": apache, "haproxy": haproxy, "debref": debref, "freebsd": freebsd}


def main():
    for name in sys.argv[1:] or list(SOURCES):
        SOURCES[name]()


if __name__ == "__main__":
    main()
