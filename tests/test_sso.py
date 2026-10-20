"""The site sign-in (portal/sso.py), its tokens, and the portal behind it (PORTAL_AUTH=sso)."""
import re
from base64 import b64encode

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from portal import tokens
from portal.kerberos import KerberosError
from portal.config import Settings
from portal.main import create_app as create_portal
from portal.invites import InviteStore
from portal.requests import RequestStore
from portal.sso import create_app, next_from_query, safe_next
from conftest import SITE
from test_app import FakeDirectory, FakeKAdmin, FakeKerberos

ISS = "https://www.m00nny.kr"


class CountingKerberos(FakeKerberos):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def verify_password(self, principal, password):
        self.calls += 1
        return super().verify_password(principal, password)


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def sso(tmp_path, key):
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False,
                 audit_log=str(tmp_path / "audit.log"), sso_issuer=ISS)
    k = CountingKerberos()
    return s, k, create_app(s, k, key)


def csrf(c, path):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def sign_in(app, uid="alice", pw="alice-password-1", nxt="/"):
    c = TestClient(app)
    r = c.post("/auth/login", data={"uid": uid, "password": pw, "next": nxt, "csrf": csrf(c, "/auth/login")},
               follow_redirects=False)
    return c, r


def check(c, uri, **headers):
    return c.get("/auth/check", headers={"X-Original-URI": uri, **headers})


def basic(uid, pw):
    return {"Authorization": "Basic " + b64encode(f"{uid}:{pw}".encode()).decode()}


def test_cookie_sign_in_and_token(sso, key):
    s, k, app = sso
    anon = TestClient(app)
    r = check(anon, "/account/", **{"X-Auth-Audience": "account"})
    assert r.status_code == 401 and "www-authenticate" not in r.headers  # nginx redirects browsers instead
    c, r = sign_in(app, nxt="/account/users")
    assert r.status_code == 303 and r.headers["location"] == "/account/users"
    cookie = r.headers["set-cookie"].lower()
    assert "path=/;" in cookie and "samesite=lax" in cookie and "httponly" in cookie
    r = check(c, "/account/", **{"X-Auth-Audience": "account"})
    assert r.status_code == 200 and r.headers["x-remote-user"] == "alice"
    pub = key.public_key()
    assert tokens.verify(pub, r.headers["x-auth-token"], ISS, "account") == "alice"
    with pytest.raises(tokens.TokenError):  # minted for the portal, refused by the handbook
        tokens.verify(pub, r.headers["x-auth-token"], ISS, "refhandbook")
    assert check(c, "/x", **{"X-Auth-Audience": "nope"}).status_code == 500  # unknown audience: fail closed
    assert "x-auth-token" not in check(c, "/x").headers  # no audience named, no token


def test_wrong_password_expired_and_logout(sso):
    s, k, app = sso
    _, r = sign_in(app, pw="wrong")
    assert r.status_code == 401 and "맞지 않습니다" in r.text
    k.expired.add("alice")
    c, r = sign_in(app, nxt="/login?req=abc")
    assert r.headers["location"] == "/auth/expired"
    c.post("/auth/expired", data={"uid": "alice", "old": "alice-password-1", "new": "fresh-password-22",
                                  "confirm": "fresh-password-22", "csrf": csrf(c, "/auth/expired")})
    assert k.passwords["alice"] == "fresh-password-22"
    c, r = sign_in(app, pw="fresh-password-22")
    assert check(c, "/account/").status_code == 200
    c.post("/auth/logout", data={"csrf": csrf(c, "/auth/logout")})
    assert check(c, "/account/").status_code == 401


def test_basic_is_not_a_sign_in(sso):
    """Only the site cookie signs in: a password in a Basic header is never checked."""
    s, k, app = sso
    r = check(TestClient(app), "/account/", **basic("alice", "alice-password-1"))
    assert r.status_code == 401 and "www-authenticate" not in r.headers and k.calls == 0


def test_next_helpers():
    for bad in ("//evil.example/", "https://evil.example/", "/\\evil", "javascript:alert(1)", "", "/a\nb"):
        assert safe_next(bad) == "/"
    assert safe_next("/account/users?q=a") == "/account/users?q=a"
    assert next_from_query("next=/login?req=abc&x=1") == "/login?req=abc&x=1"
    assert next_from_query("next=//evil.example") == "/"
    assert next_from_query("switch=1&next=/login?req=abc") == "/login?req=abc"


