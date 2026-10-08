"""Builds docs/web/ from mdn/content (CC BY-SA 2.5): JavaScript reference + guide, CSS reference, HTML
reference. Pages: js.*, css.*, html.*  Needs git + network (sparse clone into .cache/mdn)."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(ROOT, ".cache", "mdn")
WEB = os.path.join(REPO, "files", "en-us", "web")
OUT = os.path.join(ROOT, "docs", "web", "man")

PATHS = ["files/en-us/web/javascript/reference", "files/en-us/web/javascript/guide",
         "files/en-us/web/css", "files/en-us/web/html"]


def ensure_repo():
    if not os.path.isdir(REPO):
        os.makedirs(os.path.dirname(REPO), exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/mdn/content.git", REPO], check=True)
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "set", *PATHS], check=True)


MACRO = re.compile(r"\{\{\s*([A-Za-z_]+)\s*(?:\((.*?)\))?\s*\}\}")
DROP = {"compat", "specifications", "interactiveexample", "jsref", "seecompattable", "csssyntax", "cssinfo",
        "previous", "next", "previousnext", "previousmenunext", "apiref", "defaultapisidebar", "htmlsidebar",
        "cssref", "jssidebar", "glossarysidebar", "embedinteractiveexample", "embedlivesample", "domxsidebar"}
FLAGS = {"optional_inline": "(optional)", "deprecated_inline": "(deprecated)", "non-standard_inline": "(non-standard)",
         "experimental_inline": "(experimental)", "readonlyinline": "(read-only)", "securecontext_inline": ""}


def macro(m):
    name = m.group(1).lower()
    args = m.group(2) or ""
    if name in FLAGS:
        return FLAGS[name]
    if name in DROP:
        return ""
    parts = re.findall(r'"([^"]*)"|\'([^\']*)\'', args)
    strings = [a or b for a, b in parts]
    if not strings:
        return ""
    if name == "htmlelement":
        return f"<{strings[0]}>"
    text = strings[1] if len(strings) > 1 and strings[1] else strings[0]
    return text.split("/")[-1] if name in ("jsxref", "domxref") and len(strings) == 1 else text


def clean(src):
    out = []
    in_code = False
    for line in src.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        out.append(line if in_code else MACRO.sub(macro, line))
    return "\n".join(out)


def slug(s):
    s = s.replace("_colon_", "").replace("_doublecolon_", "").replace("_at-", "at-")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def page_id(rel):
    """rel: path of the page directory relative to web/, e.g. javascript/reference/global_objects/array/map"""
    parts = rel.split("/")
    top = parts[0]
    if top == "javascript":
        sub = parts[1:]
        if sub[0] == "guide":
            return "js", "guide-" + slug("-".join(sub[1:]) or "index")
        sect = sub[1] if len(sub) > 1 else ""
        rest = sub[2:]
        name = slug("-".join(rest))
        if sect == "global_objects":
            return "js", name
        if sect == "errors":
            return "js", "error-" + name
        return "js", name, sect
    if top == "css":
        sub = parts[1:]
        if sub[0] == "reference" and len(sub) > 2:
            sect, rest = sub[1], "-".join(sub[2:])
            n = slug(rest)
            prefix = {"properties": "", "selectors": "selector-", "at-rules": "", "values": "value-"}.get(sect, sect + "-")
            return "css", prefix + n
        return "css", "guide-" + slug("-".join(sub[1:]) or "index")
    if top == "html":
        sub = parts[1:]
        if sub[0] == "reference" and len(sub) > 2:
            sect, rest = sub[1], "-".join(sub[2:])
            prefix = {"elements": "", "attributes": "attr-", "global_attributes": "global-"}.get(sect, sect + "-")
            return "html", prefix + slug(rest)
        return "html", "guide-" + slug("-".join(sub[1:]) or "index")
    return top, slug("-".join(parts[1:]))


def main():
    ensure_repo()
    shutil.rmtree(os.path.join(ROOT, "docs", "web"), ignore_errors=True)
    used = {"js": set(), "css": set(), "html": set()}
    pages = []
    for base, _dirs, files in os.walk(WEB):
        if "index.md" not in files:
            continue
        rel = os.path.relpath(base, WEB).replace(os.sep, "/")
        if rel in ("javascript", "css", "html", "javascript/reference", "javascript/guide"):
            continue
        pages.append(rel)
    # global objects first so statements/operators fall back to a prefixed id on collision
    pages.sort(key=lambda r: (0 if "global_objects" in r else 1, r))
    n = 0
    for rel in pages:
        info = page_id(rel)
        topic, pid = info[0], info[1]
        if not pid or topic not in used:
            continue
        if pid in used[topic] and len(info) > 2:
            pid = slug(info[2]) + "-" + pid
        k = 2
        base_pid = pid
        while pid in used[topic]:
            pid = f"{base_pid}-{k}"
            k += 1
        used[topic].add(pid)
        src = open(os.path.join(WEB, rel, "index.md"), encoding="utf-8", errors="replace").read()
        meta, body = mdtext.parse_front_matter(src)
        title = meta.get("title") if isinstance(meta.get("title"), str) else pid
        title = clean(title).strip("\"'")
        body = clean(body)
        syn = re.search(r"\n\s*\n([^\n#`{][^\n]*)", "\n\n" + body.lstrip())
        synopsis = re.sub(r"[`*_]", "", syn.group(1)).strip() if syn else ""
        synopsis = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", synopsis)
        name_line = f"{title} - {synopsis[:140]}" if synopsis else title
        page_src = f"# {title}\n\n{body}"
        text = mdtext.convert(page_src, f"{topic}.{pid}", {"js": "JavaScript", "css": "CSS", "html": "HTML"}[topic],
                              name_line=name_line)
        d = os.path.join(OUT, topic)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("web pages", n, {k: len(v) for k, v in used.items()})


if __name__ == "__main__":
    main()
