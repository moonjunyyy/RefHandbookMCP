"""Remote mode: OAuth sign-in against LDAP, per-user stores, the MCP endpoint over HTTP."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from refhandbook import remote, research_api, server

BASE = "http://localhost:8765"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class FakeDirectory:
    """uid → password; the LDAP class is tested separately against ldap3's mock server."""

    def __init__(self, users: dict[str, str]):
        self.users = users

    def authenticate(self, username: str, password: str) -> str | None:
        u = username.strip().lower()
        return u if password and self.users.get(u) == password else None


@pytest.fixture
def cfg(tmp_path):
    return remote.Config(public_url=BASE, data_dir=tmp_path / "data")


@pytest.fixture
def client(cfg):
    m = remote.build(cfg, FakeDirectory({"moon": "pw-moon", "kim": "pw-kim"}))
    try:
        with TestClient(m.http_app(), base_url=BASE) as c:
            c.provider = m.provider  # type: ignore[attr-defined]
            yield c
    finally:  # later tests use the local (stdio) binding
        server._user_store = None
        research_api.use_resolver(None)


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


def sign_in(c, user="moon", password=None):
    """Full flow; returns (token response, client_id)."""
    cid = register(c).json()["client_id"]
    verifier, challenge = pkce()
    req = start(c, cid, challenge)
    r = c.post("/login", data={"req": req, "username": user, "password": password or f"pw-{user}", "action": "allow"},
               follow_redirects=False)
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


def test_registration_refuses_foreign_redirects(client):
    assert register(client, "https://evil.example/cb").status_code == 400
    assert register(client, "http://localhost:53682/callback").status_code == 201  # Claude Code's loopback


# ── sign-in ──────────────────────────────────────────────────────────────


def test_full_flow_and_per_user_isolation(client, cfg):
    t_moon, _ = sign_in(client, "moon")
    t_kim, _ = sign_in(client, "kim")
    s1 = mcp_session(client, t_moon["access_token"])
    tools = rpc(client, t_moon["access_token"], "tools/list", session=s1, rid=9)[1]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"lookup", "open_entry", "research_begin", "research_end", "research_doc"} <= names

    refused = call(client, t_moon["access_token"], s1, "research_end", {"ledger": "none", "turn": 1, "token": "x"}, rid=7)
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
    assert "Turn loop" in card["content"][0]["text"]
    assert (cfg.data_dir / "users" / "moon.db").exists() and (cfg.data_dir / "users" / "kim.db").exists()


def test_wrong_password_lockout_and_deny(client):
    cid = register(client).json()["client_id"]
    _, challenge = pkce()
    req = start(client, cid, challenge)
    page = client.get("/login", params={"req": req})
    assert page.status_code == 200 and "Claude" in page.text
    assert "form-action 'self' https://claude.ai" in page.headers["content-security-policy"]
    bad = client.post("/login", data={"req": req, "username": "moon", "password": "nope", "action": "allow"})
    assert bad.status_code == 401 and "맞지 않습니다" in bad.text
    empty = client.post("/login", data={"req": req, "username": "moon", "password": "", "action": "allow"})
    assert empty.status_code == 401
    # deny sends the browser back with access_denied
    d = client.post("/login", data={"req": req, "action": "deny"}, follow_redirects=False)
    assert d.status_code == 303 and "error=access_denied" in d.headers["location"]
    assert client.get("/login", params={"req": req}).status_code == 400  # request consumed

    # five failures lock the user, even with a fresh request and the right password
    for _ in range(5):
        req = start(client, cid, challenge)
        client.post("/login", data={"req": req, "username": "kim", "password": "x", "action": "allow"})
    req = start(client, cid, challenge)
    locked = client.post("/login", data={"req": req, "username": "kim", "password": "pw-kim", "action": "allow"})
    assert locked.status_code == 429


def test_code_single_use_refresh_rotation_revoke(client):
    cid = register(client).json()["client_id"]
    verifier, challenge = pkce()
    req = start(client, cid, challenge)
    r = client.post("/login", data={"req": req, "username": "moon", "password": "pw-moon", "action": "allow"},
                    follow_redirects=False)
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


# ── LDAP ─────────────────────────────────────────────────────────────────


