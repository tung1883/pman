"""Cached HTTP fetch for the importers (curl: python's CA store rejects some sites' chains)."""
import hashlib
import os
import subprocess
import time

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")


def fetch(url, delay=0.25):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read()
    html = subprocess.run(["curl", "-sSL", "--fail", "-m", "90", "-A", "Mozilla/5.0 pman-docs-import", url],
                          capture_output=True, check=True).stdout.decode("utf-8", "replace")
    open(f, "w", encoding="utf-8").write(html)
    time.sleep(delay)
    return html
