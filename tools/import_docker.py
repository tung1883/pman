"""Builds docs/docker/ from docker/docs (Apache-2.0) and docker/compose, plus the Dockerfile reference from
moby/buildkit (Apache-2.0). Pages: docker.<command> (docker.run, docker.container-ls, docker.buildx-build,
docker.compose-up), docker.dockerfile, docker.compose-file-services, docker.engine-*, docker.build-*, docker.compose-*.
Needs git + network (clones into .cache/)."""
import os
import re
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
DOCS = os.path.join(CACHE, "docker")
COMPOSE = os.path.join(CACHE, "compose")
OUT = os.path.join(ROOT, "docs", "docker", "man", "docker")
DOCKERFILE_URL = "https://raw.githubusercontent.com/moby/buildkit/master/frontend/dockerfile/docs/reference.md"
CLI_DIRS = ["engine", "buildx", "scout"]
MANUALS = ["engine", "compose", "build"]
SKIP_PAGES = re.compile(r"release-notes|_index$|^index$|changelog|deprecated|archive", re.I)


def ensure_repos():
    if not os.path.isdir(DOCS):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/docker/docs.git", DOCS], check=True)
    subprocess.run(["git", "-C", DOCS, "sparse-checkout", "set", "content/reference/compose-file", "content/manuals/engine",
                    "content/manuals/compose", "content/manuals/build", "data/cli"], check=True)
    if not os.path.isdir(COMPOSE):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/docker/compose.git", COMPOSE], check=True)
    subprocess.run(["git", "-C", COMPOSE, "sparse-checkout", "set", "docs/reference"], check=True)


def clean_hugo(src):
    src = re.sub(r"\{\{[<%].*?[>%]\}\}", "", src, flags=re.S)           # shortcodes
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"^\s*\{\.[^}]*\}\s*$", "", src, flags=re.M)
    return src


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def write(pid, title, md, label="Docker"):
    first = next((l.strip() for l in md.split("\n") if l.strip() and not l.startswith(("#", "|", "```", ">", "-", "*"))), "")
    first = re.sub(r"[`*_]", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", first))[:140]
    name_line = f"{title} - {first}" if first else title
    text = mdtext.convert(f"# {title}\n\n{md}", f"docker.{pid}", label, name_line=name_line)
    if len(text) < 300:
        return False
    with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def command_page(path):
    d = yaml.safe_load(open(path, encoding="utf-8"))
    cmd = d.get("command", "")
    if not cmd.startswith("docker") or d.get("deprecated") is True:
        return None
    words = cmd.split()[1:]
    if not words:
        return None
    md = []
    if d.get("short"):
        md.append(str(d["short"]).strip() + "\n")
    if d.get("usage"):
        md.append("## Usage\n\n```\n" + str(d["usage"]).strip() + "\n```\n")
    if d.get("aliases") and d["aliases"] != cmd:
        md.append("Aliases: " + str(d["aliases"]) + "\n")
    long = str(d.get("long") or "").strip()
    if long and long != str(d.get("short", "")).strip():
        md.append("## Description\n\n" + long + "\n")
    opts = [o for o in d.get("options") or [] if not o.get("hidden")]
    if opts:
        md.append("## Options\n")
        for o in opts:
            flag = f"--{o['option']}" + (f", -{o['shorthand']}" if o.get("shorthand") else "")
            line = f"* {flag} ({o.get('value_type', '')}): " + " ".join(str(o.get("description", "")).split())
            default = str(o.get("default_value", ""))
            if default and default not in ("[]", "map[]", "false", "0", '""'):
                line += f" [default: {default}]"
            md.append(line)
        md.append("")
    ex = str(d.get("examples") or "").strip()
    if ex:
        md.append("## Examples\n\n" + ex + "\n")
    return "-".join(words), cmd, "\n".join(md)


def main():
    ensure_repos()
    shutil.rmtree(os.path.join(ROOT, "docs", "docker"), ignore_errors=True)
    os.makedirs(OUT)
    used = set()
    n = 0

    def add(pid, title, md):
        nonlocal n
        pid = slug(pid) or "index"
        base, k = pid, 2
        while pid in used:
            pid = f"{base}-{k}"
            k += 1
        if write(pid, title, md):
            used.add(pid)
            n += 1

    for sub in CLI_DIRS:
        d = os.path.join(DOCS, "data", "cli", sub)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if name.endswith(".yaml") and name.startswith("docker"):
                r = command_page(os.path.join(d, name))
                if r:
                    add(r[0], r[1], r[2])
    d = os.path.join(COMPOSE, "docs", "reference")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".yaml") and name.startswith("docker_compose"):
            r = command_page(os.path.join(d, name))
            if r:
                add(r[0], r[1], r[2])

    # Dockerfile reference
    ref = subprocess.run(["curl", "-sSL", "--fail", DOCKERFILE_URL], capture_output=True, check=True).stdout.decode("utf-8")
    meta, body = mdtext.parse_front_matter(ref)
    add("dockerfile", "Dockerfile reference", clean_hugo(body))

    # Compose file reference and the engine / build / compose manuals
    areas = [("content/reference/compose-file", "compose-file")] + [(f"content/manuals/{m}", m) for m in MANUALS]
    for rel, area in areas:
        base = os.path.join(DOCS, rel)
        for dirpath, _dirs, files in sorted(os.walk(base)):
            for name in sorted(files):
                if not name.endswith(".md"):
                    continue
                relp = os.path.relpath(os.path.join(dirpath, name), base)[:-3].replace(os.sep, "/")
                if SKIP_PAGES.search(relp) and relp != "_index":
                    continue
                src = open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
                meta, body = mdtext.parse_front_matter(src)
                title = meta.get("title") if isinstance(meta.get("title"), str) else relp.split("/")[-1]
                parts = [p for p in relp.split("/") if p != "_index"]
                pid = "-".join([area] + parts)
                if relp == "_index":
                    pid = area
                add(pid, title.strip("\"'"), clean_hugo(body))
    print("docker pages", n)


if __name__ == "__main__":
    main()
