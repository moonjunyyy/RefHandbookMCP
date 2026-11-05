"""The handbook server: OAuth with consent after the site sign-in, per-user stores, the MCP endpoint
over HTTP, and the approval page."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from refhandbook import remote, research_api, server

BASE = "http://localhost:8765"
ISS = "https://www.m00nny.kr"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class FakeAccounts:
    """The account policy (NSS + group) in remote.Accounts; here a set of uids."""

    def __init__(self, uids):
        self.present = set(uids)

    def exists(self, uid):
        return uid in self.present


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def cfg(tmp_path):
    return remote.Config(public_url=BASE, data_dir=tmp_path / "data", sso_public_key_file="(given)", sso_issuer=ISS)


@pytest.fixture
def accounts():
    return FakeAccounts({"moon", "kim"})


@pytest.fixture
def built(cfg, accounts, key):
    m = remote.build(cfg, accounts, remote.SsoTokens(cfg, key.public_key()))
    m.key = key  # type: ignore[attr-defined]
    try:
        yield m
    finally:  # the stores are bound per server
        server._user_store = None
        research_api.use_resolver(None)


@pytest.fixture
def client(built):
    with TestClient(built.http_app(), base_url=BASE) as c:
        c.provider, c.key = built.provider, built.key  # type: ignore[attr-defined]
        yield c


def site_token(key, uid="moon", aud="refhandbook", ttl=60):
    """What the site sign-in (portal.sso) mints for this app, and nginx passes in X-Auth-Token."""
    now = int(time.time())
    return jwt.encode({"iss": ISS, "aud": aud, "sub": uid, "iat": now, "exp": now + ttl}, key, algorithm="EdDSA")


def as_user(key, uid="moon"):
    return {"X-Auth-Token": site_token(key, uid), "Origin": BASE}


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def register(c, redirect=CALLBACK):
    return c.post("/register", json={"redirect_uris": [redirect], "client_name": "Claude",
                                     "token_endpoint_auth_method": "none",
                                     "grant_types": ["authorization_code", "refresh_token"]})


def start(c, client_id, challenge, state="st-1"):
    r = c.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "refhandbook",
        "resource": BASE + "/mcp"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = urlparse(r.headers["location"])
    assert loc.path == "/login"
    return parse_qs(loc.query)["req"][0]


def allow(c, req, uid="moon"):
    return c.post("/login", data={"req": req, "action": "allow"}, headers=as_user(c.key, uid), follow_redirects=False)


def sign_in(c, user="moon"):
    """The full flow, signed in to the site as `user`; returns (token response, client_id)."""
    cid = register(c).json()["client_id"]
    verifier, challenge = pkce()
    r = allow(c, start(c, cid, challenge), user)
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["state"] == ["st-1"]
    tok = c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": CALLBACK,
                                 "client_id": cid, "code_verifier": verifier, "resource": BASE + "/mcp"})
    assert tok.status_code == 200, tok.text
    return tok.json(), cid


def rpc(c, token, method, params=None, session=None, rid=1):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["mcp-session-id"] = session
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if rid is not None:
        body["id"] = rid
    r = c.post("/mcp", headers=headers, json=body)
    if rid is None:
        return r, None
    data = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
    return r, (data[-1] if data else r.json())


def mcp_session(c, token):
    r, msg = rpc(c, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "0"}})
    assert r.status_code == 200, r.text
    sid = r.headers["mcp-session-id"]
    rpc(c, token, "notifications/initialized", session=sid, rid=None)
    return sid


def call(c, token, sid, name, args, rid=2):
    _, msg = rpc(c, token, "tools/call", {"name": name, "arguments": args}, session=sid, rid=rid)
    return msg["result"]


# ── discovery and refusal without a token ────────────────────────────────


def test_metadata_and_401(client):
    prm = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"].rstrip("/") == BASE + "/mcp"
    assert [s.rstrip("/") for s in prm["authorization_servers"]] == [BASE]
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["registration_endpoint"].endswith("/register")
    assert "S256" in asm["code_challenge_methods_supported"]
    assert "none" in asm["token_endpoint_auth_methods_supported"]  # Claude registers as a public client
    assert asm["issuer"].rstrip("/") == BASE
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert client.get("/healthz").text == "ok"


def test_every_authorization_response_names_this_server(client):
    """RFC 9207: the metadata says so, and the code, a denial and the SDK's own error redirects all carry
    `iss` equal to the metadata's issuer string (exact comparison: a client keys its callback on it)."""
    asm = client.get("/.well-known/oauth-authorization-server").json()
    prm = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert asm["authorization_response_iss_parameter_supported"] is True
    iss = asm["issuer"]
    assert prm["authorization_servers"] == [iss]
    q = lambda loc: parse_qs(urlparse(loc).query)  # noqa: E731
    # the code
    cid = register(client).json()["client_id"]
    r = allow(client, start(client, cid, pkce()[1]))
    assert r.status_code == 303 and q(r.headers["location"])["iss"] == [iss] and "code" in q(r.headers["location"])
    # a denial
    d = client.post("/login", data={"req": start(client, cid, pkce()[1]), "action": "deny"}, follow_redirects=False)
    assert q(d.headers["location"])["error"] == ["access_denied"] and q(d.headers["location"])["iss"] == [iss]
    # an error the SDK's /authorize sends back itself (a scope the client may not have), and one the
    # provider raises there (a resource that is not this server)
    base = {"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "state": "s",
            "code_challenge": pkce()[1], "code_challenge_method": "S256"}
    for extra in ({"scope": "other"}, {"scope": "refhandbook", "resource": "https://other.example/mcp"}):
        e = client.get("/authorize", params={**base, **extra}, follow_redirects=False)
        assert e.status_code == 302, e.text
        assert "error" in q(e.headers["location"]) and q(e.headers["location"])["iss"] == [iss], e.headers["location"]
        assert q(e.headers["location"])["state"] == ["s"]
    # /authorize's step to this server's own /login is not an authorization response: no iss
    ok = client.get("/authorize", params={**base, "scope": "refhandbook", "resource": BASE + "/mcp"}, follow_redirects=False)
    assert urlparse(ok.headers["location"]).path == "/login" and "iss" not in q(ok.headers["location"])


