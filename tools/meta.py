"""Shared helper for importers: writes docs/<pack>/meta.json (source, upstream version, license).

    from meta import write_meta
    write_meta("docker", name="Docker documentation", source="https://docs.docker.com/",
               upstream_version="27", license="Apache-2.0", license_url="https://.../LICENSE")

build_packs.py reads this file (if present) and copies its fields into the registry entry; the
file itself ships inside the pack's zip too, so `pman pack info` works without a registry round
trip for a locally-added pack.
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


def write_meta(pack, name="", source="", upstream_version="", license="", license_url="", fetched=None):
    d = os.path.join(DOCS, pack)
    os.makedirs(d, exist_ok=True)
    data = {
        "name": name,
        "source": source,
        "upstream_version": upstream_version,
        "fetched": fetched or datetime.date.today().isoformat(),
        "license": license,
        "license_url": license_url,
    }
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def read_meta(pack):
    path = os.path.join(DOCS, pack, "meta.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
