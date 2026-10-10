"""Builds doc packs from docs/<id>/ into dist/<id>.zip and writes dist/registry.json.

    python tools/build_packs.py                  build every pack in PACKS
    python tools/build_packs.py --only c,js       build only these
    python tools/build_packs.py --changed-only    build every pack, but bump the version and upload
                                                   only the ones whose zip sha256 changed from the
                                                   live registry (dist/registry.json, or the release
                                                   one when --publish is also given)
    python tools/build_packs.py --publish         create/update the GitHub release `latest` (gh);
                                                   with --changed-only, uploads only changed files

Each pack folder holds `man/` in the layout pman scans: man/js.txt is page `js`,
man/ts/classes.txt is page `ts.classes`. Versions live in tools/versions.json, not here, and are
bumped automatically by --changed-only; PACKS only has topics/desc/group.

docs/<pack>/meta.json (written by tools/meta.py, by an importer) carries source/upstream_version/
fetched/license; its fields are copied into the registry entry and the file ships inside the zip.
A pack with no license (own meta.json, or inherited from PACKS below) is only warned about, not
rejected -- most importers predate item 6 and do not write one yet.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meta as meta_mod  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DIST = os.path.join(ROOT, "dist")
VERSIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "versions.json")

# id -> {topics, desc, group?}. Never w3s (personal-only, never built here).
PACKS = {
    "c":  {"topics": ["c"],       "desc": "C language reference, libc and POSIX function pages, tcc manual", "group": "systems"},
    "js": {"topics": ["js", "ts"], "desc": "JavaScript (QuickJS) and the TypeScript handbook", "group": "frontend"},
    "py": {"topics": ["py"],      "desc": "Python 3.12 builtins, common modules, syntax cheat sheet", "group": "pyall"},
    "rust":  {"topics": ["rust"],  "desc": "Rust book, reference, Cargo book, Rust by Example, Nomicon, error codes", "group": "systems"},
    "go":    {"topics": ["go"],    "desc": "Go spec, Effective Go, FAQ, memory model, common std packages", "group": "systems"},
    "zig":   {"topics": ["zig"],   "desc": "Zig 0.15 language reference, one page per chapter"},
    "bash":  {"topics": ["bash"],  "desc": "bash(1) man page and the Bash Reference Manual (builtins, expansions, scripting)", "group": "scripting"},
    "powershell": {"topics": ["powershell"], "desc": "PowerShell docs (7.5 online reference) plus Get-Help for Windows PowerShell 5.1 and 7 modules (NetTCPIP, Storage, ...)", "group": "scripting"},
    "cmd":    {"topics": ["cmd"],    "desc": "tldr-pages: ~6700 command-line tools with practical examples (grep, tar, git, curl, ssh, docker...)", "group": "devops"},
    "git":    {"topics": ["git"],    "desc": "Git command reference, guides and the Pro Git book"},
    "web":    {"topics": ["js", "css", "html"], "desc": "MDN: JavaScript reference and guide, CSS reference, HTML elements and attributes", "group": "frontend"},
    "sql":    {"topics": ["sqlite", "pg"], "desc": "SQLite and PostgreSQL documentation (SQL commands, functions, data types)", "group": "data"},
    "java":   {"topics": ["java"],   "desc": "Java Language Specification, SE 21", "group": "dotnet-jvm"},
    "kotlin": {"topics": ["kotlin"], "desc": "Kotlin language and tooling documentation", "group": "dotnet-jvm"},
    "ruby":   {"topics": ["ruby"],   "desc": "Ruby 3.4 core classes"},
    "python": {"topics": ["python"], "desc": "Python 3.12 official documentation: standard library, tutorial, language reference, HOWTOs", "group": "pyall"},
    "webapi": {"topics": ["webapi", "http"], "desc": "MDN Web APIs (DOM, fetch, Storage, Canvas, ...) and HTTP (headers, methods, status codes)", "group": "frontend"},
    "gnu": {"topics": ["gnu"], "desc": "GNU manuals: coreutils, sed, grep, find, diffutils, binutils (as, ld), gawk, make, gdb, gcc", "group": "devops"},
    "docker": {"topics": ["docker"], "desc": "Docker CLI, Dockerfile and Compose file reference, engine, build and compose guides", "group": "devops"},
    "csharp": {"topics": ["csharp"], "desc": "C# language reference, fundamentals, programming guide, LINQ and async", "group": "dotnet-jvm"},
    "arch": {"topics": ["arch"], "desc": "ArchWiki: selected sysadmin pages (systemd, networking, storage, security, servers, containers)", "group": "devops"},
    "k8s": {"topics": ["k8s"], "desc": "Kubernetes documentation: concepts, tasks, kubectl, setup", "group": "devops"},
    "prometheus": {"topics": ["prometheus"], "desc": "Prometheus: PromQL, configuration, alerting, instrumentation", "group": "devops"},
    "shellcheck": {"topics": ["shellcheck"], "desc": "ShellCheck wiki: one page per check (sc2086, ...) with problem and correct code", "group": "devops"},
    "rocky": {"topics": ["rocky"], "desc": "Rocky Linux documentation: administration guides and books", "group": "devops"},
    "ubuntu": {"topics": ["ubuntu"], "desc": "Ubuntu Server documentation: how-to guides, explanation, reference", "group": "devops"},
    "nginx": {"topics": ["nginx"], "desc": "nginx documentation: guides, modules and directive reference", "group": "devops"},
    "apache": {"topics": ["apache"], "desc": "Apache HTTP Server 2.4 manual: modules, directives, programs, how-tos", "group": "devops"},
    "haproxy": {"topics": ["haproxy"], "desc": "HAProxy configuration manual, management guide and starter guide", "group": "devops"},
    "debref": {"topics": ["debref"], "desc": "Debian Reference: packages, networking, system tips, data management", "group": "devops"},
    "freebsd": {"topics": ["freebsd"], "desc": "FreeBSD Handbook: install, ZFS, jails, firewalls, networking, security", "group": "devops"},
    "node":   {"topics": ["node"],   "desc": "Node.js API documentation (fs, http, path, streams, ...)", "group": "frontend"},
    "lua":    {"topics": ["lua"],    "desc": "Lua 5.4 reference manual"},
    "php":    {"topics": ["php"],    "desc": "PHP manual: language reference, core functions and classes", "group": "frontend"},
    "cpp":    {"topics": ["cpp"],    "desc": "cppreference: C++ library and language reference", "group": "systems"},
    "tools":  {"topics": ["posix", "jq", "cmake", "vim"], "desc": "POSIX utilities (sed, awk, make, grep...), jq, CMake commands, Vim help"},
    "linux": {"topics": ["linux"], "desc": "Linux man pages: commands (coreutils, util-linux, systemd, ...), system calls, libc, file formats, overviews", "group": "systems"},
}

GROUPS = {
    "devops": {"desc": "Infrastructure, containers and sysadmin docs", "packs": ["docker", "k8s", "nginx", "apache", "haproxy", "prometheus", "shellcheck", "arch", "rocky", "ubuntu", "debref", "freebsd", "gnu", "linux", "cmd", "bash"]},
    "frontend": {"desc": "Browser, HTTP and web runtimes", "packs": ["web", "webapi", "node", "js", "php"]},
    "systems": {"desc": "Systems languages", "packs": ["c", "cpp", "rust", "go", "gnu", "linux"]},
    "pyall": {"desc": "Python", "packs": ["py", "python"]},
    "dotnet-jvm": {"desc": ".NET and JVM languages", "packs": ["csharp", "java", "kotlin"]},
    "scripting": {"desc": "Shell scripting", "packs": ["lua", "ruby", "powershell", "bash"]},
    "data": {"desc": "Databases", "packs": ["sql"]},
}


def check_groups():
    all_topics = {t for m in PACKS.values() for t in m["topics"]}
    for gid, g in GROUPS.items():
        if gid in PACKS or gid in all_topics:
            raise SystemExit(f"group id '{gid}' collides with a pack id or topic")
        for pid in g["packs"]:
            if pid not in PACKS:
                raise SystemExit(f"group '{gid}' references unknown pack '{pid}'")


def load_versions():
    if os.path.exists(VERSIONS_PATH):
        with open(VERSIONS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_versions(versions):
    with open(VERSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(versions, f, indent=2, sort_keys=True)


def build(pid):
    """Deterministic zip: sorted entries, fixed mtime/compression -> stable sha256 for unchanged content."""
    src = os.path.join(DOCS, pid)
    out = os.path.join(DIST, pid + ".zip")
    entries = []
    for base, _dirs, files in os.walk(src):
        for f in files:
            full = os.path.join(base, f)
            entries.append((os.path.relpath(full, src).replace(os.sep, "/"), full))
    entries.sort(key=lambda e: e[0])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in entries:
            info = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as fh:
                z.writestr(info, fh.read())
    data = open(out, "rb").read()
    return out, len(data), hashlib.sha256(data).hexdigest()


def live_registry():
    """The registry to diff against for --changed-only: a freshly built dist/registry.json, or (if
    missing) the published `latest` release, via `gh release download`."""
    path = os.path.join(DIST, "registry.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    try:
        out = subprocess.run(["gh", "release", "view", "latest", "--json", "assets"], capture_output=True, text=True, check=True)
        assets = json.loads(out.stdout)["assets"]
        if not any(a["name"] == "registry.json" for a in assets):
            return {"packs": {}}
        subprocess.run(["gh", "release", "download", "latest", "-p", "registry.json", "-D", DIST, "--clobber"], check=True)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"packs": {}}


def main():
    check_groups()
    os.makedirs(DIST, exist_ok=True)
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = a[len("--only="):].split(",")
        elif a == "--only":
            only = sys.argv[sys.argv.index(a) + 1].split(",")
    changed_only = "--changed-only" in sys.argv
    targets = [p for p in PACKS if (only is None or p in only)]

    versions = load_versions()
    prev_reg = live_registry() if changed_only else {"packs": {}}
    changed = []
    reg = {"packs": {}, "groups": {gid: {"desc": g["desc"], "packs": g["packs"]} for gid, g in GROUPS.items()}}
    no_license = []
    files = []
    for pid in targets:
        meta = meta_mod.read_meta(pid)
        out, size, sha = build(pid)
        files.append(out)
        pack_meta = PACKS[pid]
        v = versions.get(pid, 1)
        prev_sha = prev_reg.get("packs", {}).get(pid, {}).get("sha256")
        if changed_only and prev_sha != sha:
            v += 1
            changed.append(pid)
        versions[pid] = v
        entry = {"version": v, "url": pid + ".zip", "sha256": sha, "size": size,
                  "topics": pack_meta["topics"], "desc": pack_meta["desc"]}
        if "group" in pack_meta:
            entry["group"] = pack_meta["group"]
        if meta:
            for k in ("source", "upstream_version", "fetched", "license", "license_url"):
                if meta.get(k):
                    entry[k] = meta[k]
        if not entry.get("license"):
            no_license.append(pid)
        reg["packs"][pid] = entry
        print(f"{pid}: v{v} {size} bytes {sha[:12]}" + (" (changed)" if pid in changed else ""))

    save_versions(versions)
    reg_path = os.path.join(DIST, "registry.json")
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, sort_keys=True)
    files.append(reg_path)
    write_licenses_md(reg)

    if no_license:
        print(f"warning: no license metadata for: {', '.join(no_license)} (write docs/<pack>/meta.json)")

    if "--publish" in sys.argv:
        upload = files
        if changed_only:
            upload = [f for f in files if f == reg_path or os.path.basename(f)[:-4] in changed]
        have = subprocess.run(["gh", "release", "view", "latest"], capture_output=True).returncode == 0
        if have:
            subprocess.run(["gh", "release", "upload", "latest", *upload, "--clobber"], check=True)
        else:
            subprocess.run(["gh", "release", "create", "latest", *upload, "--title", "Doc packs",
                            "--notes", "Registry and doc packs for pman."], check=True)


def write_licenses_md(reg):
    lines = ["# Pack licenses\n", "Generated by `tools/build_packs.py`; edit `docs/<pack>/meta.json` instead.\n",
             "| pack | license | source |", "|---|---|---|"]
    for pid, info in sorted(reg["packs"].items()):
        lic = info.get("license", "?")
        src = info.get("source", "")
        lines.append(f"| {pid} | {lic} | {src} |")
    with open(os.path.join(ROOT, "LICENSES.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