def test_the_issuer_is_the_metadata_string_whatever_the_origin_looks_like(tmp_path, accounts, key):
    """`iss` is taken from the metadata as served, not rebuilt from the setting, so the two cannot drift."""
    for origin in ("https://www.example.org", "http://localhost:8765"):
        cfg = remote.Config(public_url=origin, data_dir=tmp_path / origin.split("//")[1].replace(":", "_"),
                            sso_public_key_file="(given)", sso_issuer=ISS, extra_hosts=(urlparse(origin).netloc,))
        m = remote.build(cfg, accounts, remote.SsoTokens(cfg, key.public_key()))
        try:
            with TestClient(m.http_app(), base_url=origin) as c:
                assert m.provider.issuer == c.get("/.well-known/oauth-authorization-server").json()["issuer"]
        finally:
            server._user_store = None
            research_api.use_resolver(None)


def test_registration_refuses_foreign_redirects(client):
    assert register(client, "https://evil.example/cb").status_code == 400
    assert register(client, "http://localhost:53682/callback").status_code == 201  # Claude Code's loopback


# ── consent after the site sign-in ───────────────────────────────────────


def test_full_flow_and_per_user_isolation(client, cfg):
    t_moon, _ = sign_in(client, "moon")
    t_kim, _ = sign_in(client, "kim")
    s1 = mcp_session(client, t_moon["access_token"])
    tools = rpc(client, t_moon["access_token"], "tools/list", session=s1, rid=9)[1]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"lookup", "open_entry", "research_begin", "research_end", "research_doc"} <= names

    refused = call(client, t_moon["access_token"], s1, "research_end", {"ledger": "none", "session": "x"}, rid=7)
    assert refused["isError"] and "no ledger 'none'" in refused["content"][0]["text"]  # the reason survives mcp 2
    out = call(client, t_moon["access_token"], s1, "research_ledgers",
               {"action": "init", "ledger": "gauss", "question": "Gaussian on the t-measure"})
    assert not out.get("isError"), out
    listed = call(client, t_moon["access_token"], s1, "research_ledgers", {"action": "list"}, rid=3)
    assert "gauss" in listed["content"][0]["text"]

    s2 = mcp_session(client, t_kim["access_token"])
    other = call(client, t_kim["access_token"], s2, "research_ledgers", {"action": "list"}, rid=4)
    assert "gauss" not in other["content"][0]["text"]
    # the research cards are in every user's store
    card = call(client, t_kim["access_token"], s2, "open_entry", {"id": "rs-n1"}, rid=5)
    assert "Session loop" in card["content"][0]["text"]
    assert (cfg.data_dir / "users" / "moon.db").exists() and (cfg.data_dir / "users" / "kim.db").exists()


