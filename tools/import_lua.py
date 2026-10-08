"""Builds docs/lua/ from the Lua 5.4 reference manual (lua.org). One page, `lua`."""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "lua", "man")


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "lua"), ignore_errors=True)
    os.makedirs(OUT)
    html = fetch("https://www.lua.org/manual/5.4/manual.html")
    text = convert(html, lambda tag, a: tag == "body", "Lua 5.4 Reference Manual", "lua", "Lua",
                   skip_classes={"footer"}, dt_headings=False)
    with open(os.path.join(OUT, "lua.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("lua", len(text))


if __name__ == "__main__":
    main()