@pytest.fixture
def ldap_server():
    from ldap3 import MOCK_SYNC, OFFLINE_SLAPD_2_4, Connection, Server

    s = Server("mock", get_info=OFFLINE_SLAPD_2_4)
    c = Connection(s, client_strategy=MOCK_SYNC)
    add = c.strategy.add_entry
    add("cn=svc,dc=ex,dc=org", {"objectClass": ["person"], "sn": "svc", "userPassword": "svcpw"})
    for uid, pw, n in (("moon", "pw1", 1000), ("kim", "pw2", 1001)):
        add(f"uid={uid},ou=people,dc=ex,dc=org", {
            "objectClass": ["posixAccount", "inetOrgPerson"], "uid": uid, "cn": uid, "sn": uid,
            "userPassword": pw, "uidNumber": n, "gidNumber": n, "homeDirectory": f"/home/{uid}"})
    add("cn=research,ou=groups,dc=ex,dc=org", {"objectClass": ["posixGroup"], "cn": "research",
                                                "gidNumber": 2000, "memberUid": ["moon"]})
    return s


def ldap_cfg(tmp_path, **kw):
    return remote.Config(public_url=BASE, data_dir=tmp_path, ldap_user_base="ou=people,dc=ex,dc=org", **kw)


def test_ldap_search_then_bind(tmp_path, ldap_server):
    from ldap3 import MOCK_SYNC

    a = remote.LdapAuthenticator(ldap_cfg(tmp_path, ldap_bind_dn="cn=svc,dc=ex,dc=org", ldap_bind_password="svcpw"),
                                 ldap_server, client_strategy=MOCK_SYNC)
    assert a.authenticate("Moon", "pw1") == "moon"
    assert a.authenticate("moon", "wrong") is None
    assert a.authenticate("moon", "") is None  # never an anonymous bind
    assert a.authenticate("nobody", "pw1") is None
    assert a.authenticate("moon)(uid=*", "pw1") is None  # not a POSIX name: refused before the filter


def test_ldap_anonymous_search_template_and_group(tmp_path, ldap_server):
    from ldap3 import MOCK_SYNC

    anon = remote.LdapAuthenticator(ldap_cfg(tmp_path), ldap_server, client_strategy=MOCK_SYNC)
    assert anon.authenticate("kim", "pw2") == "kim"
    tmpl = remote.LdapAuthenticator(ldap_cfg(tmp_path, ldap_user_dn="uid={uid},ou=people,dc=ex,dc=org"),
                                    ldap_server, client_strategy=MOCK_SYNC)
    assert tmpl.authenticate("kim", "pw2") == "kim"
    group = remote.LdapAuthenticator(
        ldap_cfg(tmp_path, ldap_group_base="ou=groups,dc=ex,dc=org",
                 ldap_group_filter="(&(objectClass=posixGroup)(cn=research)(memberUid={uid}))"),
        ldap_server, client_strategy=MOCK_SYNC)
    assert group.authenticate("moon", "pw1") == "moon"
    assert group.authenticate("kim", "pw2") is None  # right password, not in the group


# ── configuration and packaging ──────────────────────────────────────────


def test_config_and_redirects(monkeypatch, tmp_path):
    monkeypatch.setenv("RHB_PUBLIC_URL", "http://hb.example.org")
    with pytest.raises(SystemExit):
        remote.Config.from_env()
    monkeypatch.setenv("RHB_PUBLIC_URL", "https://hb.example.org/sub")
    with pytest.raises(SystemExit):
        remote.Config.from_env()
    pw = tmp_path / "pw"
    pw.write_text("s3cret\n")
    monkeypatch.setenv("RHB_PUBLIC_URL", "https://hb.example.org/")
    monkeypatch.setenv("RHB_LDAP_BIND_PASSWORD_FILE", str(pw))
    c = remote.Config.from_env()
    assert c.public_url == "https://hb.example.org" and c.resource_url == "https://hb.example.org/mcp"
    assert c.ldap_bind_password == "s3cret"
    allow = remote.DEFAULT_REDIRECTS
    assert remote.redirect_allowed("http://localhost:4312/callback", allow)
    assert remote.redirect_allowed(CALLBACK, allow)
    assert not remote.redirect_allowed("https://claude.ai.evil.example/api/mcp/auth_callback", allow)
    assert not remote.redirect_allowed("http://localhost.evil.example:80/cb", allow)


def test_plugin_json_cli(tmp_path, capsys):
    from refhandbook import cli

    out = tmp_path / "plugin.json"
    assert cli.main(["plugin-json", "https://hb.example.org/mcp", "--write", str(out)]) == 0
    pj = json.loads(out.read_text())
    assert pj["mcpServers"] == {"refhandbook": {"type": "http", "url": "https://hb.example.org/mcp"}}
    assert "command" not in json.dumps(pj)


