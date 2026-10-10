"""Builds sysadmin / devops doc packs from documentation repositories (needs git + network; clones into .cache/):

    python tools/import_ops.py                 all of them
    python tools/import_ops.py k8s shellcheck  only these

    shellcheck  ShellCheck wiki (GPL-3): one page per check, sc2086, ...
    prometheus  Prometheus docs (Apache-2.0): PromQL, configuration, alerting
    k8s         Kubernetes docs (CC BY 4.0): concepts, tasks, kubectl, setup
    rocky       Rocky Linux documentation (CC BY-SA 4.0): admin guides and books
    ubuntu      Ubuntu Server documentation (CC BY-SA 3.0): how-to, explanation, reference

Pages are <pack>.<name> (pman k8s pods, pman shellcheck sc2086)."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")

LANG_SUFFIX = re.compile(r"\.[a-z]{2}(?:-[a-z]{2})?\.md$", re.I)


def ensure(name, url, paths):
    d = os.path.join(CACHE, name)
    if not os.path.isdir(d):
        cmd = ["git", "clone", "-q", "--depth", "1"] + (["--filter=blob:none", "--sparse"] if paths else []) + [url, d]
        subprocess.run(cmd, check=True)
    if paths:
        subprocess.run(["git", "-C", d, "sparse-checkout", "set", *paths], check=True)
    return d


# ---- cleaners -------------------------------------------------------------------------------

def clean_common(src):
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"<[a-zA-Z/][^>]*>", "", src) if "<" in src and "```" not in src else src
    return src


def clean_hugo(src, base=None):
    def heading(m):
        return "## " + m.group(1).replace("-", " ").replace("_", " ").capitalize()
    src = re.sub(r'\{\{%\s*heading\s+"([^"]+)"\s*%\}\}', heading, src)
    if base:
        def sample(m):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            path = os.path.join(base, attrs.get("file", ""))
            if not attrs.get("file") or not os.path.isfile(path):
                return ""
            body = open(path, encoding="utf-8", errors="replace").read().strip("\n")
            return f"```{attrs.get('language', 'yaml')}\n{body}\n```"
        src = re.sub(r"\{\{[<%]\s*/?\s*code_sample\s+([^>%]*)[>%]\}\}", sample, src)
    src = re.sub(r'\{\{[<%]\s*glossary_tooltip[^>%]*?text="([^"]*)"[^>%]*[>%]\}\}', r"\1", src)
    src = re.sub(r'\{\{[<%]\s*(?:note|warning|caution|tip)[^>%]*[>%]\}\}', "> Note:", src)
    src = re.sub(r"\{\{[<%].*?[>%]\}\}", "", src, flags=re.S)
    return src


def clean_myst(src):
    def admon(m):
        kind = m.group(1).capitalize()
        body = " ".join(l.strip() for l in m.group(2).strip().split("\n") if l.strip() and not l.startswith(":"))
        return f"> {kind}: {body}\n"
    src = re.sub(r"^(?:```+|:::+)\{(note|warning|tip|important|caution|admonition|hint|seealso)\}[^\n]*\n(.*?)^(?:```+|:::+)\s*$",
                 admon, src, flags=re.S | re.M)
    src = re.sub(r"^```+\{(?:code-block|sourcecode|code)\}\s*(\S*)[^\n]*\n(?::[^\n]*\n)*", lambda m: f"```{m.group(1)}\n", src, flags=re.M)
    src = re.sub(r"^```+\{[a-z-]+\}[^\n]*\n(?::[^\n]*\n)*", "```\n", src, flags=re.M)
    src = re.sub(r"^:::+.*$", "", src, flags=re.M)
    src = re.sub(r"\{(?:ref|doc|term|command|manpage|pkg|kbd|file|samp|guilabel)\}`([^`<]*?)(?:\s*<[^>]*>)?`", r"\1", src)
    src = re.sub(r"^\([\w-]+\)=\s*$", "", src, flags=re.M)
    return src


def clean_mkdocs(src):
    src = re.sub(r'^!!!\s+(\w+)(?:\s+"([^"]*)")?\s*$', lambda m: f"> {(m.group(2) or m.group(1)).strip().capitalize()}:", src, flags=re.M)
    src = re.sub(r'^===\s+"([^"]*)"\s*$', r"\1:", src, flags=re.M)
    src = re.sub(r"^(\s*)\?\?\?\+?\s+(\w+)(?:\s+\"([^\"]*)\")?\s*$", lambda m: f"> {(m.group(3) or m.group(2)).capitalize()}:", src, flags=re.M)
    return src


# ---- sources --------------------------------------------------------------------------------

def md_files(root, accept=lambda rel: True):
    for dirpath, _dirs, files in sorted(os.walk(root)):
        for name in sorted(files):
            if name.endswith(".md") and not LANG_SUFFIX.search(name):
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
                if accept(rel):
                    yield rel, os.path.join(dirpath, name)


def slug(s):
    return re.sub(r"[^a-z0-9_.+-]+", "-", s.lower()).strip("-")


def source_shellcheck():
    d = ensure("shellcheck", "https://github.com/koalaman/shellcheck.wiki.git", None)
    for rel, path in md_files(d, lambda r: "/" not in r and not r.startswith("_") and r.lower() not in ("home.md",)):
        yield slug(rel[:-3]), "ShellCheck", path, clean_common


def source_prometheus():
    d = ensure("prom", "https://github.com/prometheus/docs.git", ["docs"])
    for rel, path in md_files(os.path.join(d, "docs"), lambda r: not re.search(r"(^|/)(_index|index)\.md$|release|changelog|specs/", r)):
        yield slug(rel[:-3].replace("/", "-")), "Prometheus", path, clean_common


def source_k8s():
    d = ensure("k8s", "https://github.com/kubernetes/website.git",
               ["content/en/docs/concepts", "content/en/docs/tasks", "content/en/docs/reference/kubectl",
                "content/en/docs/setup", "content/en/examples"])
    base = os.path.join(d, "content", "en", "examples")
    root = os.path.join(d, "content", "en", "docs")
    for sub in ("concepts", "tasks", "reference/kubectl", "setup"):
        area = sub.split("/")[-1]
        for rel, path in md_files(os.path.join(root, sub)):
            parts = [p for p in rel[:-3].split("/") if p != "_index"]
            if not parts:
                parts = [area]
            name = parts[-1]
            pid = slug(f"{area}-{parts[-2]}-{name}" if len(parts) > 1 and parts[-2] != name else f"{area}-{name}")
            yield pid, "Kubernetes", path, lambda s, base=base: clean_hugo(clean_common(s), base)


def source_rocky():
    d = ensure("rocky", "https://github.com/rocky-linux/documentation.git", ["docs/guides", "docs/books"])
    for sub in ("guides", "books"):
        for rel, path in md_files(os.path.join(d, "docs", sub), lambda r: not r.endswith(("index.md",))):
            yield slug(rel[:-3].replace("/", "-")), "Rocky Linux", path, lambda s: clean_mkdocs(clean_common(s))


def source_ubuntu():
    d = ensure("ubuntu", "https://github.com/canonical/ubuntu-server-documentation.git", ["docs"])
    for rel, path in md_files(os.path.join(d, "docs"), lambda r: not re.search(r"^(_|images|contributing)|index\.md$|release-notes", r)):
        yield slug(rel[:-3].replace("/", "-")), "Ubuntu Server", path, clean_myst


SOURCES = {"shellcheck": source_shellcheck, "prometheus": source_prometheus, "k8s": source_k8s,
           "rocky": source_rocky, "ubuntu": source_ubuntu}


def first_heading(body):
    """First markdown heading outside code fences (a level-1 one wins; wiki pages may start at ##)."""
    fence = False
    best = None
    for l in body.split("\n"):
        if l.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            m = re.match(r"^(#{1,3})\s+(.+?)\s*#*$", l)
            if m:
                if len(m.group(1)) == 1:
                    return m.group(2).strip()
                best = best or m.group(2).strip()
    return best


def build(pack):
    out = os.path.join(ROOT, "docs", pack, "man", pack)
    shutil.rmtree(os.path.join(ROOT, "docs", pack), ignore_errors=True)
    os.makedirs(out)
    used = set()
    n = 0
    for pid, label, path, clean in SOURCES[pack]():
        src = open(path, encoding="utf-8", errors="replace").read()
        meta, body = mdtext.parse_front_matter(src)
        body = clean(body)
        title = first_heading(body)
        if not title:
            t = meta.get("title")
            title = t.strip("\"' ") if isinstance(t, str) and t else pid
        title = re.sub(r"[`*_]", "", title)
        body = re.sub(r"^# .*\n", "", body, count=1, flags=re.M) if body.lstrip().startswith("# ") or "\n# " in body[:400] else body
        first = next((l.strip() for l in body.split("\n") if l.strip() and not l.lstrip().startswith(("#", "|", "```", ">", "-", "*", "!", "{", "<", "["))), "")
        first = re.sub(r"[`*_]", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", first))[:140]
        k, base_pid = 2, pid
        while pid in used or not pid:
            pid = f"{base_pid or 'page'}-{k}"
            k += 1
        used.add(pid)
        text = mdtext.convert(f"# {title}\n\n{body}", f"{pack}.{pid}", label, name_line=f"{title} - {first}".rstrip(" -"))
        if len(text) < 350:
            used.discard(pid)
            continue
        with open(os.path.join(out, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print(pack, "pages", n)


def main():
    want = sys.argv[1:] or list(SOURCES)
    for pack in want:
        build(pack)


if __name__ == "__main__":
    main()
