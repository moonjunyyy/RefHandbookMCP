"""The handbook over Streamable HTTP, one database per site user, behind the site sign-in.

Claude connects as an OAuth client (dynamic client registration + PKCE). This server is its own
authorization server: /authorize sends the browser to /login, which nginx puts behind the site
sign-in (portal.sso); the site's token names the user, and /login only asks to allow the client
before it issues a one-time code. Access tokens carry the uid as `subject`, and every tool call
opens that user's database (DATA_DIR/users/<uid>.db).

The installer renders the settings (RHB_*) into the unit from the site's facts (deploy/templates).
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import anyio
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from portal.facts import SIGNIN

from .page import page
from .store import Handbook

log = logging.getLogger("refhandbook.remote")

SCOPE = "refhandbook"
UID_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,63}$")
DEFAULT_REDIRECTS = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "http://localhost:*",
    "http://127.0.0.1:*",
)


# ── configuration ────────────────────────────────────────────────────────


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _url_env(name: str, default: str | None = None) -> str | None:
    """A URL or path setting. One with whitespace in it is refused at start: systemd's EnvironmentFile
    keeps a note after the value ("https://x   (default: …)") as part of it, and a token check against
    such an issuer fails on every request with only "Invalid issuer" to show for it."""
    v = _env(name, default)
    if v is not None and any(c.isspace() for c in v):
        raise SystemExit(f"{name}={v!r} has whitespace in it: put notes on a line of their own")
    return v


def _list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = _env(name)
    return default if v is None else tuple(x.strip() for x in v.split(",") if x.strip())


@dataclass(frozen=True)
class Config:
    public_url: str  # https://www.example.org, no trailing slash: the site
    data_dir: Path
    sso_public_key_file: str  # the site sign-in's token key (portal.tokens), public half
    sso_issuer: str = ""  # default: public_url
    sso_audience: str = "refhandbook"  # the audience nginx asks the sign-in to mint for this app
    login_url: str = SIGNIN + "/login"  # the site sign-in page, for a browser without its cookie
    host: str = "127.0.0.1"
    port: int = 0  # RHB_PORT: the installer renders the handbook role's port (portal/facts.py ROLES)
    require_group: str | None = None  # a POSIX group (through NSS) the user must belong to
    redirect_allow: tuple[str, ...] = DEFAULT_REDIRECTS
    access_ttl: int = 3600
    refresh_ttl: int = 30 * 86400
    session_ttl: int = 90 * 86400  # absolute: a grant's tokens end this long after it
    extra_hosts: tuple[str, ...] = ()  # Host headers accepted besides the public host and loopback

    @property
    def resource_url(self) -> str:
        return self.public_url + "/mcp"

    @classmethod
    def from_env(cls) -> Config:
        public = _url_env("RHB_PUBLIC_URL")
        if not public:
            raise SystemExit("RHB_PUBLIC_URL is required (the site's origin, e.g. https://www.example.org)")
        public = public.rstrip("/")
        p = urlparse(public)
        if p.scheme != "https" and p.hostname not in ("localhost", "127.0.0.1"):
            raise SystemExit("RHB_PUBLIC_URL must be https (Claude only connects to https servers)")
        if p.path not in ("", "/"):
            raise SystemExit("RHB_PUBLIC_URL must be a bare origin, without a path")
        key = _url_env("RHB_SSO_PUBLIC_KEY_FILE")
        if not key:
            raise SystemExit("RHB_SSO_PUBLIC_KEY_FILE is required (the site sign-in's sso-public.pem)")
        # systemd's StateDirectory=, unless set: the unit owns its data
        data = _env("RHB_DATA_DIR") or (os.environ.get("STATE_DIRECTORY", "").split(":")[0] or None)
        if not data:
            raise SystemExit("RHB_DATA_DIR is required outside a unit with StateDirectory=")
        port = _env("RHB_PORT")
        if not port:
            raise SystemExit("RHB_PORT is required (the handbook role's port, which nginx proxies to)")
        allow = _env("RHB_REDIRECT_ALLOW")
        return cls(
            public_url=public,
            data_dir=Path(data),
            sso_public_key_file=key,
            sso_issuer=_url_env("RHB_SSO_ISSUER", public),  # type: ignore[arg-type]
            sso_audience=_env("RHB_SSO_AUDIENCE", cls.sso_audience),  # type: ignore[arg-type]
            login_url=_url_env("RHB_LOGIN_URL", cls.login_url),  # type: ignore[arg-type]
            host=_env("RHB_HOST", cls.host),  # type: ignore[arg-type]
            port=int(port),
            require_group=_env("RHB_REQUIRE_GROUP"),
            redirect_allow=tuple(s.strip() for s in allow.split(",") if s.strip()) if allow else DEFAULT_REDIRECTS,
            access_ttl=int(_env("RHB_ACCESS_TTL", str(cls.access_ttl))),  # type: ignore[arg-type]
            refresh_ttl=int(_env("RHB_REFRESH_TTL", str(cls.refresh_ttl))),  # type: ignore[arg-type]
            session_ttl=int(_env("RHB_SESSION_TTL", str(cls.session_ttl))),  # type: ignore[arg-type]
            extra_hosts=_list("RHB_ALLOWED_HOSTS", ()),
        )


def redirect_allowed(uri: str, patterns: tuple[str, ...]) -> bool:
    """Exact match, or `scheme://host:*` for any port and path on a loopback host.

    The URI is parsed first: userinfo (`user@`), a fragment, or a scheme other than http(s) refuses
    it, so `http://evil.example\\@localhost/` cannot pass as loopback.
    """
    try:
        u = urlparse(uri)
        port = u.port
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or u.username is not None or u.password is not None or "@" in u.netloc \
            or "\\" in uri or u.fragment or not u.hostname:
        return False
    for pat in patterns:
        if pat.endswith(":*"):
            q = urlparse(pat[:-2])
            if u.scheme == q.scheme and u.hostname == q.hostname and (port is None or 0 < port < 65536):
                return True
        elif uri == pat:
            return True
    return False


def ascii_lower(name: str) -> str | None:
    """Lower-case a POSIX name; None for anything non-ASCII (the Kelvin sign lowers to 'k')."""
    return name.lower() if name.isascii() else None


# ── accounts and the site's tokens ───────────────────────────────────────


class Accounts:
    """Who may use the handbook. The site sign-in checks passwords; here only the account policy
    remains: the name resolves through NSS (which also gives the canonical name), and is in
    require_group if one is set. Checked before a grant and on every refresh."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _in_group(self, name: str) -> bool:
        import grp
        import pwd

        group = self.cfg.require_group
        if not group:
            return True
        try:
            gid = grp.getgrnam(group).gr_gid
            pw = pwd.getpwnam(name)
        except KeyError:
            return False
        return pw.pw_gid == gid or gid in os.getgrouplist(name, pw.pw_gid)

    def _account(self, username: str) -> str | None:
        import pwd

        name = ascii_lower(username.strip())
        if name is None or not UID_RE.match(name):
            return None
        try:
            return pwd.getpwnam(name).pw_name
        except KeyError:
            return None

    def exists(self, uid: str) -> bool:
        return self._account(uid) == uid and self._in_group(uid)


