"""The egress supervisor: the sandbox's only way out, and only by protocols it knows.

A sandbox has its own network namespace with nothing in it but loopback. When its policy names
egress profiles (capability kind `egress`: named sets of hosts and ports, e.g. `pypi`, `npm`,
`github`), the runner opens a unix socket for that one job and binds its directory at
/run/egress inside; a relay in the sandbox listens on 127.0.0.1:3128 and passes each connection
to the socket, and the job's environment names it as the HTTP(S) proxy, so pip, uv, npm, cargo,
git and curl work unchanged.

On the other end this supervisor speaks one protocol, HTTP CONNECT (TLS stays end to end): it
admits a tunnel only to a host and port the job's profiles name; resolves the host itself and
refuses any address that is not public, or that carries a non-public IPv4 address (loopback,
private, link-local, reserved, through NAT64 or 6to4 or a mapped form: the host's own services
stay out of reach); requires the tunnel to open with a TLS ClientHello whose server name is that
same host (on a shared CDN address another name would reach another site; an encrypted
ClientHello is refused); bounds every job (connections at once, bytes, idle time, lookups, its
log) so none can starve another; and records the job's requests, admitted or refused.
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
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PORT = 3128  # the relay's port inside the sandbox
HOST_RE = re.compile(r"^(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")
MAX_HEAD = 8192
MAX_LOG = 200  # the latest requests kept per job (with counts of all of them)
PER_JOB = 32  # connections at once, per job
TOTAL = 512  # connections at once, every job together
IDLE = 300.0  # seconds a tunnel may sit with nothing moving
ALLOW_PRIVATE = False  # tests only: admit loopback upstreams
ALLOW_PLAIN = False  # tests only: tunnels that do not start with a TLS ClientHello naming the host


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


def public(addr: str) -> bool:
    """A public address, and so is any IPv4 address it carries (NAT64, 6to4, Teredo, mapped,
    compatible): the host's own and private networks stay out of reach however they are spelled."""
    ip = ipaddress.ip_address(addr.split("%")[0])
    if not ip.is_global:
        return False
    if ip.version == 6:
        inner = []
        if ip.ipv4_mapped:
            inner.append(ip.ipv4_mapped)
        if ip.sixtofour:
            inner.append(ip.sixtofour)
        if ip.teredo:
            inner += list(ip.teredo)
        b = ip.packed
        if b[:12] == bytes(12) or ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
            inner.append(ipaddress.IPv4Address(b[12:]))
        return all(x.is_global for x in inner)
    return True


def client_hello_sni(data: bytes) -> tuple[str | None, str]:
    """(server name, problem) of a TLS ClientHello at the start of `data`; the problem is "" when
    the hello is whole and plain (no encrypted ClientHello), "short" when more bytes are needed."""
    if len(data) < 5:
        return None, "short"
    if data[0] != 22 or data[1] != 3:
        return None, "not TLS"
    rec = int.from_bytes(data[3:5], "big")
    if len(data) < 5 + rec:
        return None, "short"
    h = data[5:5 + rec]
    if len(h) < 4 or h[0] != 1:
        return None, "not a ClientHello"
    n = int.from_bytes(h[1:4], "big")
    if 4 + n > len(h):
        return None, "a ClientHello split across records"
    b, i = h[4:4 + n], 34  # version, random
    try:
        i += 1 + b[i]  # session id
        i += 2 + int.from_bytes(b[i:i + 2], "big")  # cipher suites
        i += 1 + b[i]  # compression
        end = i + 2 + int.from_bytes(b[i:i + 2], "big")
        i += 2
        sni = None
        while i + 4 <= end:
            t, ln = int.from_bytes(b[i:i + 2], "big"), int.from_bytes(b[i + 2:i + 4], "big")
            ext = b[i + 4:i + 4 + ln]
            if t in (0xFE0D, 0xFFCE):  # encrypted ClientHello: the name inside could be anything
                return None, "encrypted ClientHello"
            if t == 0 and len(ext) >= 5 and ext[2] == 0:
                sni = ext[5:5 + int.from_bytes(ext[3:5], "big")].decode("ascii").lower()
            i += 4 + ln
    except (IndexError, UnicodeDecodeError):
        return None, "a malformed ClientHello"
    return (sni, "") if sni else (None, "no server name")


@dataclass
class _Job:
    rules: Rules
    server: asyncio.AbstractServer
    path: Path
    log: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG))
    moved: int = 0
    refused: int = 0
    requests: int = 0
    live: int = 0
    resolver: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))


