"""The common sandbox base and the layers stacked on it.

    <data>/sandbox/
        hostetc/                 the host base's lowest /etc (sandbox.prepare_hostetc)
        bases/<name>/            an imported root filesystem tree (base "rootfs")
        layers/<name>/layer.json {name, base, parents, description, created, network}
        layers/<name>/tree/      the layer: only its overlay points (usr/local, opt, etc — or usr,
                                 etc, opt, var on a rootfs base), with overlay whiteouts

A layer is made once by an administrator, with the network if the build needs it (package indexes,
git), and used read-only by every agent afterwards, which runs without a network: whatever the
agents need offline (wheels, toolchains, datasets) is put into a layer. `build` runs a script in the
same sandbox the agents use, as root inside the namespace, and keeps what it changed as the new
layer. `import_tar` unpacks a tarball as a base (a whole root tree) or as a layer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import sandbox

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class LayerError(ValueError):
    pass


def _name(name: str) -> str:
    if not NAME_RE.match(name):
        raise LayerError(f"layer name {name!r}: lowercase letters, digits, '.', '_' and '-'")
    return name


@dataclass
class Layer:
    name: str
    base: str  # "host" or a base name
    parents: list[str]  # layers below this one, top first
    description: str
    created: str
    network: bool

    def to_json(self) -> dict[str, Any]:
        return self.__dict__.copy()


class LayerStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ── paths ────────────────────────────────────────────────────────────

    @property
    def hostetc(self) -> Path:
        return self.root / "hostetc"

    def base_path(self, base: str) -> str:
        """The Spec.base value for a base name: "host", or the imported tree."""
        if base == "host":
            return "host"
        p = self.root / "bases" / _name(base)
        if not p.is_dir():
            raise LayerError(f"no base {base!r}; import one with `refhandbook sandbox-layer import --base`")
        return str(p)

    def tree(self, name: str) -> Path:
        return self.root / "layers" / _name(name) / "tree"

    def ensure_hostetc(self, max_age: float = 86400.0) -> Path:
        p = self.hostetc
        if not p.is_dir() or time.time() - p.stat().st_mtime > max_age:
            sandbox.prepare_hostetc(p)
        return p

    # ── catalogue ────────────────────────────────────────────────────────

    def get(self, name: str) -> Layer:
        meta = self.root / "layers" / _name(name) / "layer.json"
        if not meta.is_file():
            raise LayerError(f"no layer {name!r}")
        return Layer(**json.loads(meta.read_text()))

    def list(self) -> list[Layer]:
        d = self.root / "layers"
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.iterdir()):
            if (p / "layer.json").is_file():
                out.append(Layer(**json.loads((p / "layer.json").read_text())))
        return out

    def bases(self) -> list[str]:
        d = self.root / "bases"
        return ["host"] + (sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else [])

    def resolve(self, names: list[str]) -> tuple[str, list[str]]:
        """The base and the lower stack (top first) for a selection of layers: each layer is
        followed by its parents; a layer already in the stack is not repeated. All must share one
        base."""
        stack: list[str] = []
        base: str | None = None

        def visit(n: str, seen: tuple[str, ...]) -> None:
            nonlocal base
            if n in seen:
                raise LayerError(f"layer {n!r} is its own parent")
            lay = self.get(n)
            if base is None:
                base = lay.base
            elif lay.base != base:
                raise LayerError(f"layer {n!r} is on base {lay.base!r}, the others on {base!r}")
            if n not in stack:
                stack.append(n)
            for p in lay.parents:
                visit(p, seen + (n,))

        for n in names:
            visit(n, ())
        return base or "host", stack

    def spec_parts(self, names: list[str]) -> dict[str, Any]:
        """Spec fields (base, layers, hostetc) for a selection of layers."""
        base, stack = self.resolve(names)
        parts: dict[str, Any] = {"base": self.base_path(base), "layers": [str(self.tree(n)) for n in stack]}
        if base == "host":
            parts["hostetc"] = str(self.ensure_hostetc())
        return parts

    def _write(self, layer: Layer) -> None:
        d = self.root / "layers" / layer.name
        (d / "layer.json").write_text(json.dumps(layer.to_json(), indent=2) + "\n")

    def remove(self, name: str) -> None:
        users = [lay.name for lay in self.list() if name in lay.parents]
        if users:
            raise LayerError(f"layer {name!r} is a parent of {', '.join(users)}; remove those first")
        d = self.root / "layers" / _name(name)
        if not d.is_dir():
            raise LayerError(f"no layer {name!r}")
        sandbox.rmtree(d)

    # ── making layers ────────────────────────────────────────────────────

    def build(self, name: str, script: str, *, base: str = "host", parents: list[str] | None = None,
              network: bool = False, description: str = "", timeout: float = 3600.0,
              limits: sandbox.Limits | None = None, ports: list[int] | None = None,
              commands: dict[str, str] | None = None) -> tuple[Layer, int, str]:
        """Run `script` (shell text) as root in a sandbox over base + parents and keep what it
        changed under the overlay points as layer `name`. Returns (layer, exit status, output);
        the layer is kept only if the script exits 0."""
        _name(name)
        parents = list(parents or [])
        if (self.root / "layers" / name).exists():
            raise LayerError(f"layer {name!r} exists; remove it first")
        if parents:
            pbase, stack = self.resolve(parents)
            if pbase != base:
                raise LayerError(f"parents are on base {pbase!r}, not {base!r}")
        else:
            stack = []
        (self.root / "layers").mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f".build-{name}.", dir=self.root / "layers"))
        try:
            for d in ("root", "upper", "work"):
                (work / d).mkdir()
            (work / "work" / "build.sh").write_text(script)
            spec = sandbox.Spec(
                argv=["/bin/sh", "-e", "/work/build.sh"], root=str(work / "root"), work=str(work / "work"),
                base=self.base_path(base), layers=[str(self.tree(n)) for n in stack], upper=str(work / "upper"),
                hostetc=str(self.ensure_hostetc()) if base == "host" else None, network=network, uid=0, gid=0,
                ports=ports if network else None, commands=list(commands) if commands is not None else None,
                command_paths=commands,
                timeout=timeout, limits=limits or sandbox.Limits(memory_mb=8192, pids=4096, fsize_mb=16384,
                                                                  tmp_mb=4096, cpus=4.0),
                env={"HOME": "/root", "DEBIAN_FRONTEND": "noninteractive"}, cwd="/work")
            (work / "spec.json").write_text(spec.to_json())
            r = subprocess.run(sandbox.command(str(work / "spec.json")), capture_output=True, text=True,
                               timeout=timeout + 30)
            out = (r.stdout + r.stderr)[-20000:]
            if r.returncode != 0:
                return Layer(name, base, parents, description, "", network), r.returncode, out
            final = self.root / "layers" / name
            tree = work / "tree"
            tree.mkdir()
            for point in spec.overlay_points():
                src = work / "upper" / point.replace("/", "_")
                if src.is_dir() and any(src.iterdir()):
                    dst = tree / point
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(src, dst)
            layer = Layer(name, base, parents, description, time.strftime("%Y-%m-%dT%H:%M:%S%z"), network)
            final.mkdir()
            os.rename(tree, final / "tree")
            self._write(layer)
            return layer, 0, out
        finally:
            sandbox.rmtree(work)

    def import_tar(self, name: str, tarball: str, *, as_base: bool = False, base: str = "host",
                   parents: list[str] | None = None, description: str = "") -> str:
        """Unpack a tarball as a base (a whole root tree, e.g. `docker export` or a debootstrap) or
        as a layer (only its overlay points are kept). Device nodes are skipped (they cannot be made
        without privilege, and a sandbox gets its /dev from the launcher); set-id bits are cleared."""
        _name(name)
        dest = self.root / ("bases" if as_base else "layers") / name
        if dest.exists():
            raise LayerError(f"{'base' if as_base else 'layer'} {name!r} exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".import-{name}.", dir=dest.parent))
        try:
            target = tmp / "tree"
            target.mkdir()
            with tarfile.open(tarball) as tf:
                tf.extractall(target, filter=_safe_member)
            if as_base:
                os.rename(target, dest)
                return str(dest)
            points = sandbox.OVERLAY_POINTS["host" if base == "host" else "rootfs"]
            keep = tmp / "keep"
            keep.mkdir()
            for point in points:
                src = target / point
                if src.is_dir():
                    (keep / point).parent.mkdir(parents=True, exist_ok=True)
                    os.rename(src, keep / point)
            dest.mkdir()
            os.rename(keep, dest / "tree")
            self._write(Layer(name, base, list(parents or []), description, time.strftime("%Y-%m-%dT%H:%M:%S%z"), False))
            return str(dest)
        finally:
            sandbox.rmtree(tmp)


def _safe_member(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    if member.ischr() or member.isblk() or member.isfifo():
        return None
    try:
        return tarfile.tar_filter(member, path)
    except tarfile.FilterError:
        return None
