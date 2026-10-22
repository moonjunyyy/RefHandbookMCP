"""The sandbox's capability kinds: policy, script, layer (kernel/capabilities.py has the life cycle).

    policy  what a sandbox is: the commands it shows (or "*": every command of the host and its
            layers), the network and its ports, the limits, the layers stacked on the base, and
            mounts of the user's own data. A grant: a version the model writes that widens one waits
            for the user's approval; narrowing takes effect at once.
    script  an interpreter of its policy, a body, the commands it requires (checked against the
            policy at every write and every review) and an optional self-test (args, expected output)
            that its review runs as a job.
    layer   a build script run as root inside a sandbox over the base (and parent layers); what it
            installs under /usr/local, /opt and /etc becomes a read-only layer a policy can stack.
            Built as a job; a build with the network is a grant.

What a version in force is, the runner reads from plain nodes the kinds write when a version comes
into force: policy:<name> and script:<name> (as before the registry), and the layer's built tree.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from ..kernel.capabilities import DAY, CapError, Kind, Registry, register
from . import sandbox

NUMBERS = {"timeout": float, "memory_mb": int, "cpus": float, "tmp_mb": int, "disk_mb": int, "concurrent": int}
POLICY_FIELDS = {"commands", "network", "ports", "mounts", "layers", "description", *NUMBERS}
RESERVED = ("/", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc", "/opt", "/proc", "/dev",
            "/work", "/tmp", "/run", "/job", "/root", "/sys", "/var")
CMD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _ws(reg: Registry) -> Any:
    ws = reg.ctx.get("ws")
    if ws is None:
        raise CapError("the sandbox kinds need the workspace")
    return ws


# ── mounts ───────────────────────────────────────────────────────────────

def mount_roots(ws: Any) -> list[str]:
    """RHB_SANDBOX_MOUNT_ROOTS: the host directories (colon-separated; {user} and {uid} name the
    store's owner) under which a policy may mount the user's data. Unset: no mounts."""
    out = []
    for t in filter(None, os.environ.get("RHB_SANDBOX_MOUNT_ROOTS", "").split(":")):
        try:
            out.append(os.path.realpath(t.format(user=ws.owner, uid=ws.owner_uid)))
        except (KeyError, IndexError, ValueError) as e:
            raise CapError(f"RHB_SANDBOX_MOUNT_ROOTS: bad template {t!r}: {e}") from e
    return out


def mount_source(ws: Any, source: str) -> str:
    """The host path a mount's source names, checked to lie under an allowed root."""
    roots = mount_roots(ws)
    if not roots:
        raise CapError("mounts are off on this server: the administrator names the directories users may mount "
                       "with RHB_SANDBOX_MOUNT_ROOTS (e.g. /data/{user})")
    try:
        path = os.path.realpath(source.format(user=ws.owner, uid=ws.owner_uid))
    except (KeyError, IndexError, ValueError) as e:
        raise CapError(f"mount source {source!r}: {e}") from e
    if not any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots):
        raise CapError(f"mount source {source!r} is outside the directories this server lets you mount: "
                       f"{', '.join(roots)}")
    if not os.path.exists(path):
        raise CapError(f"mount source {source!r} does not exist ({path})")
    return path


def _mounts(ws: Any, mounts: Any) -> list[dict[str, Any]]:
    if not isinstance(mounts, list):
        raise CapError("mounts is a list of {source, target, rw}")
    out, targets = [], set()
    for m in mounts:
        if not isinstance(m, dict) or set(m) - {"source", "target", "rw"} or not m.get("source") or not m.get("target"):
            raise CapError(f"a mount is {{source, target, rw}}, not {m!r}")
        target = os.path.normpath(str(m["target"]))
        if not target.startswith("/") or any(c in target for c in ":,\n") or any(
                target == r or (r != "/" and target.startswith(r + "/")) for r in RESERVED):
            raise CapError(f"mount target {m['target']!r}: an absolute path outside the sandbox's own directories "
                           f"({' '.join(RESERVED)}); e.g. /data or /mnt/papers")
        if target in targets:
            raise CapError(f"mount target {target} is used twice")
        targets.add(target)
        mount_source(ws, str(m["source"]))
        out.append({"source": str(m["source"]), "target": target, "rw": bool(m.get("rw", False))})
    return out


