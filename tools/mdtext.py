"""Markdown -> pman page text (stdlib only), for docs published as markdown (PowerShell-Docs)."""
import re

from htmltext import IND, heading_text


def parse_front_matter(src):
    """Returns (meta dict with scalar and list values, body)."""
    meta = {}
    if not src.startswith("---"):
        return meta, src
    end = src.find("\n---", 3)
    if end < 0:
        return meta, src
    key = None
    for line in src[3:end].split("\n"):
        if re.match(r"^\s+-\s+", line) and key:
            meta.setdefault(key, []).append(re.sub(r"^\s+-\s+", "", line).strip())
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            meta[key] = val if val else []
    return meta, src[end + 4:].lstrip("\n")


def inline(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                # images
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)            # links -> text
    s = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", s)           # reference links
    s = re.sub(r"<!--.*?-->", "", s)
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)                   # stray html tags
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
    s = s.replace("`", "")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def convert(src, pid, label, title=None, name_line=None):
    meta, body = parse_front_matter(src)
    out = []
    h = f"{pid.upper()}(1)"
    pad = max(2, 80 - len(h) * 2 - len("Sandbox manual"))
    out.append(f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}")
    out.append("")
    if name_line:
        out += [IND + "NAME", "", IND + name_line, ""]
    lines = body.split("\n")
    para = []
    in_code = False
    in_html_comment = False

    def flush_para():
        nonlocal para
        if para:
            out.append(IND + inline(" ".join(para)))
            out.append("")
            para = []

    def blank():
        if out and out[-1] != "":
            out.append("")

    for raw in lines:
        line = raw.rstrip()
        if in_html_comment:
            if "-->" in line:
                in_html_comment = False
            continue
        if line.lstrip().startswith("<!--") and "-->" not in line:
            in_html_comment = True
            continue
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            flush_para()
            if not in_code:
                blank()
            in_code = not in_code
            if not in_code:
                blank()
            continue
        if in_code:
            out.append(IND + "  " + line if line.strip() else "")
            continue
        s = line.strip()
        if not s:
            flush_para()
            continue
        if s.startswith(":::") or re.match(r"^\[!\w+\]", s):
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_para()
            level = len(m.group(1))
            text = inline(m.group(2))
            t = heading_text(text)
            blank()
            out.append(IND + (t if t else text))
            out.append("")
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush_para()
            depth = len(m.group(1)) // 2
            bullet = "*" if m.group(2) in "-*+" else m.group(2)
            out.append(IND + " " + "  " * depth + bullet + " " + inline(m.group(3)))
            continue
        if s.startswith("|"):
            flush_para()
            cells = [inline(c) for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) or not c for c in cells) and any(cells):
                continue
            out.append(IND + "  " + "  |  ".join(c for c in cells if c))
            continue
        if s.startswith(">"):
            flush_para()
            q = inline(s.lstrip("> ").strip())
            if q and not q.startswith("[!"):
                out.append(IND + "> " + q)
            continue
        para.append(s)
    flush_para()
    while out and out[-1] == "":
        out.pop()
    out += ["", f"{label} manual".ljust(40) + "from the official documentation", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))