def test_nslcd_translation():
    conf = """# /etc/nslcd.conf
uid nslcd
gid nslcd
uri ldap://ldap.ex.org ldap://ldap2.ex.org
base dc=ex,dc=org
base passwd ou=people,dc=ex,dc=org
base group ou=groups,dc=ex,dc=org
binddn cn=nslcd,dc=ex,dc=org
bindpw hunter2
ssl start_tls
tls_reqcert demand
tls_cacertfile /etc/ssl/certs/ldap-ca.pem
"""
    from refhandbook.nslcd import env_from_nslcd

    lines, notes = env_from_nslcd(conf)
    env = dict(line.split("=", 1) for line in lines)
    assert env["RHB_LDAP_URI"] == "ldap://ldap.ex.org"
    assert env["RHB_LDAP_STARTTLS"] == "1"
    assert env["RHB_LDAP_USER_BASE"] == "ou=people,dc=ex,dc=org"
    assert env["RHB_LDAP_GROUP_BASE"] == "ou=groups,dc=ex,dc=org"
    assert env["RHB_LDAP_USER_FILTER"] == "(&(objectClass=posixAccount)(uid={uid}))"
    assert env["RHB_LDAP_CA_FILE"] == "/etc/ssl/certs/ldap-ca.pem"
    assert "hunter2" not in "\n".join(lines + notes)
    anon, n2 = env_from_nslcd("uri ldapi:///\nbase dc=ex,dc=org\n")
    assert "RHB_LDAP_BIND_DN" not in "\n".join(anon) and any("anonymously" in n for n in n2)


def test_env_file(tmp_path, monkeypatch):
    from refhandbook import cli

    f = tmp_path / "env"
    f.write_text("# c\nRHB_LDAP_USER_FILTER=(&(objectClass=posixAccount)(uid={uid}))\nRHB_X='a b'\nRHB_X=later\n")
    monkeypatch.delenv("RHB_X", raising=False)
    cli.load_env_file(str(f))
    import os

    assert os.environ["RHB_LDAP_USER_FILTER"] == "(&(objectClass=posixAccount)(uid={uid}))"
    assert os.environ["RHB_X"] == "later"


# ── review regressions ───────────────────────────────────────────────────


class SlowDirectory(FakeDirectory):
    """Counts password checks; each takes a while, so concurrent posts overlap."""

    def __init__(self, users, delay=0.2):
        super().__init__(users)
        self.calls = 0
        self.delay = delay
        self.present = set(users)
        self.down = False

    def authenticate(self, username, password):
        import time

        self.calls += 1
        time.sleep(self.delay)
        return super().authenticate(username, password)

    def exists(self, uid):
        if self.down:
            raise remote.DirectoryUnavailable("down")
        return uid in self.present


@pytest.fixture
def slow(cfg):
    d = SlowDirectory({"moon": "pw-moon", "kim": "pw-kim"})
    m = remote.build(cfg, d)
    try:
        yield m, d
    finally:
        server._user_store = None
        research_api.use_resolver(None)


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


def test_concurrent_posts_cannot_bypass_lockout(slow):
    import asyncio

    m, d = slow

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            _, ch = pkce()
            one = await _new_req(c, cid, ch)
            burst = [c.post("/login", data={"req": one, "username": "moon", "password": f"guess{i}", "action": "allow"})
                     for i in range(40)]
            await asyncio.gather(*burst)
            per_request = d.calls
            reqs = [await _new_req(c, cid, ch) for _ in range(40)]
            d.calls = 0
            await asyncio.gather(*[c.post("/login", data={"req": r, "username": "kim", "password": f"g{i}",
                                                          "action": "allow"}) for i, r in enumerate(reqs)])
            return per_request, d.calls

    per_request, across = asyncio.run(run())
    assert per_request <= 5, per_request  # one sign-in request: at most five checks
    assert across <= 5, across  # many requests, one (uid, address): at most five checks


def test_lockout_is_per_address_and_ignores_junk_names(slow):
    import asyncio

    m, d = slow
    d.delay = 0

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            verifier, ch = pkce()
            for i in range(5):
                await c.post("/login", data={"req": await _new_req(c, cid, ch), "username": "kim", "password": "x",
                                             "action": "allow"}, headers={"X-Forwarded-For": "203.0.113.9"})
            locked = await c.post("/login", data={"req": await _new_req(c, cid, ch), "username": "kim",
                                                  "password": "pw-kim", "action": "allow"},
                                  headers={"X-Forwarded-For": "203.0.113.9"})
            other = await c.post("/login", data={"req": await _new_req(c, cid, ch), "username": "kim",
                                                 "password": "pw-kim", "action": "allow"},
                                 headers={"X-Forwarded-For": "198.51.100.7"})
            await c.post("/login", data={"req": await _new_req(c, cid, ch), "username": "x" * 500_000,
                                         "password": "p", "action": "allow"})
            return locked.status_code, other.status_code

    locked, other = asyncio.run(run())
    assert locked == 429 and other == 303
    assert all(len(k[0]) <= 64 for k in m.provider.failures)  # junk names are never keys


