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
POLICY_FIELDS = {"commands", "network", "ports", "mounts", "layers", "exec_work", "egress", "description", *NUMBERS}
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
#
# A policy pins each layer it stacks to a built version ("name@N"): what the user approved is that
# build. A new version of the layer does not reach the policy until a new version of the policy
# moves the pin, which is a widening like any other. Pinned trees are kept.

PIN_RE = re.compile(r"^((?:sys:)?[a-z0-9][a-z0-9._-]{0,63})(?:@(\d+))?$")
SYS = "sys:"


def layer_dir(name: str, version: int) -> str:
    return f"{name}.v{version}"


def _store(reg: Registry) -> Any:
    return _ws(reg).layer_store()


def pin(reg: Registry, entry: str, keep: dict[str, int] | None = None) -> str:
    """"name" or "name@N" → "name@N": the given build, else the one already pinned, else the latest
    built version of the layer."""
    m = PIN_RE.match(entry or "")
    if not m:
        raise CapError(f"layer {entry!r}: a name, or name@version")
    name, v = m.group(1), m.group(2)
    if name.startswith(SYS):  # the server's shared layers: built by its administrator, no record here
        store = _store(reg).system
        if store is None:
            raise CapError(f"layer {name}: this server has no system layers (`refhandbook layers build`)")
        plain = name[len(SYS):]
        built = sorted(int(x.name.rsplit(".v", 1)[1]) for x in store.list()
                       if re.fullmatch(rf"{re.escape(plain)}\.v\d+", x.name))
        n = int(v) if v else (keep or {}).get(name) or (built[-1] if built else 0)
        if n not in built:
            raise CapError(f"layer {name}@{n or '?'} is not built on this server; built: "
                           f"{', '.join(f'{name}@{b}' for b in built) or 'none'}")
        return f"{name}@{n}"
    rec = reg.get("layer", name)
    if rec["state"] == "retired":
        raise CapError(f"layer {name} is retired")
    n = int(v) if v else (keep or {}).get(name) or rec["attrs"].get("built")
    if not n:
        a = rec["attrs"]
        state = (f"its build failed: {a['build_error']}" if a.get("build_error")
                 else f"it is still building ({a.get('building') or 'no job'})")
        raise CapError(f"layer {name} is not built: {state}")
    if not Path(_store(reg).tree(layer_dir(name, n))).is_dir():
        raise CapError(f"layer {name}@{n} is not built (or was removed)")
    return f"{name}@{n}"


def layer_trees(reg: Registry, pins: list[str]) -> list[str]:
    """The trees for pinned layers and their pinned parents, top first."""
    store = _store(reg)
    try:
        dirs = []
        for p in pins:
            m = PIN_RE.match(p)
            dirs.append(layer_dir(m.group(1), int(m.group(2))))
        return [str(store.tree(d)) for d in store.resolve(dirs)[1]]
    except (ValueError, TypeError, AttributeError) as e:  # LayerError is a ValueError
        raise CapError(f"layers {' '.join(pins)}: {e}") from e


def layer_env(reg: Registry, pins: list[str]) -> dict[str, str]:
    """The environment the stacked layers ask for, bottom layer first; "$PATH" (any $VAR) in a value
    is what the layers below, or the sandbox's default, made of it."""
    from string import Template

    store = _store(reg)
    try:
        dirs = [layer_dir(m.group(1), int(m.group(2))) for p in pins for m in [PIN_RE.match(p)]]
        stack = store.resolve(dirs)[1]
        env = {"PATH": sandbox.HOST_PATH}
        for d in reversed(stack):
            for k, v in store.get(d).env.items():
                env[k] = Template(v).safe_substitute(env)
        return env
    except (ValueError, TypeError, AttributeError) as e:
        raise CapError(f"layers {' '.join(pins)}: {e}") from e


