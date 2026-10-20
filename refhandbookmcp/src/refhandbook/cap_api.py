"""The capability tools: `cap` for every kind of record, and `run` / `job` / `files` for the sandbox.

Plain functions, like research_api: the MCP server registers them and the CLI can call them. A tool
call is the model's (actor `model`). The model keeps its own capabilities up to date: it adds,
revises, deprecates, removes and restores its scripts, aliases, layers, cards and rules freely; a
version that widens a grant (a policy with more commands, the network, a mount; a layer built with
the network) waits for the user's approval on the approval page. Nothing asks per run.

Every record has a TTL. The sweep (at most once a minute, on these calls and in the runner) reviews
what is due: a record whose check passes renews itself, one that fails is deprecated with the
reason, and a deprecated one retires after its grace, keeping its history.

Runs are jobs. `run` queues one and waits a little; a job that outlasts the wait keeps running and is
read later with `job`. Where it runs: in this process for a local server (RHB_RUNNER=inprocess, the
default), or in the runner unit for a remote one (RHB_RUNNER=external).

The sandbox_* tools and research_review's rule proposals are deprecated aliases of these: they work,
with a warning, until their alias records retire.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, Literal

from .agents.workspace import DEFAULT_POLICY, Runner, Workspace, WorkspaceError
from .kernel.capabilities import DAY, KINDS, CapError, Registry
from .store import Handbook

_resolve: Callable[[], Handbook] | None = None
_lock: threading.RLock = threading.RLock()
_spaces: dict[int, Workspace] = {}
_runners: dict[int, tuple[Runner, threading.Thread]] = {}
SHOW = 20_000  # characters of output a tool result shows
MAX_WAIT = 50.0

# Tools kept under their old names, each an alias record (kind alias, owner kernel) that retires
# after DEPRECATION; until then the old name works and says what replaces it.
DEPRECATION = 30 * DAY
DEPRECATED_TOOLS = {
    "sandbox_script": ("cap(kind='script', action=add|update|show|list|remove|history, …); run(name, args) for test",
                       {"kind": "script"}),
    "sandbox_policy": ("cap(kind='policy', action='list' or 'show', name=…)", {"kind": "policy"}),
    "sandbox_run": ("run(name, args, wait, timeout)", {}),
    "sandbox_job": ("job(action, id, …)", {}),
    "sandbox_files": ("files(action, path, …)", {}),
    "research_review_rules": ("cap(kind='rule', action='add'|'update'|'list', name=<rule id>, spec={phase, body, "
                              "message, severity, replaces}); research_review records the review only", {"kind": "rule"}),
}


def configure(resolve: Callable[[], Handbook], lock: threading.RLock) -> None:
    """The server's store resolver and its call lock. Every store access here holds the lock (it is
    re-entrant: a tool call already holds it once); a tool waiting for a job lets go of it entirely,
    so other calls, and the runner's threads, go on."""
    global _resolve, _lock
    _resolve, _lock = resolve, lock


def _locked(fn: Callable[..., str]) -> Callable[..., str]:
    import functools

    @functools.wraps(fn)
    def tool(*args: Any, **kwargs: Any) -> str:
        with _lock:
            return fn(*args, **kwargs)

    return tool


def W() -> Workspace:
    if _resolve is None:
        raise WorkspaceError("the capability tools are not configured")
    hb = _resolve()
    ws = _spaces.get(id(hb))
    if ws is None or ws.hb is not hb:
        ws = _spaces[id(hb)] = Workspace(hb)
        ws.on_queue = lambda: _ensure_runner(ws)
        ensure_deprecations(ws.caps)
    return ws


def ensure_deprecations(caps: Registry) -> None:
    """The alias records of the deprecated tool names, once per store: deprecated from the start,
    retiring DEPRECATION after this store first saw them."""
    g = caps.g
    for old, (new, fixed) in DEPRECATED_TOOLS.items():
        mark = f"cap:deprecated-tool:{old}"
        if g.db.execute("SELECT 1 FROM k_meta WHERE key = ?", (mark,)).fetchone():
            continue  # created once: once it retires (and is purged), the old name stays gone
        with g.tx():
            g.db.execute("INSERT INTO k_meta VALUES (?, ?)", (mark, repr(time.time())))
        name = old.replace("_", "-")
        if caps.find("alias", name) is not None:
            continue
        caps.add("alias", name, spec={"target": "tool:" + new.split("(")[0], "fixed": fixed,
                                      "description": f"the old tool {old}: use {new}"}, actor="kernel")
        rec = caps.get("alias", name)
        g.update_node(rec["id"], actor="kernel", state="deprecated",
                         attrs={"reason": f"{old} is replaced by {new}", "retire_at": time.time() + DEPRECATION})


