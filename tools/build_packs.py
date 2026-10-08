"""Builds doc packs from docs/<id>/ into dist/<id>.zip and writes dist/registry.json.

    python tools/build_packs.py                  build only
    python tools/build_packs.py --publish        also create/update the GitHub release `latest` (gh)

Each pack folder holds `man/` in the layout pman scans: man/js.txt is page `js`,
man/ts/classes.txt is page `ts.classes`. Bump VERSIONS when a pack's content changes.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DIST = os.path.join(ROOT, "dist")

PACKS = {
    "c":  {"version": 1, "topics": ["c"],       "desc": "C language reference, libc and POSIX function pages, tcc manual"},
    "js": {"version": 1, "topics": ["js", "ts"], "desc": "JavaScript (QuickJS) and the TypeScript handbook"},
    "py": {"version": 1, "topics": ["py"],      "desc": "Python 3.12 builtins, common modules, syntax cheat sheet"},
    "rust":  {"version": 1, "topics": ["rust"],  "desc": "Rust book, reference, Cargo book, Rust by Example, Nomicon, error codes"},
    "go":    {"version": 1, "topics": ["go"],    "desc": "Go spec, Effective Go, FAQ, memory model, common std packages"},
    "zig":   {"version": 2, "topics": ["zig"],   "desc": "Zig 0.15 language reference, one page per chapter"},
    "bash":  {"version": 1, "topics": ["bash"],  "desc": "bash(1) man page and the Bash Reference Manual (builtins, expansions, scripting)"},
    "powershell": {"version": 2, "topics": ["powershell"], "desc": "PowerShell docs (7.5 online reference) plus Get-Help for Windows PowerShell 5.1 and 7 modules (NetTCPIP, Storage, ...)"},
    "cmd":    {"version": 1, "topics": ["cmd"],    "desc": "tldr-pages: ~6700 command-line tools with practical examples (grep, tar, git, curl, ssh, docker...)"},
    "git":    {"version": 1, "topics": ["git"],    "desc": "Git command reference, guides and the Pro Git book"},
    "web":    {"version": 1, "topics": ["js", "css", "html"], "desc": "MDN: JavaScript reference and guide, CSS reference, HTML elements and attributes"},
    "sql":    {"version": 1, "topics": ["sqlite", "pg"], "desc": "SQLite and PostgreSQL documentation (SQL commands, functions, data types)"},
    "java":   {"version": 1, "topics": ["java"],   "desc": "Java Language Specification, SE 21"},
    "kotlin": {"version": 1, "topics": ["kotlin"], "desc": "Kotlin language and tooling documentation"},
    "ruby":   {"version": 1, "topics": ["ruby"],   "desc": "Ruby 3.4 core classes"},
    "lua":    {"version": 1, "topics": ["lua"],    "desc": "Lua 5.4 reference manual"},
    "php":    {"version": 1, "topics": ["php"],    "desc": "PHP manual: language reference, core functions and classes"},
    "cpp":    {"version": 1, "topics": ["cpp"],    "desc": "cppreference: C++ library and language reference"},
    "tools":  {"version": 1, "topics": ["posix", "jq", "cmake", "vim"], "desc": "POSIX utilities (sed, awk, make, grep...), jq, CMake commands, Vim help"},
    "linux": {"version": 3, "topics": ["linux"], "desc": "Linux man pages: commands (coreutils, util-linux, systemd, ...), system calls, libc, file formats, overviews"},
}


def build(pid):
    src = os.path.join(DOCS, pid)
    out = os.path.join(DIST, pid + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _dirs, files in os.walk(src):
            for f in sorted(files):
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, src).replace(os.sep, "/"))
    data = open(out, "rb").read()
    return out, len(data), hashlib.sha256(data).hexdigest()


def main():
    os.makedirs(DIST, exist_ok=True)
    reg = {"packs": {}}
    files = []
    for pid, meta in PACKS.items():
        out, size, sha = build(pid)
        files.append(out)
        reg["packs"][pid] = {"version": meta["version"], "url": pid + ".zip", "sha256": sha,
                             "size": size, "topics": meta["topics"], "desc": meta["desc"]}
        print(f"{pid}: {size} bytes {sha[:12]}")
    reg_path = os.path.join(DIST, "registry.json")
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)
    files.append(reg_path)
    if "--publish" in sys.argv:
        # `latest` release holds the current registry plus the zips it points to (relative urls).
        have = subprocess.run(["gh", "release", "view", "latest"], capture_output=True).returncode == 0
        if have:
            subprocess.run(["gh", "release", "upload", "latest", *files, "--clobber"], check=True)
        else:
            subprocess.run(["gh", "release", "create", "latest", *files, "--title", "Doc packs",
                            "--notes", "Registry and doc packs for pman."], check=True)


if __name__ == "__main__":
    main()
