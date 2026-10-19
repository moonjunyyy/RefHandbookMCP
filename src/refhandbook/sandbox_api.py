"""The sandbox tools: scripts, runs, jobs and files in the user's workspace (agents/workspace.py).

Plain functions, like research_api: the MCP server registers them and the CLI can call them. A tool
call is the model's (actor `model`): it may add and revise scripts and run them, never change a
policy; the policy, granted by the user, is what the sandbox can do.

Runs are jobs. `sandbox_run` queues one and waits a little (wait=…); a job that outlasts the wait
keeps running and is read later with `sandbox_job`, so long computations go on while the
conversation does other work. Where the job runs: in this process for a local server
(RHB_RUNNER=inprocess, the default), or in the runner unit for a remote one (RHB_RUNNER=external,
since the MCP service may not create namespaces).
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, Literal

from .agents.workspace import DEFAULT_POLICY, Runner, Workspace, WorkspaceError
from .store import Handbook

_resolve: Callable[[], Handbook] | None = None
_lock: threading.RLock = threading.RLock()
_spaces: dict[int, Workspace] = {}
_runners: dict[int, tuple[Runner, threading.Thread]] = {}
SHOW = 20_000  # characters of output a tool result shows
MAX_WAIT = 50.0


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
        raise WorkspaceError("the sandbox tools are not configured")
    hb = _resolve()
    ws = _spaces.get(id(hb))
    if ws is None or ws.hb is not hb:
        ws = _spaces[id(hb)] = Workspace(hb)
    return ws


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
                cut = f"\n… {len(text) - show} more characters: sandbox_job(action='output', id='{j['id']}', " \
                      f"which='{which}', offset={show})" if len(text) > show else ""
                out.append(f"--- {which} ({a.get(which + '_bytes', len(text))} bytes)\n{text[:show]}{cut}")
        return "\n".join(out)
    return head + f" — read it later with sandbox_job(action='status', id='{j['id']}')"


def _wait(ws: Workspace, jid: str, wait: float) -> dict[str, Any]:
    deadline = time.monotonic() + min(max(wait, 0.0), MAX_WAIT)
    while True:
        j = ws.job(jid)
        if j["state"] not in ("queued", "running") or time.monotonic() >= deadline:
            return j
        with _waiting():
            time.sleep(0.2)


# ── tools ────────────────────────────────────────────────────────────────

def sandbox_script(action: Literal["add", "update", "show", "list", "retire", "test"], name: str = "",
                   body: str = "", ref: str = "", interpreter: str = "sh", description: str = "",
                   policy: str = DEFAULT_POLICY, args: list[str] | None = None) -> str:
    """Your scripts in the user's sandbox. add / update: store `body` (or a blob `ref`) under `name`,
    run by `interpreter` (a command of the policy: sh, bash, python3, …); no approval is needed, as a
    script can only use what its policy (granted by the user) puts in the sandbox. show: its body.
    list: every script. retire: remove it from use. test: run it now with `args` and wait for the
    result (as sandbox_run with wait)."""
    ws = W()
    if action == "list":
        names = ws.scripts()
        if not names:
            return "No scripts yet. Add one with action='add'."
        return "\n".join(f"{n}  [{ws.script(n)['attrs']['interpreter']}, policy {ws.script(n)['attrs']['policy']}]  "
                         f"{ws.script(n)['content']}" for n in names)
    if action in ("add", "update"):
        if ref:
            if body:
                raise WorkspaceError("pass body or ref, not both")
            body = ws.g.get_blob(ref).decode()
        s = ws.put_script(name, body, actor="model", interpreter=interpreter, description=description, policy=policy)
        return f"script {name} saved ({s['attrs']['size']} bytes, {interpreter}, policy {s['attrs']['policy']})"
    if action == "show":
        s = ws.script(name)
        return (f"script {name} [{s['attrs']['interpreter']}, policy {s['attrs']['policy']}] {s['content']}\n"
                + ws.g.get_blob(s["attrs"]["blob"]).decode(errors="replace"))
    if action == "retire":
        ws.retire_script(name, actor="model")
        return f"script {name} retired"
    if action == "test":
        return sandbox_run(name, args or [], wait=MAX_WAIT)
    raise WorkspaceError(f"unknown action {action!r}")


def sandbox_run(script: str, args: list[str] | None = None, wait: float = 20.0, timeout: float | None = None) -> str:
    """Run a script as a background job. Returns the result if it finishes within `wait` seconds
    (at most 50); otherwise the job id, and the job keeps running while you do other work (read it
    with sandbox_job). `timeout` bounds the run (at most the policy's). /work is the user's
    workspace (sandbox_files); there is no network unless the policy grants it."""
    ws = W()
    jid = ws.submit(script, list(args or []), actor="model", timeout=timeout)
    _ensure_runner(ws)
    return _render(ws, _wait(ws, jid, wait))


def sandbox_job(action: Literal["status", "output", "cancel", "list", "wait"] = "list", id: str = "",
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


def sandbox_files(action: Literal["ls", "read", "write", "remove"] = "ls", path: str = ".", text: str = "",
                  ref: str = "") -> str:
    """Files in the user's workspace (/work inside the sandbox). ls a directory, read a file, write
    `text` (or a blob `ref`) to a file, remove a file or directory."""
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


def sandbox_policy(name: str = "") -> str:
    """The policies the user granted: what each sandbox can run (commands), its network and limits.
    Read-only: a policy is changed by the user on the approval page (/agents on the server's site)."""
    ws = W()
    names = [name] if name else ws.policies()
    out = []
    for n in names:
        p = ws.policy(n)
        a = p["attrs"]
        out.append(f"{n} (by {p['author']}): {p['content']}\n  network {'yes' if a['network'] else 'no'} · timeout "
                   f"{a['timeout']} s · memory {a['memory_mb']} MB · cpus {a['cpus']} · disk {a['disk_mb']} MB · "
                   f"{a.get('concurrent', 2)} at once\n  commands: {' '.join(a['commands'])}")
    return "\n".join(out)


READ_TOOLS = [_locked(sandbox_policy)]
WRITE_TOOLS = [_locked(f) for f in (sandbox_script, sandbox_run, sandbox_job, sandbox_files)]
globals().update({f.__name__: f for f in READ_TOOLS + WRITE_TOOLS})
TOOLS = {f.__name__: f for f in READ_TOOLS + WRITE_TOOLS}