def deprecated(old: str, caps: Registry | None = None) -> str:
    """The warning line for a call under an old name, or a refusal once its alias has retired."""
    caps = caps or W().caps
    ensure_deprecations(caps)
    rec = caps.find("alias", old.replace("_", "-"))
    new = DEPRECATED_TOOLS[old][0]
    if rec is None or rec["state"] == "retired":
        raise CapError(f"{old} has been removed: use {new}")
    when = time.strftime("%Y-%m-%d", time.localtime(rec["attrs"].get("retire_at") or time.time()))
    return f"DEPRECATED {old}: use {new} (this name stops working {when})"


def _inprocess() -> bool:
    return os.environ.get("RHB_RUNNER", "inprocess") == "inprocess"


def _ensure_runner(ws: Workspace) -> None:
    if not _inprocess():
        return
    entry = _runners.get(id(ws))
    if entry is not None and entry[1].is_alive():
        return
    runner = Runner(ws, lock=_lock)
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(0.3):
            try:
                runner.reap_lost()
                runner.poll()
                with _lock:
                    if ws.caps.due():
                        ws.caps.sweep()
            except Exception:  # noqa: BLE001 — keep polling; a job's failure is recorded on the job
                pass

    t = threading.Thread(target=loop, name="rhb-runner", daemon=True)
    t.start()
    _runners[id(ws)] = (runner, t)


@contextlib.contextmanager
def _waiting() -> Iterator[None]:
    """Let go of the lock entirely (however many times this thread holds it), then take it back."""
    state = _lock._release_save()  # type: ignore[attr-defined]  (threading.Condition's own primitive)
    try:
        yield
    finally:
        _lock._acquire_restore(state)  # type: ignore[attr-defined]


def _render(ws: Workspace, j: dict[str, Any], show: int = SHOW) -> str:
    a = j["attrs"]
    head = f"{j['id']} {a.get('script')} {' '.join(a.get('args', []))}".rstrip() + f": {j['state']}"
    if j["state"] in ("done", "failed", "cancelled", "lost"):
        took = (a.get("finished", 0) - a.get("started", a.get("finished", 0))) if a.get("started") else 0
        head += f" (exit {a.get('exit', '-')}, {took:.1f} s)" + (f" — {a['error']}" if a.get("error") else "")
        out = [head]
        for which in ("stdout", "stderr"):
            text = ws.output(j, which)
            if text:
                cut = f"\n… {len(text) - show} more characters: job(action='output', id='{j['id']}', " \
                      f"which='{which}', offset={show})" if len(text) > show else ""
                out.append(f"--- {which} ({a.get(which + '_bytes', len(text))} bytes)\n{text[:show]}{cut}")
        return "\n".join(out)
    return head + f" — read it later with job(action='status', id='{j['id']}')"


def _wait(ws: Workspace, jid: str, wait: float) -> dict[str, Any]:
    deadline = time.monotonic() + min(max(wait, 0.0), MAX_WAIT)
    while True:
        j = ws.job(jid)
        if j["state"] not in ("queued", "running") or time.monotonic() >= deadline:
            return j
        with _waiting():
            time.sleep(0.2)


def _sweep(ws: Workspace) -> list[str]:
    return ws.caps.sweep() if ws.caps.due() else []


# ── rendering records ────────────────────────────────────────────────────

def _day(t: float | None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t)) if t else "-"


def _line(rec: dict[str, Any]) -> str:
    a = rec["attrs"]
    bits = [f"{a['kind']} {a['name']} v{a.get('version') or '-'} {rec['state']} [{rec['author']}]"]
    if rec["content"]:
        bits.append(rec["content"][:120])
    if a.get("pending"):
        bits.append(f"v{a['pending']} awaits the user's approval")
    if rec["state"] == "deprecated":
        bits.append(f"{a.get('reason')}" + (f" → {a['replaced_by']}" if a.get("replaced_by") else "")
                    + f"; retires {_day(a.get('retire_at'))}")
    elif rec["state"] == "active":
        bits.append(f"review {_day(a.get('review_after'))}")
    if a.get("building"):
        bits.append(f"building ({a['building']})")
    if a.get("build_error"):
        bits.append(f"build failed: {a['build_error'][:200]}")
    return " · ".join(bits)


