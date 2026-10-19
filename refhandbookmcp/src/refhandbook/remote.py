"""Remote mode: the handbook over Streamable HTTP, one database per directory user.

Claude connects as an OAuth client (dynamic client registration + PKCE). This server is its own
authorization server: /authorize sends the browser to /login, which checks the password against
the LDAP directory and then issues a one-time code. Access tokens carry the directory uid as
`subject`, and every tool call opens that user's database (DATA_DIR/users/<uid>.db).

Configuration comes from the environment (see deploy/refhandbook.env.example).
"""

from __future__ import annotations

import hashlib
import ipaddress
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
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


def _secret(name: str) -> str | None:
    """NAME_FILE (a file holding the secret) wins over NAME."""
    path = _env(name + "_FILE")
    if path:
        return Path(path).read_text().strip()
    return _env(name)


@dataclass
class Config:
    public_url: str  # https://hb.example.org, no trailing slash
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    # How passwords are checked: "pam" (the system's login stack, /etc/pam.d/<pam_service>) or
    # "ldap" (a simple bind as the user; needs the password in the directory or {SASL} pass-through).
    auth: str = "pam"
    pam_service: str = "refhandbook"
    require_group: str | None = None  # pam: a POSIX group (through NSS) the user must belong to
    ldap_uri: str = "ldap://localhost"
    ldap_starttls: bool = False
    ldap_ca_file: str | None = None
    ldap_user_base: str = ""
    ldap_user_filter: str = "(&(objectClass=posixAccount)(uid={uid}))"
    ldap_user_dn: str | None = None  # template, e.g. uid={uid},ou=people,dc=example,dc=org (skips the search)
    ldap_bind_dn: str | None = None  # service account for the search; anonymous when unset
    ldap_bind_password: str | None = None
    ldap_group_base: str | None = None
    ldap_group_filter: str | None = None  # e.g. (&(objectClass=posixGroup)(cn=research)(memberUid={uid}))
    redirect_allow: tuple[str, ...] = DEFAULT_REDIRECTS
    access_ttl: int = 3600
    refresh_ttl: int = 30 * 86400
    session_ttl: int = 90 * 86400  # absolute: a sign-in's tokens end this long after the password was checked
    max_failures: int = 5  # per (uid, client address), and per sign-in request
    max_failures_per_user: int = 50  # per uid across addresses
    lock_seconds: int = 900
    # Reverse proxies in front of this server (addresses or CIDRs): the client address for the
    # sign-in lockout is read from X-Forwarded-For through them. A router that terminates TLS and
    # forwards plain HTTP goes here too.
    trusted_proxies: tuple[str, ...] = ("127.0.0.1", "::1")
    extra_hosts: tuple[str, ...] = ()  # Host headers accepted besides the public host and loopback

    @property
    def resource_url(self) -> str:
        return self.public_url + "/mcp"

    @classmethod
    def from_env(cls) -> Config:
        public = _env("RHB_PUBLIC_URL")
        if not public:
            raise SystemExit("RHB_PUBLIC_URL is required, e.g. https://hb.example.org")
        public = public.rstrip("/")
        p = urlparse(public)
        if p.scheme != "https" and p.hostname not in ("localhost", "127.0.0.1"):
            raise SystemExit("RHB_PUBLIC_URL must be https (Claude only connects to https servers)")
        if p.path not in ("", "/"):
            raise SystemExit("RHB_PUBLIC_URL must be a bare origin (use a subdomain, not a path)")
        allow = _env("RHB_REDIRECT_ALLOW")
        uri = _env("RHB_LDAP_URI", "ldap://localhost") or ""
        starttls = _env("RHB_LDAP_STARTTLS", "0") in ("1", "true", "yes")
        host = urlparse(uri).hostname or ""
        auth = (_env("RHB_AUTH", "pam") or "pam").lower()
        if auth not in ("pam", "ldap"):
            raise SystemExit(f"RHB_AUTH must be pam or ldap, not {auth!r}")
        if auth == "ldap" and uri.startswith("ldap://") and not starttls and host not in ("localhost", "127.0.0.1", "::1") \
                and _env("RHB_LDAP_ALLOW_CLEARTEXT", "0") not in ("1", "true", "yes"):
            raise SystemExit(f"{uri} without StartTLS would send passwords in clear: set RHB_LDAP_STARTTLS=1, "
                             "use ldaps://, or set RHB_LDAP_ALLOW_CLEARTEXT=1")
        return cls(
            auth=auth,
            pam_service=_env("RHB_PAM_SERVICE", "refhandbook"),  # type: ignore[arg-type]
            require_group=_env("RHB_REQUIRE_GROUP"),
            public_url=public,
            data_dir=Path(_env("RHB_DATA_DIR", str(Path.home() / ".refhandbook" / "remote"))),  # type: ignore[arg-type]
            host=_env("RHB_HOST", "127.0.0.1"),  # type: ignore[arg-type]
            port=int(_env("RHB_PORT", "8765")),  # type: ignore[arg-type]
            ldap_uri=uri,
            ldap_starttls=starttls,
            ldap_ca_file=_env("RHB_LDAP_CA_FILE"),
            ldap_user_base=_env("RHB_LDAP_USER_BASE", ""),  # type: ignore[arg-type]
            ldap_user_filter=_env("RHB_LDAP_USER_FILTER", cls.ldap_user_filter),  # type: ignore[arg-type]
            ldap_user_dn=_env("RHB_LDAP_USER_DN"),
            ldap_bind_dn=_env("RHB_LDAP_BIND_DN"),
            ldap_bind_password=_secret("RHB_LDAP_BIND_PASSWORD"),
            ldap_group_base=_env("RHB_LDAP_GROUP_BASE"),
            ldap_group_filter=_env("RHB_LDAP_GROUP_FILTER"),
            redirect_allow=tuple(s.strip() for s in allow.split(",") if s.strip()) if allow else DEFAULT_REDIRECTS,
            access_ttl=int(_env("RHB_ACCESS_TTL", "3600")),  # type: ignore[arg-type]
            refresh_ttl=int(_env("RHB_REFRESH_TTL", str(30 * 86400))),  # type: ignore[arg-type]
            session_ttl=int(_env("RHB_SESSION_TTL", str(90 * 86400))),  # type: ignore[arg-type]
            trusted_proxies=_list("RHB_TRUSTED_PROXIES", ("127.0.0.1", "::1")),
            extra_hosts=_list("RHB_ALLOWED_HOSTS", ()),
        )