# ── layers ───────────────────────────────────────────────────────────────

def layer_dir(ws: Any, name: str, version: int) -> str:
    return f"{name}.v{version}"


def built_layers(reg: Registry, names: list[str]) -> list[str]:
    """The built trees' names for a policy's layers, top first; refused while one is not built."""
    out = []
    for n in names:
        rec, ver, _ = reg.in_force("layer", n)
        if rec["attrs"].get("built") != ver["version"]:
            state = (f"its build failed: {rec['attrs']['build_error']}" if rec["attrs"].get("build_error")
                     else f"it is still building ({rec['attrs'].get('building', 'no job')})")
            raise CapError(f"layer {n} v{ver['version']} is not built: {state}")
        out.append(layer_dir(None, n, ver["version"]))
    return out


def layer_trees(reg: Registry, names: list[str]) -> list[str]:
    ws = _ws(reg)
    store = ws.layer_store()
    trees = []
    for d in store.resolve(built_layers(reg, names))[1]:
        trees.append(str(store.tree(d)))
    return trees


def _follow(tree: str, rel: str) -> str | None:
    """Where `rel` (a path inside the sandbox) lands when `tree` is a layer over the host base: a
    symlink is followed with the sandbox's root as its root; a path the layer does not hold is the
    base's (the host's)."""
    for _ in range(40):
        if rel.startswith(".."):
            return None
        p = os.path.join(tree, rel)
        if os.path.islink(p):
            t = os.readlink(p)
            rel = os.path.normpath(t if t.startswith("/") else os.path.join(os.path.dirname(rel), t)).lstrip("/")
            continue
        if os.path.lexists(p):
            return p
        host = "/" + rel
        return host if os.path.exists(host) else None
    return None


def resolve_command(name: str, trees: list[str]) -> str | None:
    """The host file a command name runs: from a layer (top first) or from the host."""
    if not CMD_RE.match(name):
        raise CapError(f"command {name!r}: a bare name (letters, digits, . _ + -)")
    for tree in trees:
        for d in sandbox.COMMAND_DIRS:
            if not os.path.lexists(os.path.join(tree, d, name)):
                continue
            p = _follow(tree, f"{d}/{name}")
            if p and os.path.isfile(p) and os.access(p, os.X_OK):
                return os.path.realpath(p)
    host = shutil.which(name, path=sandbox.HOST_PATH)
    return os.path.realpath(host) if host else None


# ── policy ───────────────────────────────────────────────────────────────

