"""Builds docs/tools/: posix.* (POSIX.1-2024 utilities: sed, awk, grep, make, find...), jq, cmake.* (commands) and
vim.* (help files). Needs network; cached in .cache/."""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import IND, convert, heading_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "tools", "man")


def write(topic, pid, text, sub=None):
    d = os.path.join(OUT, sub or topic)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def posix():
    base = "https://pubs.opengroup.org/onlinepubs/9799919799/"
    idx = fetch(base + "idx/utilities.html")
    names = sorted(set(re.findall(r'href="\.\./utilities/([a-z0-9_]+)\.html"', idx)))
    n = 0
    for name in names:
        try:
            html = fetch(f"{base}utilities/{name}.html")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        text = convert(html, lambda tag, a: tag == "body", name, f"posix.{name}", "POSIX",
                       skip_classes={"navheader", "footer", "toc"}, skip_tags={"center"})
        if len(text) < 400:
            continue
        text = re.sub(r"(?m)^( {7})> ", lambda m: m.group(1), text)  # whole pages sit in a blockquote
        text = "\n".join(l for l in text.split("\n") if "<<< Previous" not in l)
        text = re.sub(r"(NAME\n\n {7}[^\n]*?) — ", lambda m: m.group(1) + " - ", text, count=1)
        write("posix", name, text)
        n += 1
    print("posix utilities", n)


def jq():
    html = fetch("https://jqlang.github.io/jq/manual/")
    text = convert(html, lambda tag, a: tag == "main" or (tag == "div" and "content" in (a.get("class") or "").split()),
                   "jq manual", "jq", "jq", skip_classes={"sidebar", "toc"})
    write("jq", "jq", text, sub=".")
    print("jq", len(text))


def cmake():
    base = "https://cmake.org/cmake/help/latest/"
    idx = fetch(base + "manual/cmake-commands.7.html")
    names = sorted(set(re.findall(r'href="\.\./command/([a-z0-9_]+)\.html"', idx)))
    n = 0
    for name in names:
        try:
            html = fetch(f"{base}command/{name}.html")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        text = convert(html, lambda tag, a: tag == "div" and a.get("role") == "main", name, f"cmake.{name}", "CMake",
                       skip_classes={"headerlink", "sphinxsidebar", "related"})
        if len(text) < 300:
            continue
        write("cmake", name.replace("_", "-"), text)
        n += 1
    print("cmake commands", n)


VIM_FILES = ["help", "index", "intro", "quickref", "motion", "change", "insert", "visual", "pattern", "options",
             "windows", "tabpage", "editing", "cmdline", "map", "repeat", "undo", "fold", "diff", "eval", "usr_01",
             "usr_02", "usr_03", "usr_04", "usr_05", "usr_06", "usr_07", "usr_08", "usr_09", "usr_10", "usr_11",
             "usr_12", "usr_20", "usr_21", "usr_22", "usr_23", "usr_24", "usr_25", "usr_26", "usr_27", "usr_28",
             "usr_29", "usr_30", "usr_31", "usr_32", "usr_40", "usr_41", "starting", "term", "syntax", "various",
             "visual", "terminal", "vim9", "autocmd", "gui", "spell", "indent", "scroll", "sponsor"]


def vim_page(name, raw):
    out = []
    h = f"VIM.{name.upper().replace('_', '-')}(1)"
    pad = max(2, 80 - len(h) * 2 - len("Sandbox manual"))
    out += [f"{h}{' ' * (pad // 2)}Sandbox manual{' ' * (pad - pad // 2)}{h}", ""]
    lines = raw.split("\n")
    in_code = False
    para = []

    def clean(s):
        s = re.sub(r"\*[^\s*]+\*", "", s)                # *tags*
        s = re.sub(r"\|([^\s|]+)\|", r"\1", s)           # |links|
        s = re.sub(r"`([^`]*)`", r"\1", s)
        return s.rstrip()

    def flush():
        nonlocal para
        if para:
            out.append(IND + " ".join(p.strip() for p in para))
            out.append("")
            para = []

    first_heading = True
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if i == 1 and line.startswith("*"):
            continue  # modeline header: *file.txt*  For Vim version ...
        if re.fullmatch(r"=+", line.strip() or "x") and len(line.strip()) > 20:
            flush()
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                title = heading_text(re.sub(r"\s+", " ", clean(lines[j]).strip()))
                if title:
                    if out and out[-1] != "":
                        out.append("")
                    out += [IND + title, ""]
                    first_heading = False
                i = j + 1
            continue
        if line.rstrip().endswith(" ~") and line.strip() and not line.startswith(" "):
            flush()
            title = heading_text(clean(line.rstrip(" ~")))
            if title:
                if out and out[-1] != "":
                    out.append("")
                out += [IND + title, ""]
            continue
        if line.rstrip().endswith(">") and re.search(r"\s>$", line.rstrip()) or line.rstrip() == ">":
            body = clean(line.rstrip()[:-1])
            if body.strip():
                para.append(body)
            flush()
            in_code = True
            continue
        if in_code:
            if line.startswith("<") or (line.strip() and not line.startswith((" ", "\t"))):
                in_code = False
                if line.startswith("<"):
                    line = line[1:]
                    if not line.strip():
                        continue
                else:
                    pass
            else:
                out.append(IND + "  " + clean(line).replace("\t", "    ") if line.strip() else "")
                continue
        if not line.strip():
            flush()
            continue
        if line.startswith((" ", "\t")) and re.match(r"\s+[:\w<\[|]", line) and "  " in line.strip():
            flush()
            out.append(IND + "  " + clean(line).strip().replace("\t", "  "))
            continue
        para.append(clean(line))
    flush()
    if first_heading:
        out[2:2] = [IND + heading_text(name), ""]
    while out and out[-1] == "":
        out.pop()
    out += ["", "Vim manual".ljust(40) + "from the Vim help files", ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def vim():
    n = 0
    seen = set()
    for name in VIM_FILES:
        if name in seen:
            continue
        seen.add(name)
        try:
            raw = fetch(f"https://raw.githubusercontent.com/vim/vim/master/runtime/doc/{name}.txt")
        except Exception as e:  # noqa: BLE001
            print("skip", name, e)
            continue
        write("vim", name.replace("_", "-"), vim_page(name, raw))
        n += 1
    print("vim help files", n)


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "tools"), ignore_errors=True)
    os.makedirs(OUT)
    for fn in (posix, jq, cmake, vim):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(fn.__name__, "failed:", e)


if __name__ == "__main__":
    main()