def _list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = _env(name)
    if v is None:
        return default
    items = tuple(x.strip() for x in v.split(",") if x.strip())
    for x in items if name == "RHB_TRUSTED_PROXIES" else ():
        ipaddress.ip_network(x, strict=False)  # fail at start on a typo, not at the first sign-in
    return items


def client_address(peer: str, forwarded_for: str, trusted: tuple[str, ...]) -> str:
    """The first address from the right of peer + X-Forwarded-For that is not a trusted proxy.

    Each proxy appends the address it received from, so walking right to left past our own
    proxies reaches the client; anything left of that was written by the client and is ignored.
    """
    nets = [ipaddress.ip_network(t, strict=False) for t in trusted]

    def is_trusted(addr: str) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return any(ip in n for n in nets)

    chain = [a.strip() for a in forwarded_for.split(",") if a.strip()] + [peer]
    for addr in reversed(chain):
        if not is_trusted(addr):
            return addr[:64]
    return peer


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


# ── directory ────────────────────────────────────────────────────────────


class DirectoryUnavailable(Exception):
    """The LDAP server could not be reached or refused the service bind."""


class LdapAuthenticator:
    """Checks a uid/password pair by binding to the directory as that user.

    `authenticate` returns the canonical uid (the entry's own `uid` value) or None. An empty
    password is always refused: an LDAP simple bind with an empty password is an anonymous bind
    and succeeds. `exists` re-checks an account (and the group) without its password; refresh
    tokens are only renewed while it holds.
    """

    def __init__(self, cfg: Config, server: object | None = None, **connection_kwargs: object):
        self.cfg = cfg
        self._server = server
        self._kw = connection_kwargs  # tests pass client_strategy=MOCK_SYNC

    def _server_obj(self):  # noqa: ANN202
        if self._server is not None:
            return self._server
        import ssl

        from ldap3 import Server, Tls

        tls = None
        if self.cfg.ldap_starttls or self.cfg.ldap_uri.startswith("ldaps://"):
            tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=self.cfg.ldap_ca_file)
        return Server(self.cfg.ldap_uri, tls=tls, connect_timeout=5)

    def _conn(self, user: str | None, password: str | None):  # noqa: ANN202
        from ldap3 import Connection

        conn = Connection(self._server_obj(), user=user, password=password, receive_timeout=10, **self._kw)
        conn.open()
        if self.cfg.ldap_starttls:
            conn.start_tls()
        return conn

    def _service(self):  # noqa: ANN202
        svc = self._conn(self.cfg.ldap_bind_dn, self.cfg.ldap_bind_password)
        if not svc.bind():
            raise DirectoryUnavailable(f"service bind refused: {svc.result.get('description')}")
        return svc

    def _find(self, conn, uid: str) -> tuple[str, str] | None:  # noqa: ANN001
        """(dn, canonical uid) of the one entry for uid, read through conn; None if not exactly one."""
        from ldap3 import BASE, SUBTREE
        from ldap3.utils.conv import escape_filter_chars
        from ldap3.utils.dn import escape_rdn

        cfg = self.cfg
        if cfg.ldap_user_dn:
            conn.search(cfg.ldap_user_dn.format(uid=escape_rdn(uid)), "(objectClass=*)", BASE, attributes=["uid"])
        else:
            conn.search(cfg.ldap_user_base, cfg.ldap_user_filter.format(uid=escape_filter_chars(uid)),
                        SUBTREE, attributes=["uid"], size_limit=2)
        entries = list(conn.entries)
        if len(entries) != 1:
            return None
        e = entries[0]
        canonical = uid
        if "uid" in e.entry_attributes and e["uid"].values:
            got = ascii_lower(str(e["uid"].values[0]))
            if got is None or not UID_RE.match(got):
                return None
            canonical = got
        return e.entry_dn, canonical

    def _in_group(self, conn, uid: str, dn: str) -> bool:  # noqa: ANN001
        from ldap3 import SUBTREE
        from ldap3.utils.conv import escape_filter_chars

        cfg = self.cfg
        if not cfg.ldap_group_filter:
            return True
        gfilter = cfg.ldap_group_filter.format(uid=escape_filter_chars(uid), dn=escape_filter_chars(dn))
        conn.search(cfg.ldap_group_base or cfg.ldap_user_base, gfilter, SUBTREE, attributes=["cn"], size_limit=1)
        return bool(conn.entries)

    def authenticate(self, username: str, password: str) -> str | None:
        from ldap3.core.exceptions import LDAPException
        from ldap3.utils.dn import escape_rdn

        uid = ascii_lower(username.strip())
        if not password or uid is None or not UID_RE.match(uid):
            return None
        cfg = self.cfg
        try:
            if cfg.ldap_user_dn:
                dn = cfg.ldap_user_dn.format(uid=escape_rdn(uid))
            else:
                svc = self._service()
                found = self._find(svc, uid)
                svc.unbind()
                if found is None:
                    return None
                dn = found[0]
            conn = self._conn(dn, password)
            if not conn.bind():
                return None
            canonical = self._find_canonical(conn, dn, uid)
            if canonical is None:
                return None
            if not self._in_group(conn, canonical, dn):
                log.info("login refused for %s: not in the required group", canonical)
                return None
            conn.unbind()
            return canonical
        except DirectoryUnavailable:
            raise
        except LDAPException as e:
            raise DirectoryUnavailable(str(e)) from e

    def _find_canonical(self, conn, dn: str, uid: str) -> str | None:  # noqa: ANN001
        from ldap3 import BASE

        conn.search(dn, "(objectClass=*)", BASE, attributes=["uid"])
        if not conn.entries:
            return uid
        e = conn.entries[0]
        if "uid" in e.entry_attributes and e["uid"].values:
            got = ascii_lower(str(e["uid"].values[0]))
            return got if got is not None and UID_RE.match(got) else None
        return uid

    def exists(self, uid: str) -> bool:
        """The account is still there and still in the required group (service or anonymous bind)."""
        from ldap3.core.exceptions import LDAPException

        try:
            svc = self._service()
            found = self._find(svc, uid)
            ok = found is not None and found[1] == uid and self._in_group(svc, uid, found[0])
            svc.unbind()
            return ok
        except DirectoryUnavailable:
            raise
        except LDAPException as e:
            raise DirectoryUnavailable(str(e)) from e