class PolicyKind(Kind):
    name = "policy"
    description = ("what a sandbox is: commands (a list, or ['*'] for all), network and ports, limits "
                   "(timeout, memory_mb, cpus, tmp_mb, disk_mb, concurrent), layers, mounts [{source, target, rw}]")
    ttl = 30 * DAY

    def defaults(self, reg: Registry) -> dict[str, Any]:
        ws = _ws(reg)
        base = ws.default_policy_spec()
        rec = reg.find("policy", ws.DEFAULT)
        if rec is not None and rec["attrs"].get("version"):
            base = {**base, **reg.version(rec)["spec"]}
        return base

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        ws = _ws(reg)
        bad = set(spec) - POLICY_FIELDS
        if bad:
            raise CapError(f"unknown policy fields {sorted(bad)}; known: {', '.join(sorted(POLICY_FIELDS))}")
        named = "description" in spec
        spec = {**self.defaults(reg), **spec}
        if not named:
            spec["description"] = name
        layers = spec.get("layers") or []
        if not isinstance(layers, list) or not all(isinstance(x, str) for x in layers):
            raise CapError("layers is a list of layer names")
        trees = layer_trees(reg, layers) if layers else []
        cmds = list(dict.fromkeys(spec.get("commands") or []))
        if cmds == ["*"]:
            pass
        elif "*" in cmds:
            raise CapError("commands is ['*'] (every command) or a list of names, not both")
        else:
            missing = [c for c in cmds if resolve_command(c, trees) is None]
            if missing:
                raise CapError(f"not installed on the host{' or its layers' if layers else ''}: {', '.join(missing)}")
        spec["commands"] = cmds
        spec["network"] = bool(spec.get("network"))
        ports = spec.get("ports")
        if ports is not None:
            try:
                ports = sorted({int(p) for p in ports})
            except (TypeError, ValueError) as e:
                raise CapError("ports are TCP port numbers") from e
            if not all(0 < p < 65536 for p in ports):
                raise CapError("ports are TCP port numbers (1-65535)")
        spec["ports"] = ports
        for k, cast in NUMBERS.items():
            try:
                spec[k] = cast(spec[k])
            except (TypeError, ValueError, KeyError) as e:
                raise CapError(f"{k} is a number") from e
            if spec[k] <= 0:
                raise CapError(f"{k} must be positive")
        spec["mounts"] = _mounts(ws, spec.get("mounts") or [])
        spec["layers"] = layers
        spec["description"] = str(spec.get("description") or name)
        return spec

    def widens(self, reg: Registry, old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
        old = old or _ws(reg).default_policy_spec()
        why = []
        oc, nc = set(old.get("commands") or []), set(new["commands"])
        if "*" in nc and "*" not in oc:
            why.append("every command")
        elif "*" not in nc and "*" not in oc and nc - oc:
            why.append("commands " + " ".join(sorted(nc - oc)))
        if new["network"] and not old.get("network"):
            why.append("the network")
        if new["network"] and old.get("network"):
            op, np_ = old.get("ports"), new.get("ports")
            if (op is not None and np_ is None) or (op is not None and np_ is not None and set(np_) - set(op)):
                why.append(f"ports {'any' if np_ is None else ' '.join(map(str, sorted(set(np_) - set(op))))}")
        for k in NUMBERS:
            if float(new[k]) > float(old.get(k, 0)):
                why.append(f"{k} {old.get(k)} → {new[k]}")
        om = {(m["source"], m["target"], m["rw"]) for m in old.get("mounts") or []}
        for m in new["mounts"]:
            if (m["source"], m["target"], m["rw"]) not in om and (m["source"], m["target"], True) not in om:
                why.append(f"mount {m['source']} at {m['target']}{' read-write' if m['rw'] else ''}")
        added = set(new["layers"]) - set(old.get("layers") or [])
        if added:
            why.append("layers " + " ".join(sorted(added)))
        return why

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        _ws(reg).materialize("policy", rec["attrs"]["name"], ver["spec"], ver["spec"]["description"])

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        _ws(reg).dematerialize("policy", rec["attrs"]["name"])

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        try:
            self.validate(reg, rec["attrs"]["name"], dict(ver["spec"]), None)
        except CapError as e:
            return "fail", str(e)
        return "pass", ""

    def repair(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any], detail: str) -> dict[str, Any] | None:
        spec = dict(ver["spec"])
        if spec.get("commands") == ["*"]:
            return None
        trees = []
        try:
            trees = layer_trees(reg, spec.get("layers") or [])
        except CapError:
            spec["layers"] = []
        spec["commands"] = [c for c in spec["commands"] if resolve_command(c, trees) is not None]
        try:
            return self.validate(reg, rec["attrs"]["name"], spec, None)
        except CapError:
            return None

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description", "")


# ── script ───────────────────────────────────────────────────────────────