def test_consent_page_and_deny(client):
    cid = register(client).json()["client_id"]
    req = start(client, cid, pkce()[1])
    r = client.get("/login", params={"req": req}, follow_redirects=False)  # not signed in to the site
    assert r.status_code == 303 and r.headers["location"] == f"/auth/login?next=/login?req={req}"
    page = client.get("/login", params={"req": req}, headers=as_user(client.key))
    assert page.status_code == 200 and "<b>moon</b>" in page.text and "허용" in page.text and "password" not in page.text
    assert f"/auth/login?switch=1&amp;next=/login?req={req}" in page.text
    assert "/auth/static/style.css" in page.text  # the site's look, from the site's stylesheet
    assert "<a class=brand href='/'>" in page.text  # back to the site's main page
    assert "form-action 'self' https://claude.ai" in page.headers["content-security-policy"]
    # under no-referrer the browser would send Origin: null with 허용, which the POST refuses as foreign
    assert page.headers["referrer-policy"] == "same-origin"
    d = client.post("/login", data={"req": req, "action": "deny"}, follow_redirects=False)  # cancel needs no token
    assert d.status_code == 303 and "error=access_denied" in d.headers["location"]
    assert client.get("/login", params={"req": req}, headers=as_user(client.key)).status_code == 400  # consumed


