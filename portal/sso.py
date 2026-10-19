"""Site-wide sign-in for www.m00nny.kr, consulted by nginx `auth_request`.

One Kerberos sign-in page (/auth/login) sets a site cookie; /auth/check answers nginx for every
protected location:

- a browser with the cookie                      -> 200
- a WebDAV client with Basic <uid>:<Kerberos pw> -> 200 (the check is cached briefly)
- a 200 carries X-Remote-User (for logs) and, when nginx names the backend in X-Auth-Audience,
  X-Auth-Token: a one-minute EdDSA token for that backend (portal/tokens.py). Backends trust only
  the token, never a bare user header.
- under /dav/, the path (and a MOVE/COPY Destination) must be the user's own /dav/<uid>/, else 403
- nothing valid -> 401; under /dav/ with `WWW-Authenticate: Basic`, elsewhere nginx redirects to
  /auth/login?next=...

This process holds only the HTTP service keytab (to prove the KDC is genuine), never the portal's
kadmin keytab: it is the most exposed piece, so it gets the least. Run it as its own user.
"""
import hashlib
import posixpath
import secrets
import threading
import time
from base64 import b64decode
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import audit, tokens, validators
from .config import Settings
from .kerberos import Kerberos, KerberosError, LoginResult
from .security import SecurityHeadersMiddleware, Throttle, csrf_ok, csrf_token
from .validators import ValidationError

HERE = Path(__file__).parent