class ScriptKind(Kind):
    name = "script"
    description = ("a body run by an interpreter of its policy: spec {interpreter, policy, requires [commands], "
                   "description, test {args, expect}}")
    ttl = 30 * DAY
    has_body = True

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        bad = set(spec) - {"interpreter", "policy", "requires", "description", "test"}
        if bad:
            raise CapError(f"unknown script fields {sorted(bad)}")
        ws = _ws(reg)
        spec.setdefault("interpreter", "sh")
        spec.setdefault("policy", ws.DEFAULT)
        reqs = spec.get("requires") or []
        if isinstance(reqs, str):
            reqs = reqs.split()
        spec["requires"] = list(dict.fromkeys(reqs))
        pol = ws.policy(spec["policy"])["attrs"]
        cmds = pol["commands"]
        need = [spec["interpreter"], *spec["requires"]]
        if cmds == ["*"]:
            trees = layer_trees(reg, pol.get("layers") or [])
            missing = [c for c in need if resolve_command(c, trees) is None]
        else:
            missing = [c for c in need if c not in cmds]
        if missing:
            raise CapError(f"not a command of policy {spec['policy']!r}: {', '.join(missing)} (its commands: "
                           f"{' '.join(cmds)}); ask the user to grant them, or propose a policy with them")
        t = spec.get("test")
        if t is not None:
            if not isinstance(t, dict) or set(t) - {"args", "expect"} or not all(isinstance(a, str) for a in t.get("args", [])):
                raise CapError("test is {args: [strings], expect: text the output must contain}")
        spec["description"] = str(spec.get("description", ""))
        return spec

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        ws = _ws(reg)
        s = ver["spec"]
        ws.materialize("script", rec["attrs"]["name"], {
            "interpreter": s["interpreter"], "blob": ws.g.put_blob(ver["body"]), "policy": s["policy"],
            "size": len(ver["body"].encode()), "requires": s["requires"], "version": ver["version"]},
            s["description"], state="active")

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        _ws(reg).dematerialize("script", rec["attrs"]["name"])

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        ws = _ws(reg)
        try:
            reg.in_force("policy", ver["spec"]["policy"])
            self.validate(reg, rec["attrs"]["name"], dict(ver["spec"]), ver["body"])
        except CapError as e:
            return "fail", str(e)
        t = ver["spec"].get("test")
        if not t:
            return "pass", ""
        jid = rec["attrs"].get("checking")
        if not jid:
            jid = ws.submit(rec["attrs"]["name"], list(t.get("args", [])), actor="kernel")
            reg.g.update_node(rec["id"], actor="kernel", attrs={"checking": jid})
            ws.kick()
            return "pending", ""
        j = ws.job(jid)
        if j["state"] in ("queued", "running"):
            return "pending", ""
        out = ws.output(j, "stdout")
        if j["state"] != "done":
            return "fail", f"its self-test {jid} ended {j['state']} (exit {j['attrs'].get('exit')})"
        if t.get("expect") and t["expect"] not in out:
            return "fail", f"its self-test {jid} did not print {t['expect']!r}"
        return "pass", f"self-test {jid}"

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description", "")


# ── layer ────────────────────────────────────────────────────────────────

class LayerKind(Kind):
    name = "layer"
    description = ("binaries and data for the sandbox: a build script (body) run as root over the base and "
                   "parents; spec {parents, network, timeout, description}. A policy lists the layers it stacks.")
    ttl = 90 * DAY
    has_body = True

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        bad = set(spec) - {"parents", "network", "timeout", "description"}
        if bad:
            raise CapError(f"unknown layer fields {sorted(bad)}")
        parents = spec.get("parents") or []
        if name in parents:
            raise CapError("a layer is not its own parent")
        built_layers(reg, parents)
        spec["parents"] = list(parents)
        spec["network"] = bool(spec.get("network"))
        spec["timeout"] = float(spec.get("timeout") or 1800)
        if not 0 < spec["timeout"] <= 4 * 3600:
            raise CapError("a layer build's timeout is at most 4 hours")
        spec["description"] = str(spec.get("description", ""))
        return spec

    def widens(self, reg: Registry, old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
        return ["a build with the network"] if new["network"] else []

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        ws = _ws(reg)
        jid = ws.submit_build(rec["attrs"]["name"], ver)
        reg.g.update_node(rec["id"], actor="kernel", attrs={"building": jid, "build_error": None})
        ws.kick()

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        ws = _ws(reg)
        store = ws.layer_store()
        prefix = f"{rec['attrs']['name']}.v"
        for lay in store.list():
            if lay.name.startswith(prefix) and not any(lay.name in o.parents for o in store.list()):
                store.remove(lay.name)

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        a = rec["attrs"]
        if a.get("built") == ver["version"]:
            tree = _ws(reg).layer_store().tree(layer_dir(None, a["name"], ver["version"]))
            return ("pass", "") if Path(tree).is_dir() else ("fail", "its built tree is gone")
        if a.get("build_error"):
            return "fail", f"its build failed: {a['build_error']}"
        return "pending", ""

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description", "")


for _k in (PolicyKind(), ScriptKind(), LayerKind()):
    register(_k)