class SsoTokens:
    """The site sign-in's X-Auth-Token (an EdDSA JWT minted by portal.sso for this app's audience),
    checked with portal.tokens: one implementation for every backend of the site."""

    def __init__(self, cfg: Config, public_key: object | None = None):
        from portal import tokens

        self.cfg = cfg
        self._tokens = tokens
        self.key = public_key or tokens.load_public_key(cfg.sso_public_key_file)

    def uid(self, token: str) -> str | None:
        if not token:
            return None
        try:
            sub = self._tokens.verify(self.key, token, self.cfg.sso_issuer or self.cfg.public_url, self.cfg.sso_audience)
        except self._tokens.TokenError as e:
            log.info("SSO token refused: %s", e)
            return None
        uid = ascii_lower(sub)
        return uid if uid and UID_RE.match(uid) else None


# ── OAuth authorization server ───────────────────────────────────────────

# tokens: one row per token, hashed. A sign-in starts a family; every refresh rotates within it.
# kind 'used' keeps a rotated refresh token so a replay revokes the whole family.
AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL, created REAL NOT NULL,
                                    signed_in INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL,
                                    expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS codes   (hash TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL,
                                    auth_time REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tokens  (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
                                    subject TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT,
                                    expires INTEGER NOT NULL, family TEXT NOT NULL, auth_time REAL NOT NULL,
                                    pair TEXT);
CREATE INDEX IF NOT EXISTS tokens_family ON tokens(family);
CREATE INDEX IF NOT EXISTS tokens_pair ON tokens(pair);
"""

MAX_PENDING = 5000


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class SQLiteOAuthProvider:
    """OAuthAuthorizationServerProvider backed by DATA_DIR/auth.db. Codes and tokens are stored hashed.

    All database work is synchronous and the server runs one event loop, so each method body is
    atomic between its awaits; the only awaits on a write path are marked.
    """

    def __init__(self, cfg: Config, directory: object | None = None):
        self.cfg = cfg
        self.directory = directory  # Accounts: refreshes re-check the account through it
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(cfg.data_dir / "auth.db"), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(AUTH_SCHEMA)

    def _sweep(self) -> None:
        now = time.time()
        self.db.execute("DELETE FROM pending WHERE expires < ?", (now,))
        self.db.execute("DELETE FROM codes WHERE expires < ?", (now,))
        self.db.execute("DELETE FROM tokens WHERE kind IN ('refresh','used') AND expires < ?", (int(now),))
        self.db.execute("DELETE FROM tokens WHERE kind='access' AND expires < ? AND family NOT IN "
                        "(SELECT family FROM tokens WHERE kind='refresh')", (int(now),))
        self.db.execute("DELETE FROM clients WHERE signed_in=0 AND created < ?", (now - 86400,))

    # clients
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.db.execute("SELECT info FROM clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        for uri in client_info.redirect_uris or []:
            if not redirect_allowed(str(uri), self.cfg.redirect_allow):
                raise RegistrationError("invalid_redirect_uri", f"redirect URI not allowed by this server: {uri}")
        self._sweep()
        self.db.execute("INSERT OR REPLACE INTO clients (client_id, info, created) VALUES (?,?,?)",
                        (client_info.client_id, client_info.model_dump_json(), time.time()))

    # authorization
    def _our_resource(self, resource: str | None) -> bool:
        return resource is None or resource.rstrip("/") in (self.cfg.public_url, self.cfg.resource_url)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not self._our_resource(params.resource):
            raise AuthorizeError("invalid_request", f"unknown resource: {params.resource}")
        if not redirect_allowed(str(params.redirect_uri), self.cfg.redirect_allow):
            raise AuthorizeError("invalid_request", "redirect URI not allowed by this server")
        self._sweep()
        if self.db.execute("SELECT count(*) FROM pending").fetchone()[0] >= MAX_PENDING:
            raise AuthorizeError("temporarily_unavailable", "too many sign-ins in progress")
        rid = secrets.token_urlsafe(24)
        self.db.execute("INSERT INTO pending (id, client_id, params, expires) VALUES (?,?,?,?)",
                        (rid, client.client_id, params.model_dump_json(), time.time() + 600))
        return f"{self.cfg.public_url}/login?req={rid}"

    def pending(self, rid: str) -> tuple[str, AuthorizationParams, int] | None:
        row = self.db.execute("SELECT client_id, params, attempts FROM pending WHERE id=? AND expires>=?",
                              (rid, time.time())).fetchone()
        if not row:
            return None
        return row[0], AuthorizationParams.model_validate_json(row[1]), row[2]

    def drop_pending(self, rid: str) -> None:
        self.db.execute("DELETE FROM pending WHERE id=?", (rid,))

    async def grant(self, rid: str, subject: str) -> str:
        """Called by /login once the user allowed the client: issue a code, return the client redirect."""
        got = self.pending(rid)
        if got is None:
            raise AuthorizeError("access_denied", "sign-in request expired")
        client_id, params, _ = got
        self.drop_pending(rid)
        client = await self.get_client(client_id)  # no I/O: a row read
        scopes = params.scopes or ((client.scope or SCOPE).split() if client else [SCOPE])
        code = secrets.token_urlsafe(32)
        now = time.time()
        ac = AuthorizationCode(
            code=code, scopes=scopes, expires_at=now + 300, client_id=client_id,
            code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=self.cfg.resource_url, subject=subject,  # authorize() admitted only this server
        )
        self.db.execute("INSERT INTO codes VALUES (?,?,?,?)", (_h(code), ac.model_dump_json(), ac.expires_at, now))
        self.db.execute("UPDATE clients SET signed_in=1 WHERE client_id=?", (client_id,))
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    def deny(self, rid: str) -> str | None:
        got = self.pending(rid)
        if got is None:
            return None
        self.drop_pending(rid)
        _, params, _ = got
        return construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        row = self.db.execute("SELECT data FROM codes WHERE hash=?", (_h(authorization_code),)).fetchone()
        if not row:
            return None
        ac = AuthorizationCode.model_validate_json(row[0])
        return ac if ac.client_id == client.client_id else None

    def _issue(self, client_id: str, subject: str, scopes: list[str], resource: str | None,
               family: str, auth_time: float) -> OAuthToken:
        now = int(time.time())
        hard_end = int(auth_time + self.cfg.session_ttl)
        if now >= hard_end:
            raise TokenError("invalid_grant", "session lifetime reached; sign in again")
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        sc = " ".join(scopes)
        a_exp = min(now + self.cfg.access_ttl, hard_end)
        self.db.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (_h(refresh), "refresh", client_id, subject, sc, resource,
                         min(now + self.cfg.refresh_ttl, hard_end), family, auth_time, None))
        self.db.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (_h(access), "access", client_id, subject, sc, resource, a_exp, family, auth_time, _h(refresh)))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=a_exp - now, scope=sc, refresh_token=refresh)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        row = self.db.execute("SELECT auth_time FROM codes WHERE hash=?", (_h(authorization_code.code),)).fetchone()
        cur = self.db.execute("DELETE FROM codes WHERE hash=?", (_h(authorization_code.code),))
        if cur.rowcount != 1 or not row:  # already used
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, authorization_code.subject or "", authorization_code.scopes,
                           authorization_code.resource, secrets.token_hex(16), row[0])

    def revoke_family(self, family: str) -> None:
        self.db.execute("DELETE FROM tokens WHERE family=?", (family,))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = self.db.execute("SELECT client_id, subject, scopes, expires, kind, family FROM tokens "
                              "WHERE hash=? AND kind IN ('refresh','used')", (_h(refresh_token),)).fetchone()
        if not row or row[0] != client.client_id:
            return None
        if row[4] == "used":  # a rotated token came back: someone holds a copy
            log.warning("refresh token replay for %s; revoking its family", row[1])
            self.revoke_family(row[5])
            return None
        if row[3] < time.time():
            return None
        return RefreshToken(token=refresh_token, client_id=row[0], subject=row[1], scopes=row[2].split(),
                            expires_at=row[3], resource=self.cfg.resource_url)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        subject = refresh_token.subject or ""
        if self.directory is not None and hasattr(self.directory, "exists"):
            ok = await anyio.to_thread.run_sync(self.directory.exists, subject)  # await: NSS may ask the directory
            if not ok:
                row = self.db.execute("SELECT family FROM tokens WHERE hash=?", (_h(refresh_token.token),)).fetchone()
                if row:
                    self.revoke_family(row[0])
                log.info("refresh refused for %s: account gone or not in the group", subject)
                raise TokenError("invalid_grant", "account no longer allowed")
        h = _h(refresh_token.token)
        row = self.db.execute("SELECT resource, family, auth_time FROM tokens WHERE hash=? AND kind='refresh'", (h,)).fetchone()
        cur = self.db.execute("UPDATE tokens SET kind='used' WHERE hash=? AND kind='refresh'", (h,))
        if cur.rowcount != 1 or not row:  # a concurrent refresh rotated it first
            raise TokenError("invalid_grant", "refresh token already used")
        self.db.execute("DELETE FROM tokens WHERE kind='access' AND pair=?", (h,))
        return self._issue(client.client_id, subject, scopes or refresh_token.scopes, row[0], row[1], row[2])

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Expired tokens are returned too (the bearer middleware refuses them), so they can be revoked."""
        row = self.db.execute("SELECT client_id, subject, scopes, resource, expires FROM tokens WHERE hash=? AND kind='access'",
                              (_h(token),)).fetchone()
        if not row or not row[1] or not self._our_resource(row[3]):
            return None
        return AccessToken(token=token, client_id=row[0], subject=row[1], scopes=row[2].split(),
                           resource=row[3], expires_at=row[4])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        row = self.db.execute("SELECT family FROM tokens WHERE hash=?", (_h(token.token),)).fetchone()
        if row:
            self.revoke_family(row[0])


# ── per-user stores ──────────────────────────────────────────────────────


@dataclass
class UserStores:
    root: Path
    _open: dict[str, Handbook] = field(default_factory=dict)

    def __call__(self, uid: str) -> Handbook:
        if not UID_RE.match(uid):
            raise ValueError(f"bad uid {uid!r}")
        hb = self._open.get(uid)
        if hb is None:
            (self.root / "users").mkdir(parents=True, exist_ok=True)
            hb = Handbook(self.root / "users" / f"{uid}.db")
            from .research import ensure_cards

            ensure_cards(hb)  # the rs-* cards are there before the first lookup, index or open_entry
            from .kernel import runtime

            runtime.attach(hb)  # the first open after an upgrade migrates this user's store
            self._open[uid] = hb
        return hb


# ── login page ───────────────────────────────────────────────────────────

def _consent(req: str, client: str, dest: str, uid: str, cfg: Config, error: str = "", status: int = 200,
             back: str = "") -> HTMLResponse:
    """Allow `client` to act as `uid`? The user is signed in to the site already (nginx put /login
    behind the sign-in). `back` is the client's redirect origin: CSP form-action also governs the
    redirect after the POST."""
    e = html.escape
    switch = f"{cfg.login_url}?switch=1&next=/login?req={req}"
    body = (f'<section class="card narrow"><h1>Claude 연결</h1>'
            f'<p class="muted"><b>{e(client)}</b>이(가) 연구 원장 접근을 요청합니다.<br>돌아갈 곳: <code>{e(dest)}</code></p>'
            + (f'<div class="flash error">{e(error)}</div>' if error else "")
            + f'<form method="post" action="login"><input type="hidden" name="req" value="{e(req)}">'
            f'<p><b>{e(uid)}</b>(으)로 연결합니다. <a href="{e(switch)}">다른 계정으로</a></p>'
            '<button type="submit" name="action" value="allow">허용</button> '
            '<button class="secondary" type="submit" name="action" value="deny" formnovalidate>취소</button>'
            "</form></section>")
    return page("refhandbook", body, login_url=cfg.login_url, status=status, form_action=f"'self' {back}".strip())


def _origin(uri: str) -> str:
    u = urlparse(uri)
    return f"{u.scheme}://{u.netloc}"


def _message(text: str, status: int) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>refhandbook</title><p>{html.escape(text)}</p>",
                        status_code=status, headers={"Cache-Control": "no-store"})