def _show(ws: Workspace, kind: str, name: str) -> str:
    caps = ws.caps
    rec = caps.get(kind, name)
    out = [_line(rec)]
    for label, v in (("in force", rec["attrs"].get("version")), ("awaiting approval", rec["attrs"].get("pending"))):
        if not v:
            continue
        ver = caps.version(rec, v)
        out.append(f"--- v{v} ({label}; by {ver['author']}, {_day(ver['created'])}{'; ' + ver['note'] if ver['note'] else ''})")
        out.append(json.dumps(ver["spec"], ensure_ascii=False, indent=1, sort_keys=True))
        if ver["body"]:
            body = ver["body"]
            out.append(body[:SHOW] + (f"\n… {len(body) - SHOW} more characters" if len(body) > SHOW else ""))
    return "\n".join(out)


# ── tools ────────────────────────────────────────────────────────────────

def cap(action: Literal["kinds", "list", "show", "add", "update", "deprecate", "remove", "restore", "history",
                        "review"] = "list",
        kind: str = "", name: str = "", spec: dict[str, Any] | None = None, body: str = "", ref: str = "",
        note: str = "", why: str = "", replaced_by: str = "", version: int = 0, replace: bool = False,
        ttl_days: float | None = None, retired: bool = False) -> str:
    """Your capabilities, one family for every kind: script, policy, layer, alias, rule, card (`kinds`
    lists them). Each record is versioned (versions are never rewritten), has an owner, and a TTL.
    list (kind optional; retired=true shows retired ones) · show (the version in force, and one waiting
    for approval) · add / update (spec, and body or a blob ref for scripts and layers; update merges
    spec into the latest version unless replace=true) · deprecate (why, replaced_by: it keeps
    working, with a warning, then retires) · remove (retire now; history kept) · restore (version:
    bring back a retired or older version, as a new version) · history · review (run its check now;
    without a name, review everything due).
    You change your own records freely, and the user's not at all (add yours under another name). A
    version that widens a grant (a policy's commands, network, mounts, limits or layers; a layer built
    with the network) waits for the user's approval; everything else is in force at once. Keep
    records current: when a review deprecates one, fix it (update) or retire it (remove)."""
    ws = W()
    caps = ws.caps
    swept = _sweep(ws)
    head = [f"SWEEP {e}" for e in swept]
    if action == "kinds":
        return "\n".join(head + [f"{k.name}: {k.description} (review every {k.ttl / DAY:g} days"
                                 f"{', has a body' if k.has_body else ''})" for k in sorted(KINDS.values(), key=lambda k: k.name)])
    if action == "list":
        states = ("proposed", "active", "deprecated", "retired") if retired else ("proposed", "active", "deprecated")
        recs = caps.list(kind or None, states)
        sig = ws.g.db.execute("SELECT value FROM k_meta WHERE key = 'cap:signals'").fetchone()
        tail = [f"{sig[0]} record(s) have failed a review so far (cap action=review shows what is due)"] if sig else []
        return "\n".join(head + [_line(r) for r in recs] + tail) or "No records yet. cap(action='kinds') lists the kinds."
    if not kind:
        raise CapError(f"{action} needs kind (one of {', '.join(sorted(KINDS))})")
    if action == "review":
        if not name:
            return "\n".join([f"SWEEP {e}" for e in caps.sweep(force=True)] or ["nothing was due"])
        return "\n".join(head + [caps.review_now(kind, name, actor="model")])
    if not name:
        raise CapError(f"{action} needs name")
    if action == "show":
        return "\n".join(head + [_show(ws, kind, name)])
    if action == "history":
        rows = caps.history(kind, name)
        rec = caps.get(kind, name)
        return "\n".join(head + [_line(rec)] + [
            f"v{v['version']} {_day(v['created'])} by {v['author']}{' — ' + v['note'] if v['note'] else ''}"
            + (" (in force)" if v["version"] == rec["attrs"].get("version") else "")
            + (" (awaiting approval)" if v["version"] == rec["attrs"].get("pending") else "") for v in rows])
    if ref:
        if body:
            raise CapError("pass body or ref, not both")
        body = ws.g.get_blob(ref).decode()
    if ttl_days is not None and ttl_days < 1:
        raise CapError("ttl_days is at least 1: every record is reviewed")
    if action == "add":
        _, msg = caps.add(kind, name, spec=spec, body=body or None, actor="model", note=note,
                          ttl=ttl_days * DAY if ttl_days is not None else None)
        return "\n".join(head + [msg])
    if action == "update":
        if ttl_days is not None:
            rec = caps.get(kind, name)
            caps._may(rec, "model")
            ws.g.update_node(rec["id"], actor="kernel", attrs={"ttl": ttl_days * DAY})
        if spec is None and not body and not replace and ttl_days is not None:
            return "\n".join(head + [f"{kind} {name}: reviewed every {ttl_days:g} days from its next review"])
        _, msg = caps.update(kind, name, spec=spec, body=body or None, actor="model", note=note, replace=replace)
        return "\n".join(head + [msg])
    if action == "deprecate":
        return "\n".join(head + [caps.deprecate(kind, name, actor="model", why=why, replaced_by=replaced_by)])
    if action == "remove":
        return "\n".join(head + [caps.remove(kind, name, actor="model", why=why)])
    if action == "restore":
        _, msg = caps.restore(kind, name, actor="model", version=version or None)
        return "\n".join(head + [msg])
    raise CapError(f"unknown action {action!r}")