class Supervisor:
    """One event loop on its own thread, one unix-socket server per running job. Every job is
    bounded (connections, bytes, time, lookups, its log), so no job can starve another or the
    process the supervisor lives in."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.jobs: dict[str, _Job] = {}
        self.live = 0
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

        async def start() -> None:
            box: dict[str, _Job] = {}

            async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
                await self._serve(box["j"], r, w)

            server = await asyncio.start_unix_server(handle, path=str(path), limit=MAX_HEAD)
            os.chmod(path, 0o600)
            box["j"] = _Job(rules, server, d)
            self.jobs[key] = box["j"]

        self._call(start())
        return d

    def close(self, key: str) -> dict[str, Any]:
        """Stop the job's socket; what it did: its latest requests, the counts, the bytes moved."""
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
        return {"requests": list(j.log), "count": j.requests, "bytes": j.moved, "refused": j.refused}

    async def _serve(self, j: _Job, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        if j.live >= PER_JOB or self.live >= TOTAL:
            j.refused += 1
            w.close()
            return
        j.live += 1
        self.live += 1
        upstream: asyncio.StreamWriter | None = None
        try:
            upstream = await self._tunnel(j, r, w)
        except Exception:  # noqa: BLE001 — a connection's trouble ends that connection, nothing else
            pass
        finally:
            j.live -= 1
            self.live -= 1
            for x in (w, upstream):
                if x is not None:
                    try:
                        x.close()
                    except Exception:  # noqa: BLE001
                        pass

    async def _tunnel(self, j: _Job, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> asyncio.StreamWriter | None:
        j.requests += 1
        entry: dict[str, Any] = {"at": round(time.time(), 3)}
        j.log.append(entry)

        async def refuse(code: str, why: str) -> None:
            j.refused += 1
            entry.update(status="refused", why=why[:200])
            body = f"egress refused: {why}\n".encode()
            w.write(f"HTTP/1.1 {code}\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n"
                    f"Connection: close\r\n\r\n".encode() + body)
            await asyncio.wait_for(w.drain(), 10)

        try:
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 15)  # the whole head, in 15 s
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ValueError):
            entry.update(status="refused", why="no request head")
            j.refused += 1
            return None
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        entry["request"] = line[:120]
        if len(parts) != 3 or parts[0] != "CONNECT":
            await refuse("405 Method Not Allowed", "only CONNECT (https through the proxy) is spoken here")
            return None
        host, _, port_s = parts[1].rpartition(":")
        host = host.strip("[]").lower().rstrip(".")
        if not port_s.isdigit() or not (0 < int(port_s) < 65536) or len(host) > 253 or not HOST_RE.match(host) \
                or "*" in host:
            await refuse("400 Bad Request", f"bad target {parts[1][:80]!r}")
            return None
        port = int(port_s)
        entry.update(host=host, port=port)
        if not j.rules.admits(host, port):
            await refuse("403 Forbidden", f"{host}:{port} is in none of this policy's egress profiles "
                                          f"({', '.join(j.rules.names) or 'none'})")
            return None
        if j.moved >= j.rules.max_bytes:
            await refuse("403 Forbidden", "this job has moved its byte allowance")
            return None
        try:
            async with j.resolver:
                infos = await asyncio.wait_for(self.loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), 15)
        except (OSError, asyncio.TimeoutError, UnicodeError) as e:
            await refuse("502 Bad Gateway", f"cannot resolve {host}: {e}")
            return None
        addrs = list(dict.fromkeys(i[4][0] for i in infos))
        if not addrs or not (ALLOW_PRIVATE or all(public(a) for a in addrs)):
            await refuse("403 Forbidden", f"{host} resolves to a non-public address")
            return None
        w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await asyncio.wait_for(w.drain(), 10)
        # what flows next must be TLS to that same name: on a shared CDN address, a different server
        # name would reach a different site
        hello = b""
        try:
            while True:
                sni, problem = client_hello_sni(hello)
                if problem != "short" or len(hello) > 16384 + 5:
                    break
                more = await asyncio.wait_for(r.read(16384 + 5 - len(hello) or 1), 15)
                if not more:
                    break
                hello += more
        except asyncio.TimeoutError:
            problem = "no ClientHello in time"
        if not ALLOW_PLAIN and (problem or sni != host):
            j.refused += 1
            entry.update(status="refused", why=(problem or f"the TLS server name {sni!r} is not {host}")[:200])
            return None
        upstream = None
        for a in addrs[:4]:
            try:
                ur, upstream = await asyncio.wait_for(asyncio.open_connection(a, port), 15)
                break
            except (OSError, asyncio.TimeoutError) as e:
                entry["why"] = f"cannot reach {a}: {e}"[:200]
        if upstream is None:
            j.refused += 1
            entry["status"] = "refused"
            return None
        entry["status"] = "open"
        moved = {"up": len(hello), "down": 0}
        upstream.write(hello)
        j.moved += len(hello)

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, way: str) -> None:
            try:
                while True:
                    data = await asyncio.wait_for(src.read(65536), IDLE)
                    if not data or j.moved > j.rules.max_bytes:
                        break
                    moved[way] += len(data)
                    j.moved += len(data)
                    dst.write(data)
                    await asyncio.wait_for(dst.drain(), IDLE)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(pump(r, upstream, "up"), pump(ur, w, "down"))
        entry.update(status="done", up=moved["up"], down=moved["down"], took=round(time.time() - entry["at"], 2))
        return upstream


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

    import stat as st

    d = Path(os.environ.get("RHB_EGRESS_DIR") or Path(tempfile.gettempdir()) / f"rhb-egress-{os.getuid()}")
    d.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(d)  # not followed: a link someone else planted is refused
    if not st.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError(f"{d} is not this user's private directory")
    return d
