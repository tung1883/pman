"""HTML -> pman page text (stdlib only).

Pages use the man-style layout pman parses: a header line, then headings as 7-space-indented
CAPS lines with blank lines around, paragraphs at 7 spaces, code at 9, bullets as `* text`.
"""
import re
import unicodedata
from html.parser import HTMLParser

IND = " " * 7
VOID = {"br", "hr", "img", "meta", "link", "input", "wbr", "source", "col", "area", "base"}
ALWAYS_SKIP = {"script", "style", "head", "title", "nav", "svg", "button", "noscript", "template"}
HEADING_OK = re.compile(r"[^A-Z0-9 ,&'()./:_+#-]")


def heading_text(s):
    """Fold to ASCII caps in the character set pman accepts for headings."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").upper()
    s = HEADING_OK.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -.,:/")
    return s[:70].rstrip(" -.,:/") if len(s) > 70 else s


class Converter(HTMLParser):
    def __init__(self, capture, skip_classes=(), skip_ids=(), skip_tags=(), dt_headings=False):
        super().__init__(convert_charrefs=True)
        self.dt_headings = dt_headings
        self.capture = capture          # callable(tag, attrs) -> bool: starts the content region
        self.skip_classes = set(skip_classes)
        self.skip_ids = set(skip_ids)
        self.skip_tags = ALWAYS_SKIP | set(skip_tags)
        self.cap_tag = None
        self.cap_depth = 0
        self.skip_tag = None
        self.skip_depth = 0
        self.blocks = []                # (kind, text, depth)
        self.kind = None
        self.buf = []
        self.in_pre = False
        self.list_depth = 0
        self.quote = 0
        self.row = None
        self.pre_depth_marker = 0

    # -- region tracking -------------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.cap_tag is None:
            if self.capture(tag, a):
                self.cap_tag, self.cap_depth = tag, 1
            return
        if tag == self.cap_tag and tag not in VOID:
            self.cap_depth += 1
        if self.skip_tag is not None:
            if tag == self.skip_tag and tag not in VOID:
                self.skip_depth += 1
            return
        classes = set((a.get("class") or "").split())
        if tag in self.skip_tags or classes & self.skip_classes or a.get("id") in self.skip_ids \
                or a.get("aria-hidden") == "true" or a.get("hidden") is not None:
            if tag not in VOID:
                self.skip_tag, self.skip_depth = tag, 1
            return
        self.start(tag, a, classes)

    def handle_startendtag(self, tag, attrs):
        if self.cap_tag is not None and self.skip_tag is None:
            self.start(tag, dict(attrs), set())

    def handle_endtag(self, tag):
        if self.cap_tag is None:
            return
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            if tag == self.cap_tag:
                self.cap_depth -= 1
            return
        self.end(tag)
        if tag == self.cap_tag:
            self.cap_depth -= 1
            if self.cap_depth == 0:
                self.flush()
                self.cap_tag = None

    def handle_data(self, data):
        if self.cap_tag is None or self.skip_tag is not None:
            return
        if self.in_pre:
            self.buf.append(data)
        else:
            self.buf.append(re.sub(r"\s+", " ", data))

    # -- structure -------------------------------------------------------------------------------
    def start(self, tag, a, classes):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.flush()
            self.kind = "h"
        elif tag == "p":
            if self.kind not in ("li", "dd"):
                self.flush()
                self.kind = "p"
            else:
                self.buf.append(" ")
        elif tag == "pre":
            self.flush()
            self.kind = "pre"
            self.in_pre = True
        elif tag in ("ul", "ol"):
            self.flush()
            self.list_depth += 1
        elif tag == "li":
            self.flush()
            self.kind = "li"
        elif tag == "blockquote":
            self.flush()
            self.quote += 1
        elif tag == "dt":
            self.flush()
            self.kind = "dt"
        elif tag == "dd":
            self.flush()
            self.kind = "dd"
        elif tag == "tr":
            self.flush()
            self.row = []
            self.kind = "row"
        elif tag in ("td", "th"):
            if self.row is not None:
                self.row.append("".join(self.buf).strip())
                self.buf = []
        elif tag == "br":
            self.buf.append("\n" if self.in_pre else " ")
        elif tag in ("div", "section", "details", "summary", "table", "figure", "tbody", "thead"):
            if self.kind in (None, "p", "h"):
                self.flush()

    def end(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "tr"):
            if tag == "tr" and self.row is not None:
                self.row.append("".join(self.buf).strip())
                self.buf = [" | ".join(c for c in self.row if c)]
                self.row = None
            self.flush()
        elif tag == "pre":
            self.flush()
            self.in_pre = False
        elif tag in ("ul", "ol"):
            self.flush()
            self.list_depth = max(0, self.list_depth - 1)
        elif tag == "blockquote":
            self.flush()
            self.quote = max(0, self.quote - 1)
        elif tag in ("div", "section", "details", "summary", "table"):
            if self.kind in (None, "p"):
                self.flush()

    def flush(self):
        text = "".join(self.buf)
        self.buf = []
        kind = self.kind
        if kind == "dt" and self.dt_headings and re.match(r"[A-Za-z]", text.strip() or "-"):
            kind = "h"  # texinfo @deffn entries (builtins, variables): jumpable sections
        if kind != "pre":
            text = text.strip()
            self.kind = None
        else:
            text = text.strip("\n")
            self.kind = None
        if not text.strip():
            return
        if kind is None:
            kind = "p"
        self.blocks.append((kind, text, self.list_depth, self.quote))

    # -- output ----------------------------------------------------------------------------------
    def render(self, title, pid, topic_label):
        out = []
        h = f"{pid.upper()}(1)"
        pad = max(2, 80 - len(h) * 2 - len("Sandbox manual"))
        out.append(f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}")
        out.append("")
        first = True
        for kind, text, depth, quote in self.blocks:
            if kind == "h":
                t = heading_text(text)
                if not t:
                    out.append(IND + text)
                    out.append("")
                    continue
                if out and out[-1] != "":
                    out.append("")
                out.append(IND + t)
                out.append("")
                first = False
            elif kind == "pre":
                if out and out[-1] != "":
                    out.append("")
                for line in text.split("\n"):
                    out.append(IND + "  " + line.rstrip() if line.strip() else "")
                out.append("")
            elif kind == "li":
                out.append(IND + "  " * max(0, depth - 1) + " * " + text)
            elif kind in ("row", "dt"):
                out.append(IND + "  " + text)
            else:
                if quote:
                    out.append(IND + "> " + text)
                else:
                    out.append(IND + text)
                out.append("")
        if first:  # no heading at all: lead with the page title
            t = heading_text(title) or heading_text(pid)
            out[2:2] = [IND + t, ""]
        while out and out[-1] == "":
            out.pop()
        out += ["", f"{topic_label} manual".ljust(40) + "bundled documentation", ""]
        # collapse blank runs
        text = "\n".join(out)
        return re.sub(r"\n{3,}", "\n\n", text)


def convert(html, capture, title, pid, label, **kw):
    c = Converter(capture, **kw)
    c.feed(html)
    c.close()
    c.flush()
    return c.render(title, pid, label)