def pinned_dirs(reg: Registry) -> set[str]:
    """Every layer build some policy or layer version still in force (or waiting) names."""
    out = set()
    for rec in reg.list(kind=None):
        a = rec["attrs"]
        if a["kind"] not in ("policy", "layer"):
            continue
        for v in {a.get("version"), a.get("pending")} - {None, 0}:
            spec = reg.version(rec, v)["spec"]
            for p in (spec.get("layers") or []) + (spec.get("parents") or []):
                m = PIN_RE.match(p)
                if m and m.group(2):
                    out.add(layer_dir(m.group(1), int(m.group(2))))
        if a["kind"] == "layer" and a.get("built"):
            out.add(layer_dir(a["name"], a["built"]))
    return out


def prune_layers(reg: Registry, name: str | None = None) -> list[str]:
    """Remove builds nothing pins (of one layer, or all)."""
    store, keep, gone = _store(reg), pinned_dirs(reg), []
    pat = re.compile(rf"^{re.escape(name)}\.v\d+$" if name else r"^.+\.v\d+$")
    for lay in store.list():
        if pat.match(lay.name) and lay.name not in keep and not any(lay.name in o.parents for o in store.list()):
            try:
                store.remove(lay.name)
                gone.append(lay.name)
            except (ValueError, OSError) as e:  # LayerError is a ValueError
                reg.g.log("kernel", f"layer build {lay.name} not removed: {e}", lay.name)
    return gone


def _follow(tree: str, rel: str) -> str | None:
    """The file `rel` names inside the layer `tree`, every component resolved with the tree as the
    root (a symlink, absolute or relative, at any depth, never leaves it). None: the layer does not
    hold such a file."""
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    done: list[str] = []
    hops = 0
    while parts:
        part = parts.pop(0)
        if part == "..":
            if done:
                done.pop()
            continue
        p = os.path.join(tree, *done, part)
        if os.path.islink(p):
            hops += 1
            if hops > 40:
                return None
            t = os.readlink(p)
            parts = [x for x in t.split("/") if x not in ("", ".")] + parts
            if t.startswith("/"):
                done = []
            continue
        if not os.path.lexists(p):
            return None
        done.append(part)
    p = os.path.join(tree, *done)
    return p if done else None


def resolve_command(name: str, trees: list[str]) -> str | None:
    """The host file a command name runs: a file a layer holds (top first), else the host's own
    command of that name. A layer's link to anything outside itself resolves to nothing."""
    if not CMD_RE.match(name):
        raise CapError(f"command {name!r}: a bare name (letters, digits, . _ + -)")
    for tree in trees:
        for d in sandbox.COMMAND_DIRS:
            if not os.path.lexists(os.path.join(tree, d, name)):
                continue
            p = _follow(tree, f"{d}/{name}")
            if p and os.path.isfile(p) and not os.path.islink(p) and os.access(p, os.X_OK):
                return p
    host = shutil.which(name, path=sandbox.HOST_PATH)
    return os.path.realpath(host) if host else None


# ── policy ───────────────────────────────────────────────────────────────