def _signed_in(m):
    import asyncio

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            verifier, ch = pkce()
            r = await c.post("/login", data={"req": await _new_req(c, cid, ch), "username": "moon",
                                             "password": "pw-moon", "action": "allow"})
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


def test_refresh_rechecks_the_directory(slow):
    m, d = slow
    d.delay = 0
    cid, t = _signed_in(m)
    d.down = True
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400  # cannot confirm: refused, not waved through
    d.down = False
    n = _refresh(m, cid, t["refresh_token"])
    assert n.status_code == 200
    d.present.discard("moon")  # account removed, or taken out of the group
    assert _refresh(m, cid, n.json()["refresh_token"]).status_code == 400
    assert m.provider.db.execute("SELECT count(*) FROM tokens WHERE subject='moon'").fetchone()[0] == 0


def test_refresh_replay_revokes_family_and_session_ends(slow, cfg):
    m, d = slow
    d.delay = 0
    cid, t = _signed_in(m)
    n = _refresh(m, cid, t["refresh_token"]).json()
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400  # the old one comes back ...
    assert _refresh(m, cid, n["refresh_token"]).status_code == 400  # ... and takes the new one with it

    cid, t = _signed_in(m)
    m.provider.db.execute("UPDATE tokens SET auth_time = auth_time - ?", (cfg.session_ttl + 1,))
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400  # absolute session lifetime


def test_revoking_an_expired_access_token_kills_its_refresh(slow):
    m, d = slow
    d.delay = 0
    cid, t = _signed_in(m)
    m.provider.db.execute("UPDATE tokens SET expires = 1 WHERE kind='access'")
    assert _post(m, "/revoke", {"token": t["access_token"], "client_id": cid, "client_secret": ""}).status_code == 200
    assert _refresh(m, cid, t["refresh_token"]).status_code == 400


def test_double_submit_and_resource_and_cleanup(slow):
    import asyncio
    import time

    m, d = slow
    d.delay = 0.1

    async def run():
        async with _async_client(m) as c:
            cid = await _client_id(c)
            _, ch = pkce()
            req = await _new_req(c, cid, ch)
            both = await asyncio.gather(*[c.post("/login", data={"req": req, "username": "moon", "password": "pw-moon",
                                                                 "action": "allow"}) for _ in range(2)])
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


def test_redirect_and_unicode_hardening(tmp_path, ldap_server, monkeypatch):
    from ldap3 import MOCK_SYNC

    allow = remote.DEFAULT_REDIRECTS
    assert not remote.redirect_allowed("http://evil.example\\@localhost/", allow)
    assert not remote.redirect_allowed("http://user@localhost:5000/cb", allow)
    assert not remote.redirect_allowed("http://localhost:5000/cb#frag", allow)
    assert not remote.redirect_allowed("javascript://localhost:5000/", allow)
    a = remote.LdapAuthenticator(ldap_cfg(tmp_path), ldap_server, client_strategy=MOCK_SYNC)
    assert a.authenticate("Kim", "pw2") is None  # Kelvin sign lowers to 'k'
    monkeypatch.setenv("RHB_PUBLIC_URL", "https://hb.example.org")
    monkeypatch.setenv("RHB_LDAP_URI", "ldap://ldap.example.org")
    assert remote.Config.from_env().auth == "pam"  # the default does not use LDAP for passwords
    monkeypatch.setenv("RHB_AUTH", "ldap")
    with pytest.raises(SystemExit):
        remote.Config.from_env()  # passwords would cross the network in clear
    monkeypatch.setenv("RHB_LDAP_STARTTLS", "1")
    assert remote.Config.from_env().ldap_starttls


def test_ldap_exists(tmp_path, ldap_server):
    from ldap3 import MOCK_SYNC

    g = remote.LdapAuthenticator(
        ldap_cfg(tmp_path, ldap_group_base="ou=groups,dc=ex,dc=org",
                 ldap_group_filter="(&(objectClass=posixGroup)(cn=research)(memberUid={uid}))"),
        ldap_server, client_strategy=MOCK_SYNC)
    assert g.exists("moon") is True
    assert g.exists("kim") is False  # present, not in the group
    assert g.exists("nobody") is False