class PamAuthenticator:
    """Checks the password through PAM, the way a system login does.

    /etc/pam.d/<service> includes common-auth, so whatever the host uses for logins (pam_krb5,
    pam_sss, pam_ldap through nslcd, ...) decides the password. Its account phase is pam_permit:
    pam_unix's account check needs root (a setuid/setgid shadow helper) and would refuse every
    directory account from this non-root service. The account policy is ours instead: the name must
    resolve through NSS (which also gives the canonical name) and be in RHB_REQUIRE_GROUP if set.
    No session is opened and no credentials (ticket caches) are kept.
    """

    PAM_AUTHINFO_UNAVAIL = 9  # the backing service (KDC, directory) could not be reached
    PAM_SYSTEM_ERR = 4

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()  # PAM modules are not all safe to run concurrently

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

    def authenticate(self, username: str, password: str) -> str | None:
        import pam

        name = self._account(username)
        if not password or name is None or not UID_RE.match(name):
            return None
        with self._lock:
            p = pam.PamAuthenticator()
            ok = p.authenticate(name, password, service=self.cfg.pam_service, resetcreds=False)
        if not ok:
            if p.code in (self.PAM_AUTHINFO_UNAVAIL, self.PAM_SYSTEM_ERR):
                raise DirectoryUnavailable(f"PAM: {p.reason}")
            log.info("PAM refused %s: %s", name, p.reason)
            return None
        if not self._in_group(name):
            log.info("login refused for %s: not in group %s", name, self.cfg.require_group)
            return None
        return name

    def exists(self, uid: str) -> bool:
        return self._account(uid) == uid and self._in_group(uid)