class PolicyKind(Kind):
    name = "policy"
    description = ("what a sandbox is: commands (a list, or ['*'] for all), egress (profiles it may reach through "
                   "the supervisor: pypi, npm, github, …), network (the host's, whole) and ports, limits (timeout, "
                   "memory_mb, cpus, tmp_mb, disk_mb, concurrent), layers (name@build; sys:name for the server's), "
                   "mounts [{source, target, rw}], exec_work (what is built in /work may run)")
    ttl = 30 * DAY

    def in_force_default(self, reg: Registry) -> dict[str, Any] | None:
        ws = _ws(reg)
        rec = reg.find("policy", ws.DEFAULT)
        return reg.version(rec)["spec"] if rec is not None and rec["attrs"].get("version") else None

    def defaults(self, reg: Registry) -> dict[str, Any]:
        """What a new policy starts from: the user's default as it is in force."""
        return {**_ws(reg).default_policy_spec(), **(self.in_force_default(reg) or {})}

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
            raise CapError("layers is a list of layer names (name, or name@version)")
        keep = {}
        rec = reg.find("policy", name)
        if rec is not None and rec["attrs"].get("version"):
            for p in reg.version(rec)["spec"].get("layers") or []:
                m = PIN_RE.match(p)
                if m and m.group(2):
                    keep[m.group(1)] = int(m.group(2))
        layers = [pin(reg, x, keep) for x in layers]
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
        spec["exec_work"] = bool(spec.get("exec_work"))
        eg = spec.get("egress") or []
        if not isinstance(eg, list) or not all(isinstance(x, str) for x in eg):
            raise CapError("egress is a list of egress profile names (cap kind=egress lists them)")
        for x in eg:
            reg.in_force("egress", x)
        spec["egress"] = sorted(set(eg))
        ports = spec.get("ports")
        if ports in (None, "any", ["any"]):
            ports = "any"
        else:
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
        """Against what is in force: the policy's own version, or for a new policy the user's default
        as it is in force (none: everything widens)."""
        if old is None:
            old = self.in_force_default(reg) or {"commands": [], "network": False, "mounts": [], "layers": [],
                                                 **{k: 0 for k in NUMBERS}}
        why = []
        oc, nc = set(old.get("commands") or []), set(new["commands"])
        if "*" in nc and "*" not in oc:
            why.append("every command")
        elif "*" not in nc and "*" not in oc and nc - oc:
            why.append("commands " + " ".join(sorted(nc - oc)))
        if new["network"] and not old.get("network"):
            why.append("the network")
        if new.get("exec_work") and not old.get("exec_work"):
            why.append("running what is built in /work")
        reach = set(new.get("egress") or []) - set(old.get("egress") or [])
        if reach:
            why.append("egress " + " ".join(sorted(reach)))
        if new["network"] and old.get("network"):
            op, np_ = old.get("ports"), new.get("ports")
            if op != "any" and (np_ == "any" or set(np_) - set(op or [])):
                why.append(f"ports {'any' if np_ == 'any' else ' '.join(map(str, sorted(set(np_) - set(op or []))))}")
        for k in NUMBERS:
            if float(new[k]) > float(old.get(k, 0)):
                why.append(f"{k} {old.get(k)} → {new[k]}")
        om = {(m["source"], m["target"], m["rw"]) for m in old.get("mounts") or []}
        for m in new["mounts"]:
            if (m["source"], m["target"], m["rw"]) not in om and (m["source"], m["target"], True) not in om:
                why.append(f"mount {m['source']} at {m['target']}{' read-write' if m['rw'] else ''}")
        added = set(new["layers"]) - set(old.get("layers") or [])
        if added:  # a layer, or another build of one: what the user approved is a build
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
        try:
            trees = layer_trees(reg, spec.get("layers") or [])
        except CapError:
            return None  # a layer the user approved is gone: that is for the user to answer
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
    description = ("binaries and data for the sandbox: a build script (body) run as root inside a sandbox of a "
                   "policy you already hold (its commands, network, limits and timeout), over its parents; spec "
                   "{policy, parents, description}. A policy stacks a layer at a build it pins (name@version).")
    ttl = 90 * DAY
    has_body = True

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        bad = set(spec) - {"policy", "parents", "description", "env"}
        if bad:
            raise CapError(f"unknown layer fields {sorted(bad)} (a build runs under its policy: its network, "
                           "limits and timeout)")
        ws = _ws(reg)
        spec.setdefault("policy", ws.DEFAULT)
        ws.policy(spec["policy"])  # in force: the build is a sandbox of that grant, never a wider one
        parents = spec.get("parents") or []
        if any(PIN_RE.match(p) and PIN_RE.match(p).group(1) == name for p in parents):
            raise CapError("a layer is not its own parent")
        spec["parents"] = [pin(reg, p) for p in parents]
        spec["description"] = str(spec.get("description", ""))
        env = spec.get("env") or {}
        if not isinstance(env, dict) or not all(re.fullmatch(r"[A-Z_][A-Z0-9_]*", k) and isinstance(v, str)
                                                for k, v in env.items()):
            raise CapError("env is {NAME: value}; $PATH (any $NAME) in a value expands to what is below")
        spec["env"] = env
        return spec

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        ws = _ws(reg)
        jid = ws.submit_build(rec["attrs"]["name"], ver)
        reg.g.update_node(rec["id"], actor="kernel", attrs={"building": jid, "build_error": None})
        ws.kick()

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        reg.g.update_node(rec["id"], actor="kernel", attrs={"built": None})
        prune_layers(reg, rec["attrs"]["name"])  # what a policy still pins is kept

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        a = rec["attrs"]
        if a.get("built") == ver["version"]:
            tree = _store(reg).tree(layer_dir(a["name"], ver["version"]))
            return ("pass", "") if Path(tree).is_dir() else ("fail", "its built tree is gone")
        if a.get("build_error"):
            return "fail", f"its build failed: {a['build_error']}"
        return "pending", ""

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description", "")


