"""The portal's JSON API (/account/api/v1): the pages' operations (portal/accounts.py) as JSON, and
the sign-in's /auth/api/v1/me for the pages' frame."""

import re

from fastapi.testclient import TestClient

from .test_app import FakeKerberos, env, login  # noqa: F401 — fixture
from .test_sso import ISS, key, sign_in  # noqa: F401 — fixture

V1 = "/api/v1"


def api(c, s, method, path, json=None, **kw):
    return c.request(method, V1 + path, json=json,
                     headers={"X-Requested-With": "fetch", "Origin": s.public_url, **kw.pop("headers", {})}, **kw)


def test_me_and_my_own_profile_and_password(env):
    s, d, k, ka, app, _ = env
    assert TestClient(app).get(V1 + "/me").json()["error"]["code"] == "unauthorized"
    c, _ = login(app, "alice", "alice-password-1")
    me = api(c, s, "GET", "/me").json()
    assert me["user"]["uid"] == "alice" and me["roles"] == ["user"] and not me["may"]["view_users"]
    assert "dn" not in me["user"] and "principals" not in me["user"] and me["user"]["complete"]
    r = api(c, s, "PATCH", "/me", {"displayName": "앨리스", "mail": "a@example.org", "loginShell": "/bin/bash"})
    assert r.status_code == 200 and r.json()["display_name"] == "앨리스"
    assert api(c, s, "PATCH", "/me", {"displayName": "x", "mail": "nope", "loginShell": "/bin/bash"}).status_code == 400
    r = api(c, s, "POST", "/me/password", {"old": "wrong", "new": "a-new-password-1", "confirm": "a-new-password-1"})
    assert r.status_code == 400 and "맞지 않습니다" in r.json()["error"]["message"]
    r = api(c, s, "POST", "/me/password", {"old": "alice-password-1", "new": "a-new-password-1",
                                           "confirm": "a-new-password-1"})
    assert r.json() == {"changed": True} and k.passwords["alice"] == "a-new-password-1"
    # the pages' own writes only
    r = c.request("PATCH", V1 + "/me", json={"displayName": "x"})
    assert r.status_code == 403
    assert api(c, s, "GET", "/users").status_code == 403  # not helpdesk or admin


def test_the_admins_operations(env):
    s, d, k, ka, app, _ = env
    c, _ = login(app, "moon", "moon-password-1")
    me = api(c, s, "GET", "/me").json()
    assert me["may"]["create_user"] and me["may"]["delete_user"]
    assert [u["uid"] for u in api(c, s, "GET", "/users?q=al").json()] == ["alice"]
    r = api(c, s, "POST", "/users", {"uid": "bob", "name": "Bob", "mail": "", "loginShell": "/bin/bash"})
    assert r.status_code == 201 and r.json()["user"]["uid"] == "bob" and len(r.json()["password"]) >= 12
    assert api(c, s, "POST", "/users", {"uid": "root", "name": "", "mail": "", "loginShell": "/bin/bash"}).status_code == 400
    u = api(c, s, "GET", "/users/alice").json()
    assert u["may"]["delete_user"] and "admin" in u["addable_groups"]
    assert api(c, s, "GET", "/users/moon").json()["may"]["delete_user"] is False  # not oneself
    assert api(c, s, "POST", "/users/alice/reset").json()["password"]
    assert api(c, s, "PATCH", "/users/alice", {"enabled": False}).json()["disabled"] is True
    assert "helpdesk" in api(c, s, "PUT", "/users/alice/groups/helpdesk").json()["groups"]
    assert "helpdesk" not in api(c, s, "DELETE", "/users/alice/groups/helpdesk").json()["groups"]
    assert api(c, s, "DELETE", "/users/alice?confirm=alic").status_code == 400
    assert api(c, s, "DELETE", "/users/alice?confirm=alice").json() == {"deleted": "alice"}
    assert api(c, s, "GET", "/users/alice").status_code == 403  # gone: as not allowed (tells nothing)
    assert {"name": "admin", "gid": 0} in api(c, s, "GET", "/groups").json()


def test_requests_and_invitations(env):
    s, d, k, ka, app, _ = env
    from .test_app import submit_request

    submit_request(app)
    c, _ = login(app, "moon", "moon-password-1")
    reqs = api(c, s, "GET", "/requests").json()
    assert [r["uid"] for r in reqs] == ["dana"] and reqs[0]["name"] == "다나"
    r = api(c, s, "POST", f"/requests/{reqs[0]['id']}/approve", {"loginShell": "/bin/bash"})
    assert r.status_code == 201 and r.json()["user"]["uid"] == "dana"
    assert api(c, s, "GET", "/requests").json() == []
    r = api(c, s, "POST", "/invites", {"note": "새 학생"})
    assert r.status_code == 201 and re.search(r"/join/[\w-]+$", r.json()["link"])
    iid = r.json()["invite"]["id"]
    assert [i["id"] for i in api(c, s, "GET", "/invites").json()] == [iid]
    assert api(c, s, "POST", f"/invites/{iid}/revoke").json() == {"revoked": True}


def test_a_backend_failure_is_a_reference(env):
    s, d, k, ka, app, _ = env
    ka.fail = True
    c, _ = login(app, "moon", "moon-password-1")
    r = api(c, s, "POST", "/users", {"uid": "carol", "name": "", "mail": "", "loginShell": "/bin/bash"})
    assert r.status_code == 502 and "Policy" not in r.text and "reference" in r.json()["error"]["message"]


def test_the_frame_knows_who_and_what_they_may_see(tmp_path, key, monkeypatch):
    from portal import sso as sso_mod
    from portal.config import Settings
    from portal.sso import create_app

    from .conftest import SITE

    monkeypatch.setattr(sso_mod, "nss_groups", lambda uid: {"admin"} if uid == "moon" else set())
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False,
                 audit_log=str(tmp_path / "a.log"), sso_issuer=ISS, site_file=str(SITE))
    app = create_app(s, FakeKerberos(), key)
    anon = TestClient(app).get("/auth/api/v1/me").json()
    assert anon["uid"] is None and anon["title"] == "M00NNY.KR" and anon["cards"]
    c, r = sign_in(app, uid="moon", pw="moon-password-1")
    assert r.headers["location"] == "/?start"  # to the main page, which opens their start page if they chose one
    assert sign_in(app, uid="moon", pw="moon-password-1", nxt="/agents/")[1].headers["location"] == "/agents/"
    me = c.get("/auth/api/v1/me").json()
    account = next(x for x in me["cards"] if x["id"] == "account")
    assert account["icon"] and account["href"] == "/account/"  # where it opens, for the app list
    assert me["uid"] == "moon" and "사용자 관리" in [ln["label"] for ln in account["links"]]
    c, _ = sign_in(app)
    account = next(x for x in c.get("/auth/api/v1/me").json()["cards"] if x["id"] == "account")
    assert "사용자 관리" not in [ln["label"] for ln in account["links"]]