def make_authenticator(cfg: Config) -> object:
    return PamAuthenticator(cfg) if cfg.auth == "pam" else LdapAuthenticator(cfg)


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
MAX_FAILURE_KEYS = 10000


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class SQLiteOAuthProvider:
    """OAuthAuthorizationServerProvider backed by DATA_DIR/auth.db. Codes and tokens are stored hashed.

    All database work is synchronous and the server runs one event loop, so each method body is
    atomic between its awaits; the only awaits on a write path are marked.
    """

    def __init__(self, cfg: Config, directory: object | None = None):
        self.cfg = cfg
        self.directory = directory  # has exists(uid) -> bool; refreshes re-check the account through it
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(cfg.data_dir / "auth.db"), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(AUTH_SCHEMA)
        self.failures: dict[tuple[str, str], list[float]] = {}

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

    def reserve_attempt(self, rid: str) -> bool:
        """Count a password attempt on this sign-in request before checking it; False once used up."""
        cur = self.db.execute("UPDATE pending SET attempts=attempts+1 WHERE id=? AND attempts<?",
                              (rid, self.cfg.max_failures))
        return cur.rowcount == 1

    # lockout: per (uid, client address), plus a higher ceiling per uid across addresses
    def _recent(self, key: tuple[str, str], now: float) -> list[float]:
        recent = [t for t in self.failures.get(key, []) if now - t < self.cfg.lock_seconds]
        if recent:
            self.failures[key] = recent
        else:
            self.failures.pop(key, None)
        return recent

    def locked(self, uid: str, addr: str) -> bool:
        now = time.time()
        if len(self._recent((uid, addr), now)) >= self.cfg.max_failures:
            return True
        return len(self._recent((uid, "*"), now)) >= self.cfg.max_failures_per_user

    def note_failure(self, uid: str, addr: str) -> float:
        """Record a failure now (before the check finishes); returns a stamp to retract on success."""
        if len(self.failures) > MAX_FAILURE_KEYS:
            now = time.time()
            for key in list(self.failures):
                self._recent(key, now)
            while len(self.failures) > MAX_FAILURE_KEYS:
                self.failures.pop(next(iter(self.failures)))
        stamp = time.time()
        self.failures.setdefault((uid, addr), []).append(stamp)
        self.failures.setdefault((uid, "*"), []).append(stamp)
        return stamp

    def retract_failure(self, uid: str, addr: str, stamp: float) -> None:
        for key in ((uid, addr), (uid, "*")):
            lst = self.failures.get(key, [])
            if stamp in lst:
                lst.remove(stamp)

    async def grant(self, rid: str, subject: str) -> str:
        """Called by /login after the password check: issue a code, return the client redirect."""
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
            try:
                ok = await anyio.to_thread.run_sync(self.directory.exists, subject)  # await: directory I/O
            except DirectoryUnavailable as e:
                log.error("directory unavailable during refresh: %s", e)
                raise TokenError("invalid_grant", "cannot confirm the account now; sign in again later") from e
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

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>refhandbook 로그인</title>
<style>
:root{{--bg:#f6f5f2;--fg:#1d1d1b;--mute:#6b6a66;--card:#fff;--line:#d9d7d0;--acc:#2f5d50;--err:#a33}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mute:#9a9892;--card:#20201e;--line:#3a3935;--acc:#7fb8a4;--err:#e88}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}
main{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;width:min(360px,calc(100vw - 32px));box-sizing:border-box}}
h1{{font-size:20px;margin:0 0 4px}} p{{color:var(--mute);margin:0 0 18px;font-size:14px}}
label{{display:block;font-size:13px;margin:12px 0 4px}}
input{{width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--fg);font-size:16px}}
.row{{display:flex;flex-direction:row-reverse;gap:8px;margin-top:20px}} button{{flex:1;padding:10px;border-radius:8px;border:1px solid var(--acc);font-size:15px;cursor:pointer}}
.go{{background:var(--acc);color:var(--card)}} .no{{background:transparent;color:var(--fg);border-color:var(--line)}}
.err{{color:var(--err);font-size:14px;margin:0 0 8px}}
</style></head><body><main>
<h1>refhandbook</h1>
<p><b>{client}</b>이(가) 연구 원장 접근을 요청합니다.<br>돌아갈 곳: {dest}</p>
{error}
<form method="post" action="login">
<input type="hidden" name="req" value="{req}">
<label for="u">디렉터리 사용자명</label><input id="u" name="username" autocomplete="username" required autofocus>
<label for="p">비밀번호</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<div class="row"><button class="go" type="submit" name="action" value="allow">로그인</button>
<button class="no" type="submit" name="action" value="deny" formnovalidate>취소</button></div>
</form></main></body></html>"""


def _page(req: str, client: str, dest: str, error: str = "", status: int = 200, back: str = "") -> HTMLResponse:
    """`back` is the client's redirect origin: CSP form-action also governs the redirect after the POST."""
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    body = PAGE.format(req=html.escape(req), client=html.escape(client), dest=html.escape(dest), error=err)
    return HTMLResponse(body, status_code=status, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; form-action 'self' {back}; frame-ancestors 'none'",
        "Referrer-Policy": "no-referrer",
    })


