"""The HTTP client the provider adapters use, on the standard library: urllib in a pool of worker
threads, so an agent's call does not hold up the event loop. JSON POST and GET with headers and a
timeout, nothing else.

Redirects are not followed: a key travels in a header, and a provider that answers with a redirect
gets that status back as it is, rather than the key going on to another host. Every HTTP status comes
back as a Response; only a failure to talk at all (refused, reset, timed out, no such name) raises
HttpError. The proxy settings of the environment (HTTPS_PROXY, NO_PROXY) apply, as urllib reads them.
"""

from __future__ import annotations

import asyncio
import http.client
import json as jsonlib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

MAX_BODY = 64 << 20  # bytes of a response read at most


class HttpError(Exception):
    """No HTTP answer: the connection failed, broke or timed out."""


@dataclass
class Response:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)  # names lower-cased
    content: bytes = b""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return jsonlib.loads(self.content)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # urllib then raises HTTPError with the 3xx, which comes back as a Response


class Client:
    def __init__(self, timeout: float = 900.0, workers: int = 32):
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rhb-http")

    async def post(self, url: str, json: Any = None, headers: dict[str, str] | None = None) -> Response:
        body = jsonlib.dumps(json, ensure_ascii=False).encode() if json is not None else b""
        h = {"content-type": "application/json", **(headers or {})}
        return await self._call("POST", url, body, h)

    async def get(self, url: str, headers: dict[str, str] | None = None) -> Response:
        return await self._call("GET", url, None, headers or {})

    async def _call(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> Response:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._send, method, url, body, headers)

    def _send(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> Response:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_BODY))
        except urllib.error.HTTPError as e:
            with e:
                return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read(MAX_BODY))
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise HttpError(f"{method} {url.split('?')[0]}: {getattr(e, 'reason', None) or e}") from e

    async def aclose(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