# ── server ───────────────────────────────────────────────────────────────


def build(cfg: Config, accounts: Accounts | None = None, sso_tokens: SsoTokens | None = None) -> MCPServer:
    """The server: every handbook tool, the OAuth endpoints, /login (consent after the site sign-in),
    the approval page, /healthz.

    The result also carries `provider`, `http_app()` (the ASGI app with this server's host checks)
    and `serve()` (uvicorn on cfg.host:cfg.port).
    """
    from . import research_api, server

    accounts = accounts or Accounts(cfg)
    sso_tokens = sso_tokens or SsoTokens(cfg)
    provider = SQLiteOAuthProvider(cfg, accounts)
    stores = UserStores(cfg.data_dir)
    server._user_store = stores
    os.environ.setdefault("RHB_RUNNER", "external")  # this unit may not create namespaces: the runner unit runs jobs
    research_api.use_resolver(server.handbook)

    public_host = urlparse(cfg.public_url).netloc
    m = server.make(
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=cfg.public_url,  # type: ignore[arg-type]
            resource_server_url=cfg.resource_url,  # type: ignore[arg-type]
            validate_token_resource=True,  # tokens are issued for this server only (audience check)
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=[SCOPE],
        ),
    )
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public_host, "127.0.0.1:*", "localhost:*", *cfg.extra_hosts],
        allowed_origins=[cfg.public_url, "https://claude.ai", "https://claude.com"],
    )
    m.provider = provider  # type: ignore[attr-defined]  (tests and the CLI reach the store through this)
    def http_app():  # noqa: ANN202
        # json_response: a POST is answered with one JSON body, not an event stream, so a proxy that
        # buffers (a router terminating TLS, say) cannot hold a reply back.
        app = m.streamable_http_app(transport_security=security, host=cfg.host, json_response=True)
        _advertise_public_clients(app, m.settings.auth)  # type: ignore[arg-type]
        return app

    def serve() -> None:
        import uvicorn

        uvicorn.run(http_app(), host=cfg.host, port=cfg.port, log_level="info")

    m.http_app = http_app  # type: ignore[attr-defined]
    m.serve = serve  # type: ignore[attr-defined]

    expired = "로그인 요청이 만료되었습니다. Claude에서 연결을 다시 시작하세요."

    def request_of(rid: str):  # noqa: ANN202 — (client_id, AuthorizationParams) of a pending request, or None
        got = provider.pending(rid)
        if got is None:
            return None
        return got[0], got[1]

    async def describe(client_id: str, params: AuthorizationParams) -> tuple[str, str, str]:
        client = await provider.get_client(client_id)
        name = client.client_name if client and client.client_name else client_id
        return name, urlparse(str(params.redirect_uri)).netloc, _origin(str(params.redirect_uri))

    @m.custom_route("/login", methods=["GET"])
    async def login_form(request: Request) -> Response:
        rid = request.query_params.get("req", "")
        got = request_of(rid)
        if got is None:
            return _message(expired, 400)
        name, dest, back = await describe(*got)
        uid = sso_tokens.uid(request.headers.get("x-auth-token", ""))
        if uid is None:  # nginx normally sends the browser to the sign-in page before this
            return RedirectResponse(f"{cfg.login_url}?next=/login?req={rid}", status_code=303)
        return _consent(rid, name, dest, uid, cfg, back=back)

    @m.custom_route("/login", methods=["POST"])
    async def login_submit(request: Request) -> Response:
        """The site sign-in vouches for the user; this checks the token, that the POST came from this
        page, and the account policy, then issues the code."""
        form = await request.form()
        rid = str(form.get("req", ""))[:64]
        got = request_of(rid)
        if got is None:
            return _message(expired, 400)
        client_id, params = got
        name, dest, back = await describe(client_id, params)
        if form.get("action") == "deny":
            log.info("consent declined (client %s): access_denied sent back", client_id)
            return RedirectResponse(provider.deny(rid) or "/", status_code=303)
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != cfg.public_url:
            log.warning("consent POST from foreign origin %s refused", origin)
            return _message("다른 사이트에서 보낸 요청은 받지 않습니다.", 403)
        uid = sso_tokens.uid(request.headers.get("x-auth-token", ""))
        if uid is None:
            return RedirectResponse(f"{cfg.login_url}?next=/login?req={rid}", status_code=303)
        if form.get("action") != "allow":
            return _consent(rid, name, dest, uid, cfg, "허용 또는 취소 버튼으로 제출해 주세요.", 400, back=back)
        if not await anyio.to_thread.run_sync(accounts.exists, uid):
            log.info("consent refused for %s: unknown here or not in the required group", uid)
            return _consent(rid, name, dest, uid, cfg, "이 계정은 핸드북을 쓸 수 없습니다. 관리자에게 문의하세요.", 403,
                            back=back)
        try:
            target = await provider.grant(rid, uid)
        except AuthorizeError:  # a concurrent submit already used this request
            return _message(expired, 400)
        log.info("consent given by %s (client %s)", uid, client_id)
        return RedirectResponse(target, status_code=303)

    from .agents import pages

    pages.install(m, stores=stores, uid_of=sso_tokens.uid, data_dir=Path(cfg.data_dir),
                  public_url=cfg.public_url, lock=server._CALLS, login_url=cfg.login_url, allowed=accounts.exists)

    @m.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> Response:
        return PlainTextResponse("ok")

    return m