def run(name: str, args: list[str] | None = None, wait: float = 20.0, timeout: float | None = None) -> str:
    """Run a script (or an alias of one) as a background job. Returns the result if it finishes
    within `wait` seconds (at most 50); otherwise the job id, and the job keeps running while you do
    other work (read it with job). `timeout` bounds the run (at most the policy's). /work is your
    workspace (files); the policy says what else the sandbox holds (its commands, layers, mounts,
    network)."""
    ws = W()
    _sweep(ws)
    warn = []
    args = list(args or [])
    alias = ws.caps.find("alias", name)
    if alias is not None and ws.caps.find("script", name) is None:
        rec, ver, w = ws.caps.in_force("alias", name)
        warn += [w] if w else []
        kind_, _, target = ver["spec"]["target"].partition(":")
        if kind_ != "script":
            raise CapError(f"alias {name} names a tool ({target}), not a script: call that tool")
        name, args = target, list(ver["spec"].get("args") or []) + args
    _, _, w = ws.caps.in_force("script", name)
    warn += [w] if w else []
    jid = ws.submit(name, args, actor="model", timeout=timeout)
    _ensure_runner(ws)
    return "\n".join(warn + [_render(ws, _wait(ws, jid, wait))])


def job(action: Literal["status", "output", "cancel", "list", "wait"] = "list", id: str = "",
        which: Literal["stdout", "stderr"] = "stdout", offset: int = 0, wait: float = 20.0) -> str:
    """Jobs. list: the recent ones. status: one job, with its output if finished. wait: wait up to
    `wait` seconds for it. output: its full stdout or stderr from `offset`. cancel: stop it."""
    ws = W()
    if action == "list":
        js = ws.jobs()
        return "\n".join(f"{j['id']}  {j['state']:9} {j['attrs'].get('script')} {' '.join(j['attrs'].get('args', []))}"
                         for j in js) or "No jobs yet."
    if action == "status":
        return _render(ws, ws.job(id))
    if action == "wait":
        _ensure_runner(ws)
        return _render(ws, _wait(ws, ws.job(id)["id"], wait))
    if action == "output":
        text = ws.output(ws.job(id), which)
        chunk = text[offset:offset + 200_000]
        more = len(text) - offset - len(chunk)
        return chunk + (f"\n… {more} more characters from offset {offset + len(chunk)}" if more > 0 else "")
    if action == "cancel":
        return _render(ws, ws.cancel(id, actor="model"))
    raise WorkspaceError(f"unknown action {action!r}")


def files(action: Literal["ls", "read", "write", "remove"] = "ls", path: str = ".", text: str = "",
          ref: str = "") -> str:
    """Files in your workspace (/work inside the sandbox). ls a directory, read a file, write `text`
    (or a blob `ref`) to a file, remove a file or directory."""
    ws = W()
    if action == "ls":
        rows = ws.ls(path)
        return "\n".join(f"{kind:4} {size:>10}  {name}" for name, kind, size in rows) or "(empty)"
    if action == "read":
        return ws.read(path)
    if action == "write":
        if ref:
            if text:
                raise WorkspaceError("pass text or ref, not both")
            text = ws.g.get_blob(ref).decode()
        return f"wrote {ws.write(path, text)} characters to /work/{path.lstrip('/')}"
    if action == "remove":
        ws.remove(path)
        return f"removed /work/{path.lstrip('/')}"
    raise WorkspaceError(f"unknown action {action!r}")