def test_consent_refuses_bad_tokens_foreign_posts_and_accounts(client):
    cid = register(client).json()["client_id"]
    req = start(client, cid, pkce()[1])
    other = Ed25519PrivateKey.generate()
    for bad in (site_token(client.key, aud="account"), site_token(other), site_token(client.key, ttl=-60), "junk"):
        r = client.post("/login", data={"req": req, "action": "allow"},
                        headers={"X-Auth-Token": bad, "X-Remote-User": "moon", "Origin": BASE}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/auth/login")
    r = client.post("/login", data={"req": req, "action": "allow"},
                    headers={**as_user(client.key), "Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403  # a POST from another site, even with a valid token
    client.provider.directory.present.discard("kim")
    r = allow(client, req, "kim")
    assert r.status_code == 403 and "쓸 수 없습니다" in r.text  # signed in, but not allowed here
    assert remote.SsoTokens(client.provider.cfg, client.key.public_key()).uid(site_token(client.key, "\u212aim")) is None


def test_enter_submits_allow_not_cancel(client):
    """Pressing Enter submits with the form's first submit button (HTML implicit submission): it must
    be allow, or every Enter sends access_denied back to the client."""
    import re as _re

    cid = register(client).json()["client_id"]
    _, challenge = pkce()
    page = client.get("/login", params={"req": start(client, cid, challenge)}, headers=as_user(client.key)).text
    first = _re.search(r'<button[^>]*name="action"[^>]*value="(\w+)"', page)
    assert first and first.group(1) == "allow"
    req = start(client, cid, challenge)  # a submit without an action value (some clients) is not a cancel
    r = client.post("/login", data={"req": req}, headers=as_user(client.key), follow_redirects=False)
    assert r.status_code == 400 and "access_denied" not in r.headers.get("location", "")


def test_code_single_use_refresh_rotation_revoke(client):
    cid = register(client).json()["client_id"]
    verifier, challenge = pkce()
    r = allow(client, start(client, cid, challenge))
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "client_id": cid,
            "code_verifier": verifier}
    assert client.post("/token", data={**form, "code_verifier": "wrong" * 10}).status_code == 400
    tok = client.post("/token", data=form)
    assert tok.status_code == 200
    assert client.post("/token", data=form).status_code == 400  # code already used
    t = tok.json()

    new = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": cid})
    assert new.status_code == 200, new.text
    again = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": cid})
    assert again.status_code == 400  # rotated
    old_access = rpc(client, t["access_token"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                               "clientInfo": {"name": "x", "version": "0"}})[0]
    assert old_access.status_code == 401  # the old pair died with the rotation

    n = new.json()
    assert client.post("/revoke", data={"token": n["access_token"], "client_id": cid, "client_secret": ""}).status_code == 200
    gone = rpc(client, n["access_token"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                         "clientInfo": {"name": "x", "version": "0"}})[0]
    assert gone.status_code == 401


def test_tokens_stored_hashed(client, cfg):
    t, _ = sign_in(client)
    import sqlite3

    raw = sqlite3.connect(cfg.data_dir / "auth.db").execute("SELECT hash FROM tokens").fetchall()
    assert raw and all(t["access_token"] != h[0] and t["refresh_token"] != h[0] for h in raw)


def test_wrong_resource_refused(client):
    cid = register(client).json()["client_id"]
    _, challenge = pkce()
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "state": "s",
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": "https://other.example/mcp"},
        follow_redirects=False)
    assert "location" not in r.headers or "/login" not in r.headers["location"]


# ── configuration ───────────────────────────────────────────────────────


@pytest.fixture
def site_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RHB_PUBLIC_URL", ISS)
    monkeypatch.setenv("RHB_SSO_PUBLIC_KEY_FILE", str(tmp_path / "sso-public.pem"))
    monkeypatch.setenv("RHB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RHB_PORT", "8765")
    return monkeypatch


def test_a_note_after_a_url_setting_is_refused_at_start(site_env):
    """systemd keeps "https://x   (default: …)" as the whole value; the token check would then fail
    on every request with only "Invalid issuer" to show for it."""
    site_env.setenv("RHB_SSO_ISSUER", f"{ISS}      (default: RHB_PUBLIC_URL)")
    with pytest.raises(SystemExit, match="RHB_SSO_ISSUER"):
        remote.Config.from_env()
    site_env.setenv("RHB_SSO_ISSUER", ISS)
    assert remote.Config.from_env().sso_issuer == ISS
    site_env.delenv("RHB_SSO_ISSUER")
    assert remote.Config.from_env().sso_issuer == ISS  # the public URL


def test_config_needs_the_site_and_takes_the_units_state_directory(site_env, tmp_path):
    c = remote.Config.from_env()
    assert c.public_url == ISS and c.resource_url == ISS + "/mcp" and c.data_dir == tmp_path / "data"
    site_env.delenv("RHB_DATA_DIR")
    site_env.setenv("STATE_DIRECTORY", str(tmp_path / "state"))  # systemd's StateDirectory=
    assert remote.Config.from_env().data_dir == tmp_path / "state"
    site_env.delenv("STATE_DIRECTORY")
    with pytest.raises(SystemExit, match="RHB_DATA_DIR"):
        remote.Config.from_env()
    site_env.setenv("RHB_DATA_DIR", str(tmp_path / "data"))
    site_env.delenv("RHB_SSO_PUBLIC_KEY_FILE")
    with pytest.raises(SystemExit, match="RHB_SSO_PUBLIC_KEY_FILE"):
        remote.Config.from_env()  # no default: the installer passes the site's key
    site_env.setenv("RHB_SSO_PUBLIC_KEY_FILE", "/k.pem")
    for bad in ("http://hb.example.org", "https://hb.example.org/sub"):
        site_env.setenv("RHB_PUBLIC_URL", bad)
        with pytest.raises(SystemExit):
            remote.Config.from_env()


def test_redirects_are_matched_strictly():
    allow_ = remote.DEFAULT_REDIRECTS
    assert remote.redirect_allowed("http://localhost:4312/callback", allow_)
    assert remote.redirect_allowed(CALLBACK, allow_)
    for bad in ("https://claude.ai.evil.example/api/mcp/auth_callback", "http://localhost.evil.example:80/cb",
                "http://evil.example\\@localhost/", "http://user@localhost:5000/cb", "http://localhost:5000/cb#frag",
                "javascript://localhost:5000/"):
        assert not remote.redirect_allowed(bad, allow_), bad


def test_env_file(tmp_path, monkeypatch):
    from refhandbook import cli

    f = tmp_path / "env"
    f.write_text("# c\nRHB_Y=(&(objectClass=posixAccount)(uid={uid}))\nRHB_X='a b'\nRHB_X=later\n")
    monkeypatch.delenv("RHB_X", raising=False)
    cli.load_env_file(str(f))
    import os

    assert os.environ["RHB_Y"] == "(&(objectClass=posixAccount)(uid={uid}))" and os.environ["RHB_X"] == "later"
    monkeypatch.delenv("RHB_Y")


# ── tokens over time ─────────────────────────────────────────────────────


def _async_client(m, peer="127.0.0.1"):
    import httpx2 as httpx

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=m.http_app(), client=(peer, 40000)),
                             base_url=BASE)


