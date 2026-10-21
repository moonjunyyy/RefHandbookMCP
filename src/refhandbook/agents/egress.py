"""The egress supervisor: the sandbox's only way out, and only by protocols it knows.

A sandbox has its own network namespace with nothing in it but loopback. When its policy names
egress profiles (capability kind `egress`: named sets of hosts and ports, e.g. `pypi`, `npm`,
`github`), the runner opens a unix socket for that one job and binds its directory at
/run/egress inside; a relay in the sandbox listens on 127.0.0.1:3128 and passes each connection
to the socket, and the job's environment names it as the HTTP(S) proxy, so pip, uv, npm, cargo,
git and curl work unchanged.

On the other end this supervisor speaks one protocol, HTTP CONNECT (TLS stays end to end): it
admits a tunnel only to a host and port the job's profiles name, resolves the host itself and
refuses any address that is not public (no loopback, private, link-local or reserved address:
the host's own services stay out of reach), caps the bytes a job moves, and records every
request, admitted or refused, on the job.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PORT = 3128  # the relay's port inside the sandbox
HOST_RE = re.compile(r"^(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
MAX_HEAD = 8192
MAX_LOG = 500
ALLOW_PRIVATE = False  # tests only: admit loopback upstreams


def host_ok(pattern: str) -> bool:
    return bool(HOST_RE.match(pattern)) and "." in pattern.lstrip("*.")


def matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return host == pattern


@dataclass
class Rules:
    """What one job may reach: (host pattern, ports) pairs, and how many bytes in all."""

    allow: list[tuple[str, tuple[int, ...]]]
    max_bytes: int = 4 << 30
    names: list[str] = field(default_factory=list)  # the profiles, for the messages

    def admits(self, host: str, port: int) -> bool:
        return any(matches(host, h) and port in ports for h, ports in self.allow)


@dataclass
class _Job:
    rules: Rules
    server: asyncio.AbstractServer
    path: Path
    log: list[dict[str, Any]] = field(default_factory=list)
    moved: int = 0
    refused: int = 0


class Supervisor:
    """One event loop on its own thread, one unix-socket server per running job."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.jobs: dict[str, _Job] = {}
        self._t = threading.Thread(target=self.loop.run_forever, name="rhb-egress", daemon=True)
        self._t.start()

    def _call(self, coro: Any, timeout: float = 10.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def open(self, key: str, rules: Rules, root: str | Path) -> Path:
        """A socket for job `key`, in a directory of its own (the directory is what the sandbox binds)."""
        d = Path(root) / key
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, mode=0o700)
        path = d / "sock"

        async def start() -> asyncio.AbstractServer:
            job: dict[str, _Job] = {}

            async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
                await self._serve(job["j"], r, w)

            server = await asyncio.start_unix_server(handle, path=str(path))
            os.chmod(path, 0o600)
            job["j"] = _Job(rules, server, d)
            self.jobs[key] = job["j"]
            return server

        self._call(start())
        return d

    def close(self, key: str) -> dict[str, Any]:
        """Stop the job's socket; what it did: every request, bytes moved, refusals."""
        j = self.jobs.pop(key, None)
        if j is None:
            return {}

        async def stop() -> None:
            j.server.close()
            await j.server.wait_closed()

        try:
            self._call(stop())
        except (TimeoutError, RuntimeError):
            pass
        shutil.rmtree(j.path, ignore_errors=True)
        return {"requests": j.log[:MAX_LOG], "bytes": j.moved, "refused": j.refused}

    async def _serve(self, j: _Job, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        entry: dict[str, Any] = {"at": time.time()}
        try:
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 30)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            w.close()
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        entry["request"] = line[:200]

        async def refuse(code: str, why: str) -> None:
            j.refused += 1
            entry.update(status="refused", why=why)
            j.log.append(entry)
            body = (f"egress refused: {why}\n").encode()
            w.write(f"HTTP/1.1 {code}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n"
                    f"Connection: close\r\n\r\n".encode() + body)
            try:
                await w.drain()
            finally:
                w.close()

        if len(parts) != 3 or parts[0] != "CONNECT":
            await refuse("405 Method Not Allowed", "only CONNECT (https through the proxy) is spoken here")
            return
        host, _, port_s = parts[1].rpartition(":")
        host = host.strip("[]").lower()
        try:
            port = int(port_s)
        except ValueError:
            await refuse("400 Bad Request", f"bad target {parts[1]!r}")
            return
        entry.update(host=host, port=port)
        if not j.rules.admits(host, port):
            await refuse("403 Forbidden", f"{host}:{port} is in none of this policy's egress profiles "
                                          f"({', '.join(j.rules.names) or 'none'})")
            return
        if j.moved >= j.rules.max_bytes:
            await refuse("403 Forbidden", "this job has moved its byte allowance")
            return
        try:
            infos = await self.loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            await refuse("502 Bad Gateway", f"cannot resolve {host}: {e}")
            return
        addrs = [i[4][0] for i in infos]
        if not addrs or not (ALLOW_PRIVATE or all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)):
            await refuse("403 Forbidden", f"{host} resolves to a non-public address")
            return
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(addrs[0], port), 20)
        except (OSError, asyncio.TimeoutError) as e:
            await refuse("502 Bad Gateway", f"cannot reach {host}:{port}: {e}")
            return
        w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await w.drain()
        entry["status"] = "open"
        j.log.append(entry)
        moved = {"up": 0, "down": 0}

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, way: str) -> None:
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    moved[way] += len(data)
                    j.moved += len(data)
                    if j.moved > j.rules.max_bytes:
                        break
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                try:
                    dst.close()
                except (ConnectionError, OSError):
                    pass

        await asyncio.gather(pump(r, uw, "up"), pump(ur, w, "down"))
        entry.update(status="done", up=moved["up"], down=moved["down"], took=round(time.time() - entry["at"], 2))


def proxy_env(port: int = PORT) -> dict[str, str]:
    """What a job's tools read to use the relay."""
    url = f"http://127.0.0.1:{port}"
    return {k: url for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY")} | {
        "NO_PROXY": "", "no_proxy": "", "npm_config_proxy": url, "npm_config_https_proxy": url,
        "CARGO_HTTP_PROXY": url, "GIT_TERMINAL_PROMPT": "0"}


_sup: Supervisor | None = None
_sup_lock = threading.Lock()


def supervisor() -> Supervisor:
    """This process's supervisor (the runner's: the MCP process for a local server, the runner unit
    for a remote one)."""
    global _sup
    with _sup_lock:
        if _sup is None:
            _sup = Supervisor()
        return _sup


def socket_root() -> Path:
    """A short private directory for the sockets (a unix socket's path is at most 107 bytes)."""
    import tempfile

    d = Path(os.environ.get("RHB_EGRESS_DIR") or Path(tempfile.gettempdir()) / f"rhb-egress-{os.getuid()}")
    d.mkdir(mode=0o700, exist_ok=True)
    if d.stat().st_uid != os.getuid() or d.stat().st_mode & 0o077:
        raise OSError(f"{d} is not this user's private directory")
    return d