# ── egress ───────────────────────────────────────────────────────────────

# The protocols the kernel knows: package registries and source hosts a computation commonly needs.
# Seeded once per store (the user may change or remove them; the model may propose its own).
EGRESS_PROFILES = {
    "pypi": (["pypi.org", "files.pythonhosted.org"], "Python packages (pip, uv)"),
    "npm": (["registry.npmjs.org", "registry.yarnpkg.com"], "Node packages (npm, yarn, pnpm)"),
    "crates": (["crates.io", "index.crates.io", "static.crates.io"], "Rust crates (cargo)"),
    "github": (["github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                "raw.githubusercontent.com", "release-assets.githubusercontent.com"], "GitHub: git over https, releases"),
    "huggingface": (["huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co", "*.hf.co"],
                    "Hugging Face models and datasets"),
    "arxiv": (["arxiv.org", "export.arxiv.org"], "arXiv papers and metadata"),
    "python-tools": (["astral.sh", "github.com", "objects.githubusercontent.com",
                      "release-assets.githubusercontent.com"], "uv and its managed Pythons"),
    "nodejs": (["nodejs.org"], "Node.js releases"),
    "rustup": (["static.rust-lang.org", "sh.rustup.rs"], "the Rust toolchain (rustup)"),
}


class EgressKind(Kind):
    name = "egress"
    description = ("a protocol the sandbox may use to reach out, through the egress supervisor: hosts (exact, or "
                   "*.domain) and ports (default 443), https only (CONNECT); a policy lists the profiles it may use")
    ttl = 90 * DAY

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        from .egress import host_ok

        bad = set(spec) - {"hosts", "ports", "description"}
        if bad:
            raise CapError(f"unknown egress fields {sorted(bad)}")
        hosts = [str(h).lower() for h in spec.get("hosts") or []]
        if not hosts or not all(host_ok(h) for h in hosts):
            raise CapError("hosts: one or more host names (a.b.c, or *.b.c)")
        try:
            ports = sorted({int(p) for p in spec.get("ports") or [443]})
        except (TypeError, ValueError) as e:
            raise CapError("ports are TCP port numbers") from e
        if not all(0 < p < 65536 for p in ports):
            raise CapError("ports are TCP port numbers (1-65535)")
        return {"hosts": sorted(set(hosts)), "ports": ports, "description": str(spec.get("description") or name)}

    def widens(self, reg: Registry, old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
        oh, op = set((old or {}).get("hosts") or []), set((old or {}).get("ports") or [])
        why = []
        if set(new["hosts"]) - oh:
            why.append("hosts " + " ".join(sorted(set(new["hosts"]) - oh)))
        if set(new["ports"]) - op:
            why.append("ports " + " ".join(map(str, sorted(set(new["ports"]) - op))))
        return why

    def summary(self, spec: dict[str, Any]) -> str:
        return f"{spec.get('description', '')}: {' '.join(spec.get('hosts', []))}"


def egress_rules(reg: Registry, names: list[str]) -> Any:
    """What a job under these profiles may reach (only profiles in force count)."""
    from .egress import Rules

    allow, used = [], []
    for n in names:
        try:
            _, ver, _ = reg.in_force("egress", n)
        except CapError:
            continue
        used.append(n)
        allow += [(h, tuple(ver["spec"]["ports"])) for h in ver["spec"]["hosts"]]
    return Rules(allow=allow, names=used)


for _k in (PolicyKind(), ScriptKind(), LayerKind(), EgressKind()):
    register(_k)
