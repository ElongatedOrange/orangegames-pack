#!/usr/bin/env python3
"""Build OrangeGamesPack.zip from the repo contents and print its SHA-1.

The zip (and its SHA-1) are what server.properties points at:
  resource-pack=https://raw.githubusercontent.com/<user>/orangegames-pack/main/OrangeGamesPack.zip
  resource-pack-sha1=<sha1>

Run after any asset change, commit the refreshed zip together with the change.
"""
import hashlib
import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "OrangeGamesPack.zip")
EXCLUDE = {".git", ".github", "OrangeGamesPack.zip", "build.py", "README.md"}

entries = []
for base, dirs, files in os.walk(ROOT):
    rel_base = os.path.relpath(base, ROOT)
    parts = [] if rel_base == "." else rel_base.split(os.sep)
    if parts and parts[0] in EXCLUDE:
        dirs[:] = []
        continue
    dirs[:] = [d for d in dirs if not (not parts and d in EXCLUDE)]
    for f in files:
        if not parts and f in EXCLUDE:
            continue
        full = os.path.join(base, f)
        arc = os.path.relpath(full, ROOT).replace(os.sep, "/")
        entries.append((full, arc))

entries.sort(key=lambda e: e[1])
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for full, arc in entries:
        # Fixed timestamp so identical content -> identical zip -> stable SHA-1
        info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        with open(full, "rb") as fh:
            z.writestr(info, fh.read(), zipfile.ZIP_DEFLATED)

sha1 = hashlib.sha1(open(OUT, "rb").read()).hexdigest()
print(f"{len(entries)} files -> {OUT}")
print(f"sha1: {sha1}")