# ── the old names ────────────────────────────────────────────────────────

def sandbox_script(action: Literal["add", "update", "show", "list", "retire", "test"], name: str = "",
                   body: str = "", ref: str = "", interpreter: str = "sh", description: str = "",
                   policy: str = DEFAULT_POLICY, args: list[str] | None = None) -> str:
    """DEPRECATED: use cap(kind='script', …) and run(…). Works until its alias retires."""
    warn = deprecated("sandbox_script")
    if action == "list":
        out = cap("list", kind="script")
    elif action in ("add", "update"):
        ws = W()
        if ref:
            body = ws.g.get_blob(ref).decode()
        ws.put_script(name, body, actor="model", interpreter=interpreter, description=description, policy=policy)
        out = f"script {name} saved ({len(body.encode())} bytes, {interpreter}, policy {policy})"
    elif action == "show":
        out = cap("show", kind="script", name=name)
    elif action == "retire":
        out = cap("remove", kind="script", name=name, why="retired through sandbox_script")
    elif action == "test":
        out = run(name, args or [], wait=MAX_WAIT)
    else:
        raise WorkspaceError(f"unknown action {action!r}")
    return f"{warn}\n{out}"


def sandbox_run(script: str, args: list[str] | None = None, wait: float = 20.0, timeout: float | None = None) -> str:
    """DEPRECATED: use run(name, args, wait, timeout)."""
    return f"{deprecated('sandbox_run')}\n{run(script, args, wait, timeout)}"


def sandbox_job(action: Literal["status", "output", "cancel", "list", "wait"] = "list", id: str = "",
                which: Literal["stdout", "stderr"] = "stdout", offset: int = 0, wait: float = 20.0) -> str:
    """DEPRECATED: use job(action, id, …)."""
    return f"{deprecated('sandbox_job')}\n{job(action, id, which, offset, wait)}"


def sandbox_files(action: Literal["ls", "read", "write", "remove"] = "ls", path: str = ".", text: str = "",
                  ref: str = "") -> str:
    """DEPRECATED: use files(action, path, …)."""
    return f"{deprecated('sandbox_files')}\n{files(action, path, text, ref)}"


def sandbox_policy(name: str = "") -> str:
    """DEPRECATED: use cap(kind='policy', action='list' or 'show', name=…)."""
    warn = deprecated("sandbox_policy")
    return f"{warn}\n" + (cap("show", kind="policy", name=name) if name else cap("list", kind="policy"))


def _ports(p: Any) -> str:
    return "any" if p in (None, "any") else " ".join(map(str, p))


def policy_text(ws: Workspace, name: str = "") -> str:
    """The policies in force, for the server's terminal."""
    out = []
    for n in [name] if name else ws.policies():
        p = ws.policy(n)
        a = p["attrs"]
        rec = ws.caps.find("policy", n)
        out.append(f"{n} (v{rec['attrs'].get('version') if rec else '?'}, by {rec['author'] if rec else p['author']}): "
                   f"{p['content']}\n  network {'yes' if a['network'] else 'no'}"
                   f"{' ports ' + _ports(a.get('ports')) if a['network'] else ''} · "
                   f"timeout {a['timeout']:g} s · memory {a['memory_mb']} MB · cpus {a['cpus']} · disk {a['disk_mb']} MB · "
                   f"{a.get('concurrent', 2)} at once\n  commands: {' '.join(a['commands'])}"
                   + (f"\n  layers: {' '.join(a['layers'])}" if a.get("layers") else "")
                   + "".join(f"\n  mount {m['source']} at {m['target']}{' (rw)' if m['rw'] else ''}"
                             for m in a.get("mounts") or []))
    return "\n".join(out)


READ_TOOLS: list[Callable[..., str]] = []
WRITE_TOOLS = [_locked(f) for f in (cap, run, job, files)]
DEPRECATED = [_locked(f) for f in (sandbox_script, sandbox_run, sandbox_job, sandbox_files, sandbox_policy)]
globals().update({f.__name__: f for f in WRITE_TOOLS + DEPRECATED})
TOOLS = {f.__name__: f for f in WRITE_TOOLS + DEPRECATED}