def _origin(uri: str) -> str:
    u = urlparse(uri)
    return f"{u.scheme}://{u.netloc}"


def _message(text: str, status: int) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>refhandbook</title><p>{html.escape(text)}</p>",
                        status_code=status, headers={"Cache-Control": "no-store"})


# ── server ───────────────────────────────────────────────────────────────


def build(cfg: Config, authenticator: object | None = None) -> MCPServer:
    """The remote server: every handbook tool, OAuth endpoints, /login, /healthz.

    The result also carries `provider`, `http_app()` (the ASGI app with this server's host checks)
    and `serve()` (uvicorn on cfg.host:cfg.port).
    """
    from . import research_api, server

    auth_fn = authenticator or make_authenticator(cfg)
    provider = SQLiteOAuthProvider(cfg, auth_fn)
    stores = UserStores(cfg.data_dir)
    server._user_store = stores
    research_api.use_resolver(server.handbook)

    public_host = urlparse(cfg.public_url).netloc
    m = MCPServer(
        "refhandbook",
        instructions=server.INSTRUCTIONS,
        version=server.mcp.version,
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
    server.install(m)
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

    @m.custom_route("/login", methods=["GET"])
    async def login_form(request: Request) -> Response:
        rid = request.query_params.get("req", "")
        got = provider.pending(rid)
        if got is None:
            return _message(expired, 400)
        client = await provider.get_client(got[0])
        name = (client.client_name if client and client.client_name else got[0])
        return _page(rid, name, urlparse(str(got[1].redirect_uri)).netloc, back=_origin(str(got[1].redirect_uri)))

    def client_addr(request: Request) -> str:
        peer = request.client.host if request.client else ""
        return client_address(peer, request.headers.get("x-forwarded-for", ""), cfg.trusted_proxies)

    @m.custom_route("/login", methods=["POST"])
    async def login_submit(request: Request) -> Response:
        form = await request.form()
        rid = str(form.get("req", ""))[:64]
        got = provider.pending(rid)
        if got is None:
            return _message(expired, 400)
        client_id, params, _ = got
        client = await provider.get_client(client_id)
        name = (client.client_name if client and client.client_name else client_id)
        dest = urlparse(str(params.redirect_uri)).netloc
        back = _origin(str(params.redirect_uri))
        if form.get("action") == "deny":
            log.info("sign-in cancelled by the user (client %s): access_denied sent back", client_id)
            return RedirectResponse(provider.deny(rid) or "/", status_code=303)
        if form.get("action") != "allow":
            return _page(rid, name, dest, "로그인 버튼으로 제출해 주세요.", 400, back=back)
        # Everything below up to the directory call runs without an await, so concurrent posts
        # cannot all pass the checks before one of them is counted.
        if not provider.reserve_attempt(rid):
            provider.drop_pending(rid)
            return _message("시도 횟수를 넘었습니다. Claude에서 연결을 다시 시작하세요.", 429)
        user = ascii_lower(str(form.get("username", "")).strip()[:64])
        password = str(form.get("password", ""))[:1024]
        if not user or not UID_RE.match(user) or not password:
            return _page(rid, name, dest, "사용자명 또는 비밀번호가 맞지 않습니다.", 401, back=back)
        addr = client_addr(request)
        if provider.locked(user, addr):
            return _page(rid, name, dest, "잠시 잠겼습니다. 15분 뒤 다시 시도하세요.", 429, back=back)
        stamp = provider.note_failure(user, addr)  # counted now, retracted on success
        try:
            uid = await anyio.to_thread.run_sync(auth_fn.authenticate, user, password)  # type: ignore[attr-defined]
        except DirectoryUnavailable as e:
            provider.retract_failure(user, addr, stamp)
            log.error("directory unavailable: %s", e)
            return _page(rid, name, dest, "디렉터리 서버에 연결할 수 없습니다.", 503, back=back)
        if not uid:
            log.info("login failed for %s from %s", user, addr)
            return _page(rid, name, dest, "사용자명 또는 비밀번호가 맞지 않습니다.", 401, back=back)
        provider.retract_failure(user, addr, stamp)
        try:
            target = await provider.grant(rid, uid)
        except AuthorizeError:  # a concurrent submit already used this request
            return _message(expired, 400)
        log.info("login ok for %s from %s (client %s)", uid, addr, client_id)
        return RedirectResponse(target, status_code=303)

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