async def _new_req(c, cid, challenge):
    r = await c.get("/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "state": "s",
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": BASE + "/mcp"})
    return parse_qs(urlparse(r.headers["location"]).query)["req"][0]


async def _client_id(c):
    r = await c.post("/register", json={"redirect_uris": [CALLBACK], "client_name": "Claude",
                                        "token_endpoint_auth_method": "none"})
    return r.json()["client_id"]


def _signed_in(m):
    import asyncio

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            verifier, ch = pkce()
            r = await c.post("/login", data={"req": await _new_req(c, cid, ch), "action": "allow"},
                             headers=as_user(m.key))
            code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
            t = await c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
                                             "client_id": cid, "code_verifier": verifier})
            return cid, t.json()

    return asyncio.run(run())


def _post(m, path, data):
    import asyncio

    async def run():
        async with _async_client(m) as c:
            return await c.post(path, data=data)

    return asyncio.run(run())


def _refresh(m, cid, rt):
    return _post(m, "/token", {"grant_type": "refresh_token", "refresh_token": rt, "client_id": cid})


def test_refresh_rechecks_the_account(built, accounts):
    m = built
    cid, t = _signed_in(m)
    n = _refresh(m, cid, t["refresh_token"])
    assert n.status_code == 200
    accounts.present.discard("moon")  # account removed, or taken out of the group
    assert _refresh(m, cid, n.json()["refresh_token"]).status_code == 400
    assert m.provider.db.execute("SELECT count(*) FROM tokens WHERE subject='moon'").fetchone()[0] == 0


def test_refresh_replay_revokes_family_and_session_ends(built, cfg):
    m = built
    cid, t = _signed_in(m)
    n = _refresh(m, cid, t["refresh_token"]).json()
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400  # the old one comes back ...
    assert _refresh(m, cid, n["refresh_token"]).status_code == 400  # ... and takes the new one with it

    cid, t = _signed_in(m)
    m.provider.db.execute("UPDATE tokens SET auth_time = auth_time - ?", (cfg.session_ttl + 1,))
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400  # absolute session lifetime