def _advertise_public_clients(app, auth: AuthSettings) -> None:  # noqa: ANN001
    """Serve authorization server metadata that lists "none" among the token endpoint's auth methods.

    Claude registers through DCR as a public client (token_endpoint_auth_method "none"), and the SDK
    accepts and authenticates such clients, but its metadata hard-codes only client_secret_post and
    client_secret_basic. The metadata route is replaced so what we advertise matches what we accept.
    """
    from mcp.server.auth.handlers.metadata import MetadataHandler
    from mcp.server.auth.routes import build_metadata, cors_middleware
    from starlette.routing import Route

    metadata = build_metadata(auth.issuer_url, auth.service_documentation_url,
                              auth.client_registration_options or ClientRegistrationOptions(),
                              auth.revocation_options or RevocationOptions())
    methods = ["none", "client_secret_post", "client_secret_basic"]
    metadata.token_endpoint_auth_methods_supported = methods
    if metadata.revocation_endpoint is not None:
        metadata.revocation_endpoint_auth_methods_supported = methods
    path = "/.well-known/oauth-authorization-server"
    for i, r in enumerate(app.router.routes):
        if isinstance(r, Route) and r.path == path:
            app.router.routes[i] = Route(path, endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
                                         methods=["GET", "OPTIONS"])
            return
    raise RuntimeError("authorization server metadata route not found; the SDK layout changed")