def safe_next(value: str | None) -> str:
    """A same-site path to return to after sign-in; anything else becomes "/" (no open redirect)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if any(ord(c) < 0x21 for c in value) or urlsplit(value).netloc:
        return "/"
    return value


def next_from_query(query: str) -> str:
    """nginx sends `?next=$request_uri` unencoded, so next= is the last parameter and everything
    after it is the value (a request URI may itself carry ?a=1&b=2). `switch=1&next=...` works too."""
    if query.startswith("next="):
        return safe_next(unquote(query[5:]))
    i = query.find("&next=")
    return safe_next(unquote(query[i + 6:])) if i >= 0 else "/"


def dav_owner(path: str, prefix: str) -> str | None:
    """The uid a /dav/<uid>/... path belongs to; None for /dav itself, traversal, or bad names."""
    path = unquote(path)
    if "\x00" in path:
        return None
    norm = posixpath.normpath(path)
    if norm != path.rstrip("/") and norm + "/" != path:
        return None  # "..", "//", "/./" and the like: refuse rather than guess what nginx maps
    rest = norm[len(prefix):] if norm == prefix or norm.startswith(prefix + "/") else None
    if not rest:
        return None
    uid = rest.lstrip("/").split("/", 1)[0]
    try:
        return validators.uid(uid)
    except ValidationError:
        return None


class BasicCache:
    """Recently verified (uid, password) pairs, so WebDAV's Basic-on-every-request does not ask the
    KDC each time. Holds salted hashes only; a disabled account keeps working for at most `ttl`."""

    def __init__(self, ttl: int):
        self.ttl = ttl
        self._salt = secrets.token_bytes(16)
        self._ok: dict[str, float] = {}
        self._lock = threading.Lock()

    def _key(self, uid: str, password: str) -> str:
        return hashlib.sha256(self._salt + uid.encode() + b"\0" + password.encode()).hexdigest()

    def hit(self, uid: str, password: str) -> bool:
        now = time.monotonic()
        with self._lock:
            exp = self._ok.get(self._key(uid, password))
            return exp is not None and exp > now

    def add(self, uid: str, password: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._ok) > 10000:
                self._ok = {k: v for k, v in self._ok.items() if v > now}
            self._ok[self._key(uid, password)] = now + self.ttl


def create_app(settings: Settings | None = None, kerberos=None, signing_key=None) -> FastAPI:
    s = settings or Settings()
    audiences = s.audiences()  # apps.toml is read at start: a bad file stops the SSO, not a request
    if len(s.sso_secret) < 32:
        raise RuntimeError("PORTAL_SSO_SECRET must be set to at least 32 random characters.")
    kerberos = kerberos or Kerberos(s)
    signing_key = signing_key or tokens.load_private_key(s.sso_signing_key_file)
    throttle = Throttle()
    cache = BasicCache(s.basic_cache_seconds)
    audit.setup(s.audit_log)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    # Lax, not Strict: Claude's OAuth flow arrives at /authorize from claude.ai by a top-level GET,
    # and the sign-in should carry over. Lax still keeps the cookie off cross-site POSTs.
    app.add_middleware(SessionMiddleware, secret_key=s.sso_secret, session_cookie=s.sso_cookie,
                       max_age=s.sso_max_age, same_site="lax", https_only=s.cookie_secure, path="/")
    app.mount("/auth/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    def ip(request: Request) -> str:
        return request.client.host if request.client else "-"

    def flash(request: Request, kind: str, msg: str) -> None:
        request.session.setdefault("flash", []).append([kind, msg])

    def render(request: Request, name: str, status: int = 200, **ctx):
        ctx.update(csrf=csrf_token(request.session), flashes=request.session.pop("flash", []), settings=s)
        resp = templates.TemplateResponse(request, name, ctx)
        resp.status_code = status
        return resp

    def redirect(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def session_user(request: Request) -> str | None:
        uid, at = request.session.get("uid"), request.session.get("login_at", 0)
        if uid and time.time() - at <= s.sso_max_age:
            return uid
        return None

    def verify(raw_uid: str, password: str, addr: str) -> tuple[str | None, LoginResult]:
        """Throttled Kerberos check. Returns (uid, result)."""
        keys = (f"ip:{addr}", f"uid:{raw_uid}")
        if throttle.blocked(*keys):
            return None, LoginResult.BAD
        try:
            uid = validators.uid(raw_uid)
        except ValidationError:
            uid = None
        result = LoginResult.BAD
        if uid and password and "\x00" not in password:
            result = kerberos.verify_password(s.principal(uid), password)
        if result is LoginResult.OK:
            throttle.reset(f"uid:{uid}")
        elif result is not LoginResult.EXPIRED:  # an expired password is a right one
            throttle.fail(*keys)
        return (uid if result is LoginResult.OK else None), result

    # ---- nginx auth_request ------------------------------------------------------------------

    def basic_credentials(request: Request) -> tuple[str, str] | None:
        h = request.headers.get("authorization", "")
        if not h.lower().startswith("basic "):
            return None
        try:
            raw = b64decode(h[6:].strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        user, sep, password = raw.partition(":")
        return (user.strip().lower(), password) if sep else None

    @app.get("/auth/check")
    async def check(request: Request):
        uri = request.headers.get("x-original-uri", "").split("?", 1)[0]  # nginx sends $request_uri
        is_dav = uri == s.dav_prefix or uri.startswith(s.dav_prefix + "/")
        uid = session_user(request)
        if uid is None:
            creds = basic_credentials(request)
            if creds is not None:
                user, password = creds
                if cache.hit(user, password):
                    uid = user
                else:
                    uid, result = await run_in_threadpool(verify, user, password, ip(request))
                    if uid:
                        cache.add(uid, password)
                        audit.record(uid, "basic_login", None, True, ip(request))
                    else:
                        audit.record(user, "basic_login", None, False, ip(request), result.value)
        if uid is None:
            headers = {"WWW-Authenticate": 'Basic realm="m00nny", charset="UTF-8"'} if is_dav else {}
            return Response(status_code=401, headers=headers)
        if is_dav:
            if dav_owner(uri, s.dav_prefix) != uid:
                return Response(status_code=403)
            dest = request.headers.get("x-original-destination", "")
            if dest and dav_owner(urlsplit(dest).path, s.dav_prefix) != uid:
                return Response(status_code=403)
        headers = {"X-Remote-User": uid}
        aud = request.headers.get("x-auth-audience", "")
        if aud:
            if aud not in audiences:
                return Response(status_code=500)  # a typo in nginx; fail closed and visibly
            headers["X-Auth-Token"] = tokens.issue(signing_key, s.sso_issuer, aud, uid, s.token_ttl)
        return Response(status_code=200, headers=headers)

    # ---- sign-in -----------------------------------------------------------------------------

    @app.get("/auth/login")
    async def login_page(request: Request):
        nxt = next_from_query(request.url.query)
        uid = session_user(request)
        if uid and request.query_params.get("switch") != "1":
            return redirect(nxt)
        return render(request, "sso_login.html", next=nxt, current=uid)

    @app.post("/auth/login")
    async def login(request: Request):
        data = await request.form()
        if not csrf_ok(request.session, data.get("csrf")):
            return render(request, "sso_login.html", 403, next="/", current=None,
                          error="Invalid or missing CSRF token. Reload the page and try again.")
        nxt = safe_next(str(data.get("next", "/")))
        raw_uid, password = str(data.get("uid", "")).strip().lower()[:64], str(data.get("password", ""))[:1024]
        uid, result = await run_in_threadpool(verify, raw_uid, password, ip(request))
        audit.record(uid or raw_uid, "sso_login", None, uid is not None, ip(request), result.value)
        if result is LoginResult.EXPIRED:
            request.session["expired_uid"] = raw_uid
            request.session["expired_next"] = nxt
            flash(request, "info", "비밀번호를 먼저 바꿔야 합니다 (임시 비밀번호이거나 만료됨).")
            return redirect("/auth/expired")
        if uid is None:
            msg = ("사용자명 또는 비밀번호가 맞지 않습니다." if result is LoginResult.BAD
                   else "비활성화되었거나 잠긴 계정입니다.")
            return render(request, "sso_login.html", 401, next=nxt, current=None, error=msg, uid=raw_uid)
        request.session.clear()  # new session on sign-in
        request.session.update(uid=uid, login_at=time.time())
        return redirect(nxt)

    @app.get("/auth/logout")
    async def logout_page(request: Request):
        return render(request, "sso_logout.html", current=session_user(request))

    @app.post("/auth/logout")
    async def logout(request: Request):
        data = await request.form()
        if csrf_ok(request.session, data.get("csrf")):
            audit.record(request.session.get("uid"), "sso_logout", None, True, ip(request))
            request.session.clear()
        return redirect("/")

    # ---- one-time and expired passwords (kpasswd; no admin rights) ----------------------------

    @app.get("/auth/expired")
    async def expired_page(request: Request):
        return render(request, "sso_expired.html", uid=request.session.get("expired_uid", ""))

    @app.post("/auth/expired")
    async def expired_change(request: Request):
        data = await request.form()
        if not csrf_ok(request.session, data.get("csrf")):
            flash(request, "error", "Invalid or missing CSRF token. Reload the page and try again.")
            return redirect("/auth/expired")
        raw_uid = str(data.get("uid", "")).strip().lower()[:64]
        keys = (f"ip:{ip(request)}", f"uid:{raw_uid}")
        if throttle.blocked(*keys):
            flash(request, "error", "실패가 너무 많습니다. 15분 뒤 다시 시도하세요.")
            return redirect("/auth/expired")
        try:
            uid = validators.uid(raw_uid)
            new = validators.new_password(str(data.get("new", "")), str(data.get("confirm", "")))
            await run_in_threadpool(kerberos.change_own_password, s.principal(uid), str(data.get("old", "")), new)
        except (ValidationError, KerberosError) as e:
            throttle.fail(*keys)
            audit.record(raw_uid, "change_expired_password", raw_uid, False, ip(request), str(e))
            flash(request, "error", str(e))
            return redirect("/auth/expired")
        audit.record(uid, "change_expired_password", uid, True, ip(request))
        nxt = request.session.pop("expired_next", "/")
        request.session.pop("expired_uid", None)
        flash(request, "ok", "비밀번호를 바꿨습니다. 새 비밀번호로 로그인하세요.")
        return redirect("/auth/login?next=" + nxt)

    @app.get("/auth/healthz")
    async def healthz():
        return Response("ok", media_type="text/plain")

    return app
