"""Linux man-pages (troff) -> pman page text. Used by import_linux.py."""
import re
import shlex

IND = " " * 7

CHARS = {"aq": "'", "dq": '"', "em": "--", "en": "-", "lq": '"', "rq": '"', "oq": "`", "cq": "'", "co": "(c)",
         "ti": "~", "bu": "*", "->": "->", "<-": "<-", "ha": "^", "ga": "`", "ba": "|", "rs": "\\", "sl": "/",
         "lB": "[", "rB": "]", "lC": "{", "rC": "}", "mu": "x", "di": "/", "pl": "+", "mi": "-", "eq": "=",
         "**": "*", "ge": ">=", "le": "<=", "!=": "!=", "if": "inf", "*": "*", "dg": "+", "Fi": ">>", "Fo": "<<",
         "aa": "'", "sc": "S", "de": "deg", "+-": "+-", "pi": "pi", "~~": "~", "sr": "sqrt", "ap": "~", "ul": "_"}


def esc(s):
    s = s.replace("\\\\", "\x00")
    s = re.sub(r"\\f(\[[^\]]*\]|\(..|.)", "", s)
    s = re.sub(r"\\\*\[[^\]]*\]|\\\*\(..|\\\*.", "", s)
    s = re.sub(r"\\s[+-]?\d+", "", s)
    s = re.sub(r"\\\[u([0-9A-Fa-f]{4,6})\]", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"\\\[([^\]]+)\]", lambda m: CHARS.get(m.group(1), ""), s)
    s = re.sub(r"\\\((..)", lambda m: CHARS.get(m.group(1), ""), s)
    s = s.replace("\\e", "\x01").replace("\\-", "-").replace("\\ ", " ").replace("\\~", " ").replace("\\0", " ")
    s = re.sub(r"\\[&|^%:c,/]", "", s)
    s = re.sub(r"\\[a-zA-Z]", "", s)
    s = s.replace("\x00", "\\").replace("\x01", "\\")
    return s


def args(line):
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.split()


def convert(text, name, sec, label="Linux"):
    raw = text.split("\n")
    out = []
    st = {"buf": [], "nofill": False, "tag": None, "skip": False}
    table = None
    DROP = {"LIBRARY", "HISTORY", "COLOPHON"}

    def flush():
        if st["buf"]:
            if not st["skip"]:
                out.append(IND + " ".join(st["buf"]))
            st["buf"] = []

    def blank():
        if not st["skip"] and out and out[-1] != "":
            out.append("")

    def verbatim(t):
        if not st["skip"]:
            out.append(IND + "  " + t.rstrip() if t.strip() else "")

    def text(t):
        if st.get("bullet") and t.strip():
            flush()
            st["buf"] = [" *", t.strip()]  # following source lines of the item join this bullet
            st["bullet"] = False
            return
        if st["tag"]:
            flush()
            if st["tag"] == "blank":
                blank()
            verbatim(t.strip())
            st["tag"] = None
            return
        if st["nofill"]:
            verbatim(t)
        elif t.strip():
            st["buf"].append(t.strip())
        else:
            flush()
            blank()

    i = 0
    while i < len(raw):
        line = raw[i]
        i += 1
        if line.startswith("'\\\"") or line.startswith(".\\\"") or line.startswith("\\\""):
            continue
        if table is not None:
            if line.startswith(".TE"):
                table = None
                blank()
                continue
            if table == "fmt":
                if line.rstrip().endswith("."):
                    table = "rows"
                continue
            row = line
            if "T{" in row:
                while "T}" not in row and i < len(raw):
                    row += " " + raw[i]
                    i += 1
                row = row.replace("T{", "").replace("T}", "")
            row = esc(row)
            if row.strip() and set(row.strip()) <= set("_="):
                continue
            verbatim("  ".join(c.strip() for c in row.split("\t")))
            continue
        if line.startswith(".") or line.startswith("'"):
            m = re.match(r"[.'][ \t]*(\S+)[ \t]*(.*)", line)
            if not m:
                continue
            mac, rest = m.group(1), m.group(2)
            a = [esc(x) for x in args(rest)]
            if mac in ("SH", "SS"):
                flush()
                if a:
                    title = " ".join(a)
                else:
                    title = esc(raw[i].strip())
                    i += 1
                title = title.upper()
                if mac == "SH":
                    st["skip"] = title in DROP
                st["nofill"] = False
                blank()
                if not st["skip"]:
                    out.append(IND + title)
                    out.append("")
            elif mac in ("P", "PP", "LP"):
                flush()
                blank()
                st["tag"] = None
            elif mac in ("TP", "TQ"):
                flush()
                st["tag"] = "blank" if mac == "TP" else "noblank"
            elif mac == "IP":
                flush()
                blank()
                if a and a[0] in ("[bu]", "bu", "•", "*", "-"):
                    st["bullet"] = True
                elif a:
                    verbatim(a[0])
            elif mac in ("nf", "EX"):
                flush()
                st["nofill"] = True
            elif mac in ("fi", "EE"):
                st["nofill"] = False
            elif mac == "br":
                flush()
            elif mac == "sp":
                flush()
                blank()
            elif mac == "TS":
                flush()
                blank()
                table = "fmt"
            elif mac in ("B", "I", "SM", "SB", "BR", "IR", "RI", "RB", "BI", "IB"):
                if not a and i < len(raw):
                    a = [esc(raw[i].strip())]
                    i += 1
                text(" ".join(a) if mac in ("B", "I", "SM", "SB") else "".join(a))
        else:
            text(esc(line))
    flush()
    while out and out[-1] == "":
        out.pop()
    h = f"{name.upper()}({sec})"
    pad = 80 - len(h) * 2 - len("Sandbox manual")
    head = f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}"
    return "\n".join([head, ""] + out + ["", f"{label} manual".ljust(40) + "from the Linux man-pages project", ""])