def test_revoking_an_expired_access_token_kills_its_refresh(built):
    m = built
    cid, t = _signed_in(m)
    m.provider.db.execute("UPDATE tokens SET expires = 1 WHERE kind='access'")
    assert _post(m, "/revoke", {"token": t["access_token"], "client_id": cid, "client_secret": ""}).status_code == 200
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400


def test_double_submit_and_resource_and_cleanup(built):
    import asyncio

    m = built

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            _, ch = pkce()
            req = await _new_req(c, cid, ch)
            both = await asyncio.gather(*[c.post("/login", data={"req": req, "action": "allow"},
                                                 headers=as_user(m.key)) for _ in range(2)])
            evil = await c.get("/authorize", params={
                "response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "state": "s",
                "code_challenge": ch, "code_challenge_method": "S256",
                "resource": "http://localhost:8765.evil.example/mcp"})
            return sorted(r.status_code for r in both), evil

    codes, evil = asyncio.run(run())
    assert codes == [303, 400]
    assert "/login" not in evil.headers.get("location", "")
    p = m.provider
    p.db.execute("INSERT INTO clients (client_id, info, created) VALUES ('stale', '{}', ?)", (time.time() - 2 * 86400,))
    p._sweep()
    assert p.db.execute("SELECT count(*) FROM clients WHERE client_id='stale'").fetchone()[0] == 0
    assert p.db.execute("SELECT count(*) FROM clients WHERE signed_in=1").fetchone()[0] == 1  # kept


# ── the approval page (/agents): the user's channel, behind the site sign-in ──


def _csrf(page):
    import re

    return re.search(r"name=csrf value='([0-9a-f]+)'", page).group(1)


