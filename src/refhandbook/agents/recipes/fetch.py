"""Download helper for the recipes, standard library only (a host may lack curl or xz).

    python3 fetch.py URL DEST                  download URL to DEST
    python3 fetch.py --unpack URL DIR [STRIP]  unpack the tar archive at URL into DIR, dropping
                                               STRIP leading path components (default 0)
    python3 fetch.py --json URL EXPR           print EXPR evaluated on the JSON at URL (as `d`)
"""
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "refhandbook-layers"})
    return urllib.request.urlopen(req, timeout=300)


def unpack(url: str, dest: str, strip: int) -> None:
    with tempfile.TemporaryFile() as tmp:
        with get(url) as r:
            shutil.copyfileobj(r, tmp)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tf:
            members = []
            for m in tf.getmembers():
                parts = m.name.split("/")[strip:]
                if not parts or not parts[0]:
                    continue
                m.name = "/".join(parts)
                if m.islnk():
                    m.linkname = "/".join(m.linkname.split("/")[strip:])
                members.append(m)
            os.makedirs(dest, exist_ok=True)
            tf.extractall(dest, members=members, filter="tar")


if sys.argv[1] == "--json":
    print(eval(sys.argv[3], {"d": json.load(get(sys.argv[2]))}))  # noqa: S307 — the recipe's own expression
elif sys.argv[1] == "--unpack":
    unpack(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
else:
    with get(sys.argv[1]) as r, open(sys.argv[2], "wb") as f:
        shutil.copyfileobj(r, f)