def test_portal_behind_sso(tmp_path, key):
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="", root_path="/account", auth_mode="sso", sso_issuer=ISS)
    d, k = FakeDirectory(s), FakeKerberos()
    app = create_portal(s, d, k, FakeKAdmin(k, d), RequestStore(str(tmp_path / "req.db")), key.public_key(),
                         InviteStore(":memory:"))
    c = TestClient(app)
    r = c.get("/account/admin/users", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/auth/login?next=/account/admin/users"
    assert c.get("/account/login", follow_redirects=False).headers["location"].startswith("/auth/login")
    # a bare user header, a token for another backend, a forged or expired one: all refused
    other = Ed25519PrivateKey.generate()
    for tok in (tokens.issue(key, ISS, "refhandbook", "moon"), tokens.issue(other, ISS, "account", "moon"),
                tokens.issue(key, ISS, "account", "moon", ttl=-60), "garbage"):
        r = c.get("/account/admin/users", headers={"X-Auth-Token": tok, "X-Remote-User": "moon"}, follow_redirects=False)
        assert r.status_code == 303
    good = {"X-Auth-Token": tokens.issue(key, ISS, "account", "moon")}
    assert c.get("/account/admin/users", headers=good).status_code == 200
    page = c.get("/account/", headers=good).text
    assert 'href="/auth/logout"' in page
    # actions still need the portal's CSRF token, and roles still come from LDAP
    t = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = c.post("/account/admin/users/alice/reset", data={"csrf": t}, headers=good)
    assert r.status_code == 200 and "One-time password" in r.text
    alice = {"X-Auth-Token": tokens.issue(key, ISS, "account", "alice")}
    assert c.get("/account/admin/users", headers=alice).status_code == 403
    assert c.post("/account/login", data={}).status_code == 403  # no local sign-in in sso mode
    assert c.get("/account/request").status_code == 200  # the request form stays public


APPS = """
[[app]]
id = "agents"
title = "Agents"
audience = "refhandbook"
upstream = "http://127.0.0.1:8765"
menu = "Agents"
menu_href = "/agents"
  [[app.route]]
  path = "/agents"
[[app]]
id = "lab"
title = "Lab"
audience = "lab"
upstream = "http://127.0.0.1:9000"
groups = ["admin"]
menu = "Lab"
menu_href = "/lab/"
  [[app.route]]
  path = "/lab/"
"""


def test_the_menu_shows_the_apps_each_user_may_see(tmp_path, key):
    apps = tmp_path / "site.toml"
    apps.write_text(APPS)
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="", root_path="/account", auth_mode="sso", sso_issuer=ISS, site_file=str(apps))
    d, k = FakeDirectory(s), FakeKerberos()
    c = TestClient(create_portal(s, d, k, FakeKAdmin(k, d), RequestStore(str(tmp_path / "req.db")), key.public_key(),
                         InviteStore(":memory:")))
    page = c.get("/account/", headers={"X-Auth-Token": tokens.issue(key, ISS, "account", "moon")}).text
    assert 'href="/agents">Agents</a>' in page and 'href="/lab/">Lab</a>' in page  # moon is an admin
    page = c.get("/account/", headers={"X-Auth-Token": tokens.issue(key, ISS, "account", "alice")}).text
    assert 'href="/agents">Agents</a>' in page and "/lab/" not in page


def test_the_sso_mints_for_the_audiences_the_apps_declare(tmp_path, key):
    apps = tmp_path / "site.toml"
    apps.write_text(APPS)
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False, audit_log=str(tmp_path / "a.log"),
                 sso_issuer=ISS, sso_audiences=("account",), site_file=str(apps))
    c, _ = sign_in(create_app(s, CountingKerberos(), key))
    r = check(c, "/lab/", **{"X-Auth-Audience": "lab"})
    assert r.status_code == 200 and tokens.verify(key.public_key(), r.headers["x-auth-token"], ISS, "lab") == "alice"
    assert check(c, "/x", **{"X-Auth-Audience": "nope"}).status_code == 500


def test_the_main_page_knows_who_is_signed_in(tmp_path, key):
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False,
                 audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE))
    app = create_app(s, FakeKerberos(), key)
    page = TestClient(app).get("/").text
    assert 'href="/auth/login">로그인' in page and 'href="/account/request"' in page and "로그아웃" not in page
    for title in ("계정", "에이전트 · 샌드박스", "핸드북 (Claude MCP)"):  # a card per app of the site file
        assert f"<h2>{title}</h2>" in page
    assert "https://www.m00nny.kr/mcp</code>" in page  # the derived domain
    c, _ = sign_in(app)
    page = c.get("/").text
    assert "<code>alice</code> 님" in page and 'href="/auth/logout">로그아웃' in page and 'href="/account/"' in page


def test_a_broken_keytab_is_a_message_not_a_crash(sso, tmp_path):
    s, k, app = sso

    def broken(principal, password):
        raise KerberosError("KDC verification against HTTP@www.m00nny.kr failed: keytab is nonexistent")
    k.verify_password = broken
    _, r = sign_in(app)
    assert r.status_code == 503 and "관리자에게 알려 주세요" in r.text and "keytab" not in r.text
    assert "keytab is nonexistent" in (tmp_path / "audit.log").read_text()
