"""The site's JSON APIs: one convention for every service (docs/site.md "APIs and pages").

    /<service>/api/v1/...     JSON in, JSON out; the version moves only with a breaking change
    200/201                   the resource itself (an object or a list), no envelope
    4xx/5xx                   {"error": {"code": "...", "message": "..."}}

Who is asking is the service's to say (the site sign-in's token, through nginx); this module only
shapes requests and answers. A request that writes (anything but GET and HEAD) must carry
`X-Requested-With: fetch` and, if it has an Origin, the site's: a form on another site cannot send that
header, and with no CORS allowed here no script on another site can either. That stands in for the
pages' form tokens.

A refusal the user can act on (a bad value, a missing thing) is a 4xx with its message. Anything else
the backends raise is a 502 with a reference only; what went wrong goes to the log under it.
"""

from __future__ import annotations

import functools
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("portal.api")

VERSION = "v1"
MAX_BODY = 1 << 20
WRITE_HEADER = ("x-requested-with", "fetch")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def bad(message: str, code: str = "invalid") -> ApiError:
    return ApiError(400, code, message)


def missing(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


def forbidden(message: str = "not allowed") -> ApiError:
    return ApiError(403, "forbidden", message)


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "sign in first")


def answer(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def failure(e: ApiError) -> JSONResponse:
    return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.status,
                        headers={"Cache-Control": "no-store"})


def check_write(request: Request, origin: str) -> None:
    """A writing request comes from the site's own pages (see the module's docstring)."""
    if request.method in ("GET", "HEAD"):
        return
    if request.headers.get(WRITE_HEADER[0], "").lower() != WRITE_HEADER[1]:
        raise forbidden(f"a write needs the header {WRITE_HEADER[0]}: {WRITE_HEADER[1]}")
    o = request.headers.get("origin")
    if o is not None and o.rstrip("/") != origin.rstrip("/"):
        raise forbidden("a request from another site")


async def body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ApiError(413, "too_large", f"at most {MAX_BODY} bytes")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise bad(f"the body is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise bad("the body is a JSON object")
    return data


def endpoint(*, origin: str, user_errors: tuple[type[BaseException], ...] = (),
             refusals: tuple[type[BaseException], ...] = (),
             backend_errors: tuple[type[BaseException], ...] = ()) -> Callable[..., Any]:
    """Wrap an endpoint `(request) -> data | Response` (a Response as is: answer(data, 201) for a
    creation): the write check, JSON answers, errors shaped as above. `user_errors` become 400 with their message, `backend_errors` (and anything else) 502
    or 500 with a reference."""

    def deco(fn: Callable[[Request], Awaitable[Any]]) -> Callable[[Request], Awaitable[Response]]:
        @functools.wraps(fn)
        async def run(request: Request) -> Response:
            try:
                check_write(request, origin)
                out = await fn(request)
                return out if isinstance(out, Response) else answer(out)
            except ApiError as e:
                return failure(e)
            except user_errors as e:
                return failure(bad(str(e)))
            except refusals as e:
                return failure(forbidden(str(e)))
            except backend_errors as e:
                ref = secrets.token_hex(4)
                log.warning("[%s] %s %s: %s", ref, request.method, request.url.path, e)
                return failure(ApiError(502, "backend", f"the operation could not be completed (reference {ref})"))
            except Exception:  # noqa: BLE001 — a bug answers as one, with a reference to find it by
                ref = secrets.token_hex(4)
                log.exception("[%s] %s %s", ref, request.method, request.url.path)
                return failure(ApiError(500, "internal", f"something went wrong (reference {ref})"))
        return run
    return deco