def test_client_address_through_proxies(monkeypatch):
    lan = ("127.0.0.1", "::1", "192.168.0.1")
    # router (192.168.0.1) terminates TLS and forwards straight to the app
    assert remote.client_address("192.168.0.1", "203.0.113.5", lan) == "203.0.113.5"
    # router -> nginx on the server -> app: nginx appends the router's address
    assert remote.client_address("127.0.0.1", "203.0.113.5, 192.168.0.1", lan) == "203.0.113.5"
    # a client cannot pick its own address by sending X-Forwarded-For
    assert remote.client_address("192.168.0.1", "1.2.3.4, 203.0.113.5", lan) == "203.0.113.5"
    # an untrusted peer's header is ignored
    assert remote.client_address("198.51.100.9", "1.2.3.4", lan) == "198.51.100.9"
    # the router sends no header: every sign-in looks like the router
    assert remote.client_address("192.168.0.1", "", lan) == "192.168.0.1"
    monkeypatch.setenv("RHB_PUBLIC_URL", "https://hb.example.org")
    monkeypatch.setenv("RHB_TRUSTED_PROXIES", "127.0.0.1, 192.168.0.0/24")
    monkeypatch.setenv("RHB_ALLOWED_HOSTS", "hb.example.org:443")
    c = remote.Config.from_env()
    assert c.trusted_proxies == ("127.0.0.1", "192.168.0.0/24") and c.extra_hosts == ("hb.example.org:443",)
    monkeypatch.setenv("RHB_TRUSTED_PROXIES", "192.168.0.300")
    with pytest.raises(ValueError):
        remote.Config.from_env()


# ── PAM (real libpam, pam_unix, a throwaway account; root only) ─────────


@pytest.fixture
def pam_account(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    if os.geteuid() != 0 or not Path("/etc/pam.d").is_dir() or not shutil.which("useradd"):
        pytest.skip("needs root, PAM and useradd")
    user, group, service = "rhbpamtest", "rhbpamgrp", "refhandbook-test"
    subprocess.run(["userdel", user], capture_output=True)
    subprocess.run(["groupdel", group], capture_output=True)
    subprocess.run(["groupadd", group], check=True)
    subprocess.run(["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", user], check=True)
    subprocess.run(["chpasswd"], input=f"{user}:s3cret-Pw\n", text=True, check=True)
    svc = Path("/etc/pam.d") / service
    svc.write_text("auth required pam_unix.so\naccount required pam_unix.so\n")
    try:
        yield user, group, service
    finally:
        svc.unlink(missing_ok=True)
        subprocess.run(["userdel", user], capture_output=True)
        subprocess.run(["groupdel", group], capture_output=True)


def test_pam_authenticator(pam_account, tmp_path):
    import subprocess

    user, group, service = pam_account
    a = remote.PamAuthenticator(remote.Config(public_url=BASE, data_dir=tmp_path, pam_service=service))
    assert a.authenticate(user, "s3cret-Pw") == user
    assert a.authenticate(user.upper(), "s3cret-Pw") == user  # canonical name from NSS
    assert a.authenticate(user, "wrong") is None
    assert a.authenticate(user, "") is None
    assert a.authenticate("nosuchuser", "s3cret-Pw") is None
    assert a.exists(user) and not a.exists("nosuchuser")

    g = remote.PamAuthenticator(remote.Config(public_url=BASE, data_dir=tmp_path, pam_service=service,
                                              require_group=group))
    assert g.authenticate(user, "s3cret-Pw") is None and not g.exists(user)  # right password, not in the group
    subprocess.run(["usermod", "-aG", group, user], check=True)
    assert g.authenticate(user, "s3cret-Pw") == user and g.exists(user)


def test_enter_submits_login_not_cancel(client):
    """Pressing Enter submits with the form's first submit button (HTML implicit submission):
    it must be the login button, or every Enter sends access_denied back to the client."""
    import re as _re

    cid = register(client).json()["client_id"]
    _, challenge = pkce()
    page = client.get("/login", params={"req": start(client, cid, challenge)}).text
    first = _re.search(r'<button[^>]*name="action"[^>]*value="(\w+)"', page)
    assert first and first.group(1) == "allow"
    # a submit without an action value (some clients) is not taken as a cancel
    req = start(client, cid, challenge)
    r = client.post("/login", data={"req": req, "username": "moon", "password": "pw-moon"}, follow_redirects=False)
    assert r.status_code == 400 and "access_denied" not in r.headers.get("location", "")
