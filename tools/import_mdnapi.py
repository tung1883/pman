"""Builds docs/webapi/ from mdn/content (CC BY-SA 2.5): Web APIs (DOM, fetch, Storage, Canvas, ...) and HTTP
(headers, methods, status codes, guides). Pages: webapi.<interface>[-<member>], http.<name>.
Reuses the cloned repo and the markdown cleanup of import_mdn.py. Niche hardware/3D families are skipped."""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdtext  # noqa: E402
from import_mdn import REPO, WEB, clean, ensure_repo, slug  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "webapi", "man")
NICHE = re.compile(r"^(webgl|webgpu|gpu|xr|webxr|vr|bluetooth|usb|hid|serial|midi|ndef|nfc|web_?audio_?mod|gamepad|"
                   r"ink|barcode|battery|sensor|accelerometer|gyroscope|magnetometer|orientationsensor|light|"
                   r"proximity|ambient|payment|presentation|remote_?playback|screen_?capture|eyedropper|"
                   r"webtransport|webcodecs|webhid|webusb|webserial|webmidi|webnn|ml|window_management)", re.I)
HTTP_SECTIONS = {"headers": "header-", "methods": "method-", "status": "status-", "csp": "csp-", "cors": "cors-",
                 "range_requests": "range-", "conditional_requests": "conditional-", "caching": "caching-",
                 "cookies": "cookies-", "authentication": "auth-", "redirections": "redirect-", "messages": "messages-",
                 "headers/permissions-policy": "permissions-policy-"}


def ids(rel):
    parts = rel.split("/")
    if parts[0] == "http":
        sub = parts[1:]
        if sub and sub[0] in ("guides", "reference"):
            sub = sub[1:]
        if not sub:
            return None
        pre = HTTP_SECTIONS.get(sub[0], "guide-" if sub[0] not in HTTP_SECTIONS else "")
        rest = sub[1:] if sub[0] in HTTP_SECTIONS else sub
        return "http", pre + slug("-".join(rest) or sub[0])
    if parts[0] == "api":
        sub = parts[1:]
        if not sub or NICHE.match(sub[0]):
            return None
        return "webapi", slug("-".join(sub))
    return None


def main():
    ensure_repo()
    subprocess.run(["git", "-C", REPO, "sparse-checkout", "add", "files/en-us/web/api", "files/en-us/web/http"], check=True)
    shutil.rmtree(os.path.join(ROOT, "docs", "webapi"), ignore_errors=True)
    used = {"http": set(), "webapi": set()}
    n = 0
    for base, _dirs, files in sorted(os.walk(WEB)):
        if "index.md" not in files:
            continue
        rel = os.path.relpath(base, WEB).replace(os.sep, "/")
        info = ids(rel)
        if not info or not info[1]:
            continue
        topic, pid = info
        k, base_pid = 2, pid
        while pid in used[topic]:
            pid = f"{base_pid}-{k}"
            k += 1
        used[topic].add(pid)
        src = open(os.path.join(base, "index.md"), encoding="utf-8", errors="replace").read()
        meta, body = mdtext.parse_front_matter(src)
        title = meta.get("title") if isinstance(meta.get("title"), str) else pid
        title = clean(title).strip("\"'")
        body = clean(body)
        syn = re.search(r"\n\s*\n([^\n#`{][^\n]*)", "\n\n" + body.lstrip())
        synopsis = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", re.sub(r"[`*_]", "", syn.group(1)).strip()) if syn else ""
        name_line = f"{title} - {synopsis[:140]}" if synopsis else title
        text = mdtext.convert(f"# {title}\n\n{body}", f"{topic}.{pid}", "Web APIs" if topic == "webapi" else "HTTP",
                              name_line=name_line)
        if len(text) < 300:
            continue
        d = os.path.join(OUT, topic)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("webapi pages", n, {k: len(v) for k, v in used.items()})


if __name__ == "__main__":
    main()