def test_the_approval_page_needs_the_site_sign_in_and_an_allowed_account(client):
    c, key = client, client.key
    r = c.get("/approvals", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/auth/login?next=/approvals"
    r = c.get("/approvals", headers={"X-Auth-Token": site_token(key, uid="nobody")}, follow_redirects=False)
    assert r.status_code == 303  # signed in, but not an account of this server
    page = c.get("/approvals", headers={"X-Auth-Token": site_token(key)}).text
    assert "<b>moon</b>" in page and "제안된 규칙 (0)" in page and "default" in page


def test_a_proposal_is_approved_only_by_the_user_on_the_page(client):
    from refhandbook.kernel import proposals, runtime

    c, key = client, client.key
    tok = {"X-Auth-Token": site_token(key)}
    g = runtime.attach(server._user_store("moon")).g
    with g.tx():
        g.define_rule("rv_page", "check", 'rv_page(R) :- rs_row(Self, X, R, "H").', actor="model",
                      applies_to="ledger", message="{R}")
    page = c.get("/approvals", headers=tok).text
    sha = proposals.approval_sha(g, "rv_page")[:12]
    assert "rv_page" in page and f"승인 해시 {sha}" in page
    form = {"rule": "rv_page", "seen": sha, "csrf": _csrf(page)}
    r = c.post("/approvals/approve", data={**form, "csrf": "0" * 64}, headers={**tok, "Origin": BASE}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/approvals/approve", data=form, headers={**tok, "Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/approvals/approve", data=form, headers=tok, follow_redirects=False)  # no Origin: refused
    assert r.status_code == 403
    r = c.post("/approvals/approve", data=form, headers={**tok, "Origin": BASE}, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert g.get_rule("rv_page")["authority"] == "sealed"


def test_a_policy_is_granted_on_the_page(client):
    from refhandbook.agents.workspace import Workspace

    c, key = client, client.key
    tok = {"X-Auth-Token": site_token(key), "Origin": BASE}
    page = c.get("/approvals", headers=tok).text
    r = c.post("/approvals/policy", data={"name": "net", "commands": "sh cat", "network": "on", "timeout": "30",
                                       "csrf": _csrf(page)}, headers=tok, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    w = Workspace(server._user_store("moon"))
    p = w.policy("net")
    assert w.caps.get("policy", "net")["author"] == "user" and p["attrs"]["network"] is True and p["attrs"]["commands"] == ["sh", "cat"]
    assert p["attrs"]["exec_work"] is False and "name=exec_work" in page
    r = c.post("/approvals/policy", data={"name": "net", "commands": "sh cat", "exec_work": "on", "csrf": _csrf(page)},
               headers=tok, follow_redirects=False)
    assert "ok=" in r.headers["location"] and w.policy("net")["attrs"]["exec_work"] is True
    assert "빌드 실행" in c.get("/approvals", headers=tok).text
    # numbers as they are shown (120.0 before) are taken; a refusal keeps what was typed
    r = c.post("/approvals/policy", data={"name": "net", "commands": "sh cat", "timeout": "30.0", "memory_mb": "1,024",
                                          "csrf": _csrf(page)}, headers=tok, follow_redirects=False)
    assert "ok=" in r.headers["location"] and w.policy("net")["attrs"]["timeout"] == 30 \
        and w.policy("net")["attrs"]["memory_mb"] == 1024
    assert "value='30'" in c.get("/approvals", headers=tok).text  # not 30.0
    r = c.post("/approvals/policy", data={"name": "net", "commands": "sh cat my-typed-cmd-xyz", "timeout": "1.5",
                                          "description": "typed by hand", "csrf": _csrf(page)}, headers=tok)
    assert r.status_code == 400 and "정수로 적어 주세요" in r.text
    assert "typed by hand" in r.text and "my-typed-cmd-xyz" in r.text and "<details class='panel' open>" in r.text
    r = c.post("/approvals/policy", data={"name": "bad", "commands": "no-such-tool-xyz", "csrf": _csrf(page)},
               headers=tok, follow_redirects=False)
    assert r.status_code == 400 and "flash error" in r.text  # the page again, saying why


def test_a_grant_the_model_asked_for_is_approved_on_the_page(client):
    from refhandbook.agents.workspace import Workspace

    c, key = client, client.key
    tok = {"X-Auth-Token": site_token(key), "Origin": BASE}
    w = Workspace(server._user_store("moon"))
    w.caps.add("policy", "wider", spec={"network": True, "commands": ["sh", "cat"]}, actor="model")
    page = c.get("/approvals", headers=tok).text
    assert "승인 대기 중인 권한 (1)" in page and "policy wider" in page and "the network" in page
    form = {"kind": "policy", "name": "wider", "version": "1", "csrf": _csrf(page)}
    r = c.post("/approvals/cap/approve", data=form, headers={**tok, "Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/approvals/cap/approve", data=form, headers=tok, follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    assert Workspace(server._user_store("moon")).policy("wider")["attrs"]["network"] is True
    r = c.post("/approvals/cap/approve", data=form, headers=tok, follow_redirects=False)  # nothing waits any more
    assert r.status_code == 400 and "flash error" in r.text  # the page again, saying why


def test_the_approval_page_opens_without_the_default_policy(client):
    """The user may retire the default policy and keep others (here: dev). The new-policy form then
    starts from the default's definition instead of failing."""
    from refhandbook.agents.workspace import DEFAULT_POLICY, Workspace

    c, key = client, client.key
    w = Workspace(server._user_store("moon"))
    w.set_policy("dev", actor="user", commands=["sh", "cat"])
    w.caps.remove("policy", DEFAULT_POLICY, actor="user")
    assert w.policies() == ["dev"]
    page = c.get("/approvals", headers={"X-Auth-Token": site_token(key)})
    assert page.status_code == 200 and "새 정책" in page.text and "<b>dev</b>" in page.text
    assert w.base_policy() == Workspace.default_policy_spec()


def test_a_mount_path_with_spaces_is_quoted_on_the_policy_form(client):
    """A mount line splits as a shell would: a path with spaces is quoted or escaped, and the form writes
    a saved mount back the same way, so saving the form again keeps it."""
    from refhandbook.agents import pages
    from refhandbook.store import HandbookError

    vault = {"source": "/data/me/Obsidian/Research Vault", "target": "/Vault", "rw": True}
    assert pages._mounts('"/data/me/Obsidian/Research Vault" /Vault rw\n\n/data/me/ws /ws') == [
        vault, {"source": "/data/me/ws", "target": "/ws", "rw": False}]
    assert pages._mounts("/data/me/Obsidian/Research\\ Vault /Vault rw") == [vault]
    assert pages._mounts(pages._mount_line(vault)) == [vault]
    assert pages._mount_line({"source": "/data/me/ws", "target": "/ws", "rw": False}) == "/data/me/ws /ws"
    for bad in ('"/data/me/open /Vault', "/data/me/Research Vault /Vault rw", "/a /b ro"):
        with pytest.raises(HandbookError):
            pages._mounts(bad)


def test_a_record_is_renamed_deprecated_removed_restored_and_edited_on_the_page(client):
    from refhandbook.agents.workspace import Workspace

    c, key = client, client.key
    tok = {"X-Auth-Token": site_token(key), "Origin": BASE}
    w = Workspace(server._user_store("moon"))
    w.set_policy("dev", actor="user", commands=["sh", "cat"])
    w.put_script("probe", "cat /etc/hostname", actor="model", policy="dev", description="line one\nline two")
    page = c.get("/approvals", headers=tok).text
    assert "id='rec-script-probe'" in page and "class='rec-desc'" in page and "id='policy-dev'" in page
    assert "action='/approvals/cap/manage'" in page

    def manage(**form):
        return c.post("/approvals/cap/manage", data={"csrf": _csrf(page), **form}, headers=tok, follow_redirects=False)

    # a rename is a copy and a pointer: the old policy points to the new one, its script moves along
    r = manage(kind="policy", name="dev", action="rename", new="work", move="on")
    assert r.status_code == 303 and "ok=" in r.headers["location"] and r.headers["location"].endswith("#records")
    assert "work" in w.policies() and w.caps.get("policy", "work")["author"] == "user"
    old = w.caps.get("policy", "dev")
    assert old["state"] == "deprecated" and old["attrs"]["replaced_by"] == "work"
    probe = w.caps.get("script", "probe")
    assert w.caps.version(probe)["spec"]["policy"] == "work" and probe["author"] == "model"
    assert manage(kind="policy", name="work", action="rename", new="work").status_code == 400  # the same name

    r = manage(kind="script", name="probe", action="deprecate", why="superseded")
    assert "ok=" in r.headers["location"] and w.caps.get("script", "probe")["state"] == "deprecated"
    r = manage(kind="script", name="probe", action="remove")
    assert "ok=" in r.headers["location"] and w.caps.get("script", "probe")["state"] == "retired"
    assert "은퇴한 기록 (" in c.get("/approvals", headers=tok).text
    r = manage(kind="script", name="probe", action="restore")
    assert "ok=" in r.headers["location"] and w.caps.get("script", "probe")["state"] == "active"

    # a new version, as typed in the page (a browser sends a textarea's lines as CRLF)
    spec = json.dumps({"interpreter": "sh", "policy": "work", "description": "by hand"})
    r = manage(kind="script", name="probe", action="edit", spec=spec, body="cat /etc/os-release\r\n", note="typed")
    assert "ok=" in r.headers["location"]
    v = w.caps.version(w.caps.get("script", "probe"))
    assert v["body"] == "cat /etc/os-release\n" and v["author"] == "user" and v["note"] == "typed"
    r = manage(kind="script", name="probe", action="edit", spec="{not json")
    assert r.status_code == 400 and "JSON" in r.text
    assert manage(kind="policy", name="work", action="edit", spec="{}").status_code == 400  # a policy: its form
    assert manage(kind="script", name="probe", action="nonsense").status_code == 400
