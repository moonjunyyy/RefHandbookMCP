"""Download helper for the recipes, standard library only (a host may lack curl or xz). It goes
through the proxy the build's environment names (the egress supervisor).

    python3 fetch.py [--sums URL] URL DEST                  download URL to DEST
    python3 fetch.py [--sums URL] --unpack URL DIR [STRIP]  unpack the tar archive at URL into DIR,
                                                            dropping STRIP leading path components
    python3 fetch.py --json URL KEY                        print the named JSON field (or latest-lts-version)

--sums names the publisher's checksum list (lines "<sha256>  <file>", or one bare hash): the
download must match the line for its file name, or nothing is written.
"""
import hashlib
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


def expected(sums_url: str, url: str) -> str:
    name = url.rsplit("/", 1)[1]
    text = get(sums_url).read().decode()
    lines = [ln.split() for ln in text.splitlines() if ln.strip()]
    def named(p: list[str]) -> bool:
        return os.path.basename(p[-1].lstrip("*")) == name

    if len(lines) == 1 and len(lines[0][0]) == 64 and (len(lines[0]) == 1 or named(lines[0])):
        return lines[0][0].lower()
    for parts in lines:
        if len(parts) >= 2 and named(parts):
            return parts[0].lower()
    raise SystemExit(f"fetch: {name} is not in {sums_url}")


def download(url: str, sums: str | None) -> tempfile.SpooledTemporaryFile:
    tmp = tempfile.TemporaryFile()
    h = hashlib.sha256()
    with get(url) as r:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            tmp.write(chunk)
    if sums and h.hexdigest() != expected(sums, url):
        raise SystemExit(f"fetch: {url} does not match its published checksum")
    tmp.seek(0)
    return tmp


def unpack(tmp, dest: str, strip: int) -> None:
    """Unpack as the layer's own files: root's. The archive's owners are dropped: the build runs as
    root of a user namespace that maps uid 0 alone, so chown to the publisher's uid (node's is 1001)
    fails, and tarfile, which skips a member's chmod once its chown fails and by default only logs
    that, would leave every file without its modes (a node that cannot run). errorlevel 2: any
    failure to restore a file stops the build instead."""
    with tarfile.open(fileobj=tmp) as tf:
        tf.errorlevel = 2
        members = []
        for m in tf.getmembers():
            parts = m.name.split("/")[strip:]
            if not parts or not parts[0]:
                continue
            m.name = "/".join(parts)
            if m.islnk():
                m.linkname = "/".join(m.linkname.split("/")[strip:])
            m.uid = m.gid = 0
            m.uname = m.gname = "root"
            members.append(m)
        os.makedirs(dest, exist_ok=True)
        tf.extractall(dest, members=members, filter="tar", numeric_owner=True)


def main() -> None:
    args = sys.argv[1:]
    sums = None
    if args[0] == "--sums":
        sums, args = args[1], args[2:]
    if args[0] == "--json":
        data = json.load(get(args[1]))
        key = args[2]
        if key == "latest-lts-version":
            if not isinstance(data, list):
                raise SystemExit("fetch: expected a JSON release list")
            release = next((item for item in data if isinstance(item, dict)
                            and item.get("lts") and isinstance(item.get("version"), str)), None)
            if release is None:
                raise SystemExit("fetch: no LTS release found")
            print(release["version"])
        elif isinstance(data, dict) and key in data:
            print(data[key])
        else:
            raise SystemExit(f"fetch: JSON key {key!r} is missing")
    elif args[0] == "--unpack":
        unpack(download(args[1], sums), args[2], int(args[3]) if len(args) > 3 else 0)
    else:
        with download(args[0], sums) as src, open(args[1], "wb") as f:
            shutil.copyfileobj(src, f)


if __name__ == "__main__":
    main()
