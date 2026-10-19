"""A user's sandbox workspace, shared by Chat sessions (the MCP tools) and agents (the runner):
policies, scripts and jobs as kernel nodes, files in a work tree, and the runner that executes jobs.

The rule every part follows is the kernel's: the model writes what is proposed, the user writes what
governs. Here that splits as

    policy  written by the user (or the kernel: the default). It IS the sandbox: the commands the
            sandbox shows, the network, the limits. Granted once, it covers every script that runs
            under it, so nothing asks again per script or per run.
    script  written by the model (or the user): an interpreter (a command of its policy) and a body.
            Adding or revising one needs no approval, because it can do nothing its policy does not
            already allow: what it can call is what the policy put in the sandbox.
    job     one run of one script version: queued by a tool call, executed by a runner (in this
            process for a local server, the runner unit for a remote one), its output kept as blobs.

Layout next to the store (<db> is the store's file, so local and remote stores alike get one):

    <db>.sandbox/work/            the workspace, /work inside the sandbox
    <db>.sandbox/jobs/<id>/       one job's root mount point, script and captured output
    <db>.sandbox/hostetc/         the host base's /etc (sandbox.prepare_hostetc)
    <db>.sandbox/queue/<id>       a marker per queued job, so a runner finds work without opening
                                  every store
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..kernel.graph import Conflict, Forbidden, Graph, KernelError
from ..store import Handbook, HandbookError
from . import sandbox

PKG = "sandbox"
VERSION = "1"
DEFAULT_POLICY = "default"
# The default policy's vocabulary: a coreutils-like set, a shell and Python for computation, no network.
# Only the commands installed on the host are kept.
DEFAULT_COMMANDS = (
    "sh bash cat ls head tail wc grep egrep sed awk sort uniq cut tr paste join comm fold fmt nl tac rev "
    "find xargs diff cmp date env echo printf test true false sleep timeout seq expr factor bc "
    "mkdir cp mv rm rmdir touch ln basename dirname realpath readlink stat du tee split csplit "
    "md5sum sha1sum sha256sum sha512sum base64 od hexdump tar gzip gunzip zcat xz bzip2 "
    "nproc id uname python3 jq"
).split()
JOB_STATES = {"queued": ["live"], "running": ["live"], "done": ["finished"], "failed": ["finished"],
              "cancelled": ["finished"], "lost": ["finished"]}
OUTPUT_CAP = 1 << 20  # bytes of stdout / stderr kept per job (the rest is cut from the middle)
NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_."


class WorkspaceError(HandbookError):
    pass


def _name(name: str, what: str) -> str:
    n = (name or "").strip().lower()
    if not n or len(n) > 64 or any(c not in NAME_CHARS for c in n) or n[0] in "-.":
        raise WorkspaceError(f"{what} name {name!r}: lowercase letters, digits, - _ . (up to 64)")
    return n


def install(g: Graph) -> None:
    if g.db.execute("SELECT value FROM k_meta WHERE key = 'pkg:sandbox'").fetchone() == (VERSION,):
        return
    with g.tx():
        g.define_type("policy", "node", actor="kernel", pkg=PKG,
                      description="What a sandbox is: its commands, network and limits. Written by the user.")
        g.define_type("script", "node", actor="kernel", pkg=PKG,
                      states={"active": ["live"], "retired": ["finished"]},
                      description="An interpreter of its policy and a body (a blob); runs as jobs.")
        g.define_type("job", "node", actor="kernel", pkg=PKG, states=JOB_STATES,
                      transitions=[("queued", "cancelled", "any")],
                      description="One run of one script version, executed by a runner.")
        g.db.execute("INSERT OR REPLACE INTO k_meta VALUES ('pkg:sandbox', ?)", (VERSION,))


def _du(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


class Workspace:
    """One store's sandbox: its policies, scripts, jobs and files. Every method that touches the
    store expects the caller to serialize access to the store's connection (the server's lock)."""

    def __init__(self, hb: Handbook, base: str | Path | None = None):
        from ..kernel import runtime

        self.hb = hb
        self.g = runtime.attach(hb).g
        install(self.g)
        if base is None:
            base = (Path(tempfile.mkdtemp(prefix="rhb-sandbox-")) if hb.path == ":memory:"
                    else Path(f"{hb.path}.sandbox"))
        self.base = Path(base)
        for d in ("work", "jobs", "queue"):
            (self.base / d).mkdir(parents=True, exist_ok=True)
        self.work = self.base / "work"
        self._ensure_default_policy()

    # ── policies: the user's grant, once ─────────────────────────────────

    def _ensure_default_policy(self) -> None:
        pid = f"policy:{DEFAULT_POLICY}"
        if self.g.get_node(pid) is None:
            commands = [c for c in DEFAULT_COMMANDS if shutil.which(c, path=sandbox.HOST_PATH)]
            self.g.put_node(pid, "policy", actor="kernel", content="the default: computation, no network",
                            attrs={"commands": commands, "network": False, "ports": [80, 443], "timeout": 120,
                                   "memory_mb": 2048, "cpus": 2.0, "tmp_mb": 512, "disk_mb": 2048, "concurrent": 2})

    def set_policy(self, name: str, *, actor: str, **attrs: Any) -> dict[str, Any]:
        """Grant or change a policy. Only the user's channel (the approval page, the CLI) calls
        this with actor='user'; the model cannot write a policy at all."""
        if actor == "model":
            raise Forbidden("a policy is the user's grant: the model cannot write one (ask the user to grant it "
                            "on the approval page)")
        name = _name(name, "policy")
        known = {"commands", "network", "ports", "timeout", "memory_mb", "cpus", "tmp_mb", "disk_mb", "concurrent",
                 "description"}
        bad = set(attrs) - known
        if bad:
            raise WorkspaceError(f"unknown policy fields {sorted(bad)}; known: {sorted(known)}")
        if "commands" in attrs:
            cmds = list(dict.fromkeys(attrs["commands"]))
            missing = [c for c in cmds if not shutil.which(c, path=sandbox.HOST_PATH)]
            if missing:
                raise WorkspaceError(f"not installed on the host: {', '.join(missing)}")
            attrs["commands"] = cmds
        if "ports" in attrs and attrs["ports"] is not None:
            ports = [int(x) for x in attrs["ports"]]
            if not all(0 < x < 65536 for x in ports):
                raise WorkspaceError("ports are TCP port numbers (1-65535)")
            attrs["ports"] = ports
        desc = attrs.pop("description", None)
        pid = f"policy:{name}"
        with self.g.tx():
            if self.g.get_node(pid) is None:
                base = dict(self.policy(DEFAULT_POLICY)["attrs"])
                base.update(attrs)
                self.g.put_node(pid, "policy", actor=actor, content=desc or name, attrs=base)
            else:
                self.g.update_node(pid, actor=actor, attrs=attrs, content=desc)
            self.g.log(actor, f"policy {name} granted: {json.dumps(attrs, sort_keys=True)}", pid)
        return self.policy(name)

    def policy(self, name: str) -> dict[str, Any]:
        n = self.g.get_node(f"policy:{_name(name, 'policy')}")
        if n is None:
            raise WorkspaceError(f"no policy {name!r}; policies: {', '.join(self.policies()) or 'none'}")
        if n["author"] == "model":  # cannot happen through this module; a forged row is not a grant
            raise Forbidden(f"policy {name!r} was not written by the user")
        return n

    def policies(self) -> list[str]:
        return [r[0].split(":", 1)[1] for r in
                self.g.db.execute("SELECT id FROM k_nodes WHERE type = 'policy' ORDER BY id")]

    # ── scripts: the model's, freely, within a policy ────────────────────

    def put_script(self, name: str, body: str, *, actor: str, interpreter: str = "sh", description: str = "",
                   policy: str = DEFAULT_POLICY) -> dict[str, Any]:
        name = _name(name, "script")
        pol = self.policy(policy)
        if interpreter not in pol["attrs"]["commands"]:
            raise WorkspaceError(f"interpreter {interpreter!r} is not a command of policy {policy!r} "
                                 f"({' '.join(pol['attrs']['commands'])})")
        if not body.strip():
            raise WorkspaceError("a script needs a body")
        sha = self.g.put_blob(body)
        sid = f"script:{name}"
        attrs = {"interpreter": interpreter, "blob": sha, "policy": _name(policy, "policy"), "size": len(body.encode())}
        with self.g.tx():
            old = self.g.get_node(sid)
            if old is None:
                self.g.put_node(sid, "script", actor=actor, state="active", content=description, attrs=attrs)
            else:
                if actor == "model" and old["author"] != "model":
                    raise Forbidden(f"script {name!r} is the user's: add yours under another name")
                self.g.update_node(sid, actor=actor, state="active", content=description or old["content"],
                                   attrs=attrs)
            self.g.log(actor, f"script {name} {'revised' if old else 'added'} ({sha[:12]})", sid)
        return self.script(name)

    def script(self, name: str) -> dict[str, Any]:
        n = self.g.get_node(f"script:{_name(name, 'script')}")
        if n is None:
            raise WorkspaceError(f"no script {name!r}; scripts: {', '.join(self.scripts()) or 'none'}")
        return n

    def scripts(self) -> list[str]:
        return [r[0].split(":", 1)[1] for r in self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'script' AND state = 'active' ORDER BY id")]

    def retire_script(self, name: str, *, actor: str) -> None:
        n = self.script(name)
        if actor == "model" and n["author"] != "model":
            raise Forbidden(f"script {name!r} is the user's")
        self.g.update_node(n["id"], actor=actor, state="retired")

    # ── jobs ─────────────────────────────────────────────────────────────

    def submit(self, name: str, args: list[str] | None = None, *, actor: str, timeout: float | None = None) -> str:
        s = self.script(name)
        pol = self.policy(s["attrs"]["policy"])
        if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args or []):
            raise WorkspaceError("args is a list of strings")
        limit = float(pol["attrs"]["timeout"])
        t = limit if timeout is None else float(timeout)
        if not 0 < t <= limit:
            raise WorkspaceError(f"timeout must be in (0, {limit:g}] s under policy {pol['id'][7:]!r}")
        used = _du(self.work) // (1 << 20)
        if used > int(pol["attrs"]["disk_mb"]):
            raise WorkspaceError(f"the workspace uses {used} MB, over the policy's {pol['attrs']['disk_mb']} MB: "
                                 "remove files first")
        jid = f"job:{secrets.token_hex(5)}"
        self.g.put_node(jid, "job", actor=actor, state="queued", content=name,
                        attrs={"script": name, "blob": s["attrs"]["blob"], "interpreter": s["attrs"]["interpreter"],
                               "policy": s["attrs"]["policy"], "args": list(args or []), "timeout": t,
                               "submitted": time.time()})
        (self.base / "queue" / jid[4:]).touch()
        return jid

    def job(self, jid: str) -> dict[str, Any]:
        jid = jid if jid.startswith("job:") else f"job:{jid}"
        n = self.g.get_node(jid)
        if n is None or n["type"] != "job":
            raise WorkspaceError(f"no job {jid!r}")
        return n

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [self.g.node(r[0]) for r in self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'job' ORDER BY created DESC LIMIT ?", (limit,))]

    def cancel(self, jid: str, *, actor: str) -> dict[str, Any]:
        j = self.job(jid)
        if j["state"] == "queued":
            self.g.update_node(j["id"], actor=actor, state="cancelled", expect=j["version"])
            (self.base / "queue" / j["id"][4:]).unlink(missing_ok=True)
        elif j["state"] == "running":
            self.g.update_node(j["id"], actor=actor, attrs={"cancel": True})
        return self.job(jid)

    def output(self, j: dict[str, Any], which: str = "stdout") -> str:
        sha = j["attrs"].get(which)
        return self.g.get_blob(sha).decode(errors="replace") if sha else ""

    # ── files ────────────────────────────────────────────────────────────
    # The sandbox writes the workspace, so the host never follows a name in it: every path is walked
    # one component at a time on directory descriptors, with no symlink followed (O_NOFOLLOW), and
    # only regular files are opened (O_NONBLOCK, then fstat), so a symlink swapped in by a running
    # job, or a FIFO, cannot steer or stall a call.

    @staticmethod
    def _parts(rel: str) -> list[str]:
        rel = (rel or ".").strip()
        rel = rel[len("/work"):] if rel == "/work" or rel.startswith("/work/") else rel
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise WorkspaceError(f"{rel!r} is outside the workspace (no '..')")
        return parts

    def _dir_fd(self, parts: list[str], create: bool = False) -> int:
        """A descriptor of the directory parts[...] beneath the workspace, symlinks refused."""
        fd = os.open(self.work, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            for name in parts:
                if create:
                    try:
                        os.mkdir(name, 0o755, dir_fd=fd)
                    except FileExistsError:
                        pass
                try:
                    nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                except (NotADirectoryError, OSError) as e:
                    raise WorkspaceError(f"{'/'.join(parts)!r}: {name!r} is not a directory of the workspace "
                                         f"(or is a symlink)") from e
                os.close(fd)
                fd = nxt
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _open_file(self, rel: str, flags: int, mode: int = 0o644) -> int:
        parts = self._parts(rel)
        if not parts:
            raise WorkspaceError("name a file")
        d = self._dir_fd(parts[:-1], create=bool(flags & os.O_CREAT))
        try:
            fd = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, mode, dir_fd=d)
        except OSError as e:
            raise WorkspaceError(f"{rel!r}: {e.strerror} (a symlink, a special file, or missing)") from e
        finally:
            os.close(d)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise WorkspaceError(f"{rel!r} is not a regular file")
        os.set_blocking(fd, True)
        return fd

    def ls(self, rel: str = ".") -> list[tuple[str, str, int]]:
        d = self._dir_fd(self._parts(rel))
        try:
            out = []
            with os.scandir(d) as it:
                for e in sorted(it, key=lambda e: e.name):
                    st = e.stat(follow_symlinks=False)
                    kind = ("link" if stat.S_ISLNK(st.st_mode) else "dir" if stat.S_ISDIR(st.st_mode)
                            else "file" if stat.S_ISREG(st.st_mode) else "special")
                    out.append((e.name, kind, st.st_size if kind == "file" else 0))
            return out
        finally:
            os.close(d)

    def read(self, rel: str, limit: int = 200_000) -> str:
        fd = self._open_file(rel, os.O_RDONLY)
        with os.fdopen(fd, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            data = f.read(limit + 1)
        text = data[:limit].decode(errors="replace")
        return text + (f"\n… (cut at {limit} bytes of {size})" if len(data) > limit else "")

    def write(self, rel: str, text: str) -> int:
        fd = self._open_file(rel, os.O_WRONLY | os.O_CREAT)
        with os.fdopen(fd, "w") as f:
            f.truncate(0)
            return f.write(text)

    def remove(self, rel: str) -> None:
        """Removes the name itself: a symlink is unlinked, never followed; a directory is removed with
        its contents (shutil.rmtree on descriptors, which follows no symlink)."""
        parts = self._parts(rel)
        if not parts:
            raise WorkspaceError("the workspace itself cannot be removed")
        d = self._dir_fd(parts[:-1])
        try:
            st = os.stat(parts[-1], dir_fd=d, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                shutil.rmtree(parts[-1], dir_fd=d)
            else:
                os.unlink(parts[-1], dir_fd=d)
        except FileNotFoundError as e:
            raise WorkspaceError(f"no {rel!r} in the workspace") from e
        finally:
            os.close(d)


# ── the runner ───────────────────────────────────────────────────────────


def _cap(data: bytes) -> bytes:
    if len(data) <= OUTPUT_CAP:
        return data
    half = OUTPUT_CAP // 2
    return data[:half] + f"\n… ({len(data) - OUTPUT_CAP} bytes cut) …\n".encode() + data[-half:]


class Runner:
    """Executes a store's queued jobs. Claiming is a compare-and-swap on the job's state, so two
    runners (or a runner and a restarted one) never run a job twice; a job a dead runner held is
    `lost` when its lease expires. Store access goes through `lock` (the server's call lock in the
    MCP process, a private one in the runner unit)."""

    def __init__(self, ws: Workspace, lock: threading.RLock | None = None, workers: int = 2, rid: str | None = None,
                 cgroups: bool | None = None):
        self.ws, self.lock = ws, lock or threading.RLock()
        if cgroups is None:
            cgroups = os.environ.get("RHB_CGROUPS", "1") != "0"
        # memory and cpu limits: a delegated cgroup subtree (the runner unit has Delegate=yes);
        # without one, rlimits (RLIMIT_AS for memory; no cpu share)
        self.cg = sandbox.Cgroups.prepare() if cgroups else None
        self.rid = rid or f"runner:{os.getpid()}:{secrets.token_hex(3)}"
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rhb-job")
        self.hostetc = ws.base / "hostetc"
        if not self.hostetc.exists():
            sandbox.prepare_hostetc(self.hostetc)

    def _claim(self) -> dict[str, Any] | None:
        with self.lock:
            for marker in sorted((self.ws.base / "queue").iterdir(), key=lambda p: p.stat().st_mtime):
                jid = f"job:{marker.name}"
                j = self.ws.g.get_node(jid)
                if j is None or j["state"] != "queued":
                    marker.unlink(missing_ok=True)
                    continue
                running = self.ws.g.db.execute("SELECT count(*) FROM k_nodes WHERE type = 'job' AND state = 'running'"
                                               " AND json_extract(attrs, '$.policy') = ?",
                                               (j["attrs"]["policy"],)).fetchone()[0]
                if running >= int(self.ws.policy(j["attrs"]["policy"])["attrs"].get("concurrent", 2)):
                    continue
                try:
                    self.ws.g.update_node(jid, actor="kernel", state="running", expect=j["version"],
                                          attrs={"runner": self.rid, "started": time.time(),
                                                 "lease": time.time() + j["attrs"]["timeout"] + 60})
                except Conflict:
                    continue
                marker.unlink(missing_ok=True)
                return self.ws.g.node(jid)
        return None

    def reap_lost(self) -> int:
        """Running jobs whose lease ran out belong to a runner that died."""
        n = 0
        with self.lock:
            for (jid,) in self.ws.g.db.execute("SELECT id FROM k_nodes WHERE type = 'job' AND state = 'running' "
                                               "AND json_extract(attrs, '$.lease') < ?", (time.time(),)).fetchall():
                self.ws.g.update_node(jid, actor="kernel", state="lost", attrs={"finished": time.time()})
                n += 1
        return n

    def poll(self) -> int:
        """Start every job that can start now; returns how many."""
        started = 0
        while (j := self._claim()) is not None:
            self.pool.submit(self._execute, j)
            started += 1
        return started

    def run_now(self, jid: str) -> dict[str, Any]:
        """Claim and execute one job in this thread (tests, `script test`)."""
        while True:
            j = self._claim()
            if j is None:
                break
            if j["id"] == jid:
                self._execute(j)
                break
            self.pool.submit(self._execute, j)
        with self.lock:
            return self.ws.job(jid)

    def _spec(self, j: dict[str, Any], jobdir: Path) -> sandbox.Spec:
        with self.lock:
            pol = self.ws.policy(j["attrs"]["policy"])["attrs"]
        (jobdir / "root").mkdir(parents=True, exist_ok=True)
        script = jobdir / "script"
        with self.lock:
            script.write_bytes(self.ws.g.get_blob(j["attrs"]["blob"]))
        interp = j["attrs"]["interpreter"]
        limits = sandbox.Limits(memory_mb=int(pol["memory_mb"]), cpus=float(pol["cpus"]), tmp_mb=int(pol["tmp_mb"]),
                                address_space=self.cg is None)
        leaf = str(self.cg.leaf(j["id"][4:], limits)) if self.cg is not None else None
        return sandbox.Spec(
            argv=[f"/usr/bin/{interp}", "/job/script", *j["attrs"]["args"]],
            root=str(jobdir / "root"), work=str(self.ws.work), hostetc=str(self.hostetc),
            binds_ro=[(str(script), "/job/script")], network=bool(pol["network"]),
            ports=list(pol.get("ports") or [80, 443]) if pol["network"] else None,
            timeout=float(j["attrs"]["timeout"]), commands=list(pol["commands"]), limits=limits, cgroup=leaf)

    def _execute(self, j: dict[str, Any]) -> None:
        jobdir = self.ws.base / "jobs" / j["id"][4:]
        jobdir.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {}
        try:
            spec = self._spec(j, jobdir)
            (jobdir / "spec.json").write_text(spec.to_json())
            with self.lock:
                disk_mb = int(self.ws.policy(j["attrs"]["policy"])["attrs"]["disk_mb"])
            with open(jobdir / "stdout", "wb") as out, open(jobdir / "stderr", "wb") as err:
                p = subprocess.Popen(sandbox.command(str(jobdir / "spec.json")), stdout=out, stderr=err,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
                ticks = 0
                while True:
                    try:
                        code = p.wait(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        ticks += 1
                        with self.lock:
                            cancel = self.ws.g.node(j["id"])["attrs"].get("cancel")
                        if cancel and not result.get("cancelled"):
                            p.send_signal(signal.SIGTERM)  # the launcher kills the namespace's pid 1
                            result["cancelled"] = True
                        if ticks % 10 == 0 and _du(self.ws.work) > disk_mb << 20 and not result.get("error"):
                            p.send_signal(signal.SIGTERM)  # the workspace is over the policy's disk
                            result["error"] = f"stopped: the workspace went over the policy's {disk_mb} MB"
            result["exit"] = code
            state = ("cancelled" if result.get("cancelled") else "failed" if result.get("error")
                     else "done" if code == 0 else "failed")
        except Exception as e:  # noqa: BLE001 — a runner never dies of one job
            state, result["error"] = "failed", f"{type(e).__name__}: {e}"
        if self.cg is not None:
            sandbox.Cgroups.remove(self.cg.base / j["id"][4:])
        for attempt in range(5):  # the result must land: a busy store is waited out, not dropped
            try:
                with self.lock:
                    for which in ("stdout", "stderr"):
                        f = jobdir / which
                        if f.exists():
                            data = f.read_bytes()
                            result[which] = self.ws.g.put_blob(_cap(data))
                            result[f"{which}_bytes"] = len(data)
                    result["finished"] = time.time()
                    self.ws.g.update_node(j["id"], actor="kernel", state=state, attrs=result)
                break
            except KernelError:
                break  # the job moved on (reaped as lost): nothing to record
            except sqlite3.OperationalError:
                time.sleep(1 + attempt)
        shutil.rmtree(jobdir, ignore_errors=True)

    def close(self) -> None:
        self.pool.shutdown(wait=True)
