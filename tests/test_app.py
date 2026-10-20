"""End-to-end tests of routes, permissions and CSRF against in-memory fakes of LDAP and Kerberos."""
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from portal.config import Settings
from portal.directory import DirectoryError, User
from portal.kerberos import KerberosError, LoginResult
from portal.invites import InviteStore
from portal.main import create_app
from portal.requests import RequestStore


class FakeDirectory:
    def __init__(self, s):
        self.s = s
        self.users = {}
        self.groups = {"user": {"moon", "alice", "helen"}, "admin": {"moon"}, "helpdesk": {"helen"}}
        for i, uid in enumerate(["moon", "alice", "helen"]):
            self.users[uid] = User(uid=uid, dn=s.user_dn(uid), display_name=uid.title(), uid_number=10001 + i,
                                   gid_number=10001 + i, login_shell="/bin/bash", principals=[s.principal(uid)])

    def get_user(self, uid):
        u = self.users.get(uid)
        if u:
            u = replace(u, groups=sorted(g for g, m in self.groups.items() if uid in m))
        return u

    def search_users(self, q):
        return [self.get_user(u) for u in sorted(self.users) if q in u]

    def list_groups(self):
        return sorted((g, 0) for g in self.groups)

    def update_self(self, uid, changes):
        u = self.users[uid]
        u.display_name, u.mail, u.login_shell = changes["displayName"], changes["mail"], changes["loginShell"]

    def create_user(self, uid, name, mail, shell):
        if uid in self.users:
            raise DirectoryError("exists")
        self.users[uid] = User(uid=uid, dn=self.s.user_dn(uid), display_name=name, mail=mail,
                               login_shell=shell, uid_number=20000)
        self.groups["user"].add(uid)
        return self.get_user(uid)

    def rollback_user(self, uid):
        self.users.pop(uid, None)
        self.groups["user"].discard(uid)

    def set_membership(self, group, uid, member):
        (self.groups[group].add if member else self.groups[group].discard)(uid)


class FakeKerberos:
    def __init__(self):
        self.passwords = {"moon": "moon-password-1", "alice": "alice-password-1", "helen": "helen-password-1"}
        self.expired = set()

    def verify_password(self, principal, password):
        uid = principal.split("/")[0]
        if self.passwords.get(uid) != password:
            return LoginResult.BAD
        return LoginResult.EXPIRED if uid in self.expired else LoginResult.OK

    def change_own_password(self, principal, old, new):
        uid = principal.split("/")[0]
        if self.passwords.get(uid) != old:
            raise KerberosError("Current password is incorrect.")
        self.passwords[uid] = new
        self.expired.discard(uid)


class FakeKAdmin:
    def __init__(self, krb, directory):
        self.krb, self.dir, self.calls, self.fail = krb, directory, [], False

    def create_principal(self, principal, dn, password, alias, needchange=True):
        self.calls.append(("create", principal, alias))
        if self.fail:
            raise KerberosError("add_principal: Policy does not exist while creating x.")
        uid = principal.split("/")[0]
        self.krb.passwords[uid] = password
        if needchange:
            self.krb.expired.add(uid)

    def reset_password(self, principal, password):
        uid = principal.split("/")[0]
        self.calls.append(("reset", principal))
        self.krb.passwords[uid] = password
        self.krb.expired.add(uid)

    def unlock(self, principal):
        self.calls.append(("unlock", principal))

    def set_enabled(self, principal, enabled):
        self.calls.append(("enabled", principal, enabled))
        self.dir.users[principal.split("/")[0]].disabled = not enabled


@pytest.fixture
def env(tmp_path):
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="")
    d, k = FakeDirectory(s), FakeKerberos()
    ka = FakeKAdmin(k, d)
    app = create_app(s, d, k, ka, RequestStore(str(tmp_path / "requests.db")),
                     invites=InviteStore(str(tmp_path / "invites.db")))
    return s, d, k, ka, app, tmp_path


def csrf(client, path="/login"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def login(app, uid, pw):
    c = TestClient(app)
    r = c.post("/login", data={"uid": uid, "password": pw, "csrf": csrf(c)}, follow_redirects=False)
    assert r.status_code == 303
    return c, r


def test_login_and_self_service(env):
    s, d, k, ka, app, tmp = env
    c, r = login(app, "alice", "alice-password-1")
    assert r.headers["location"] == "/"
    home = c.get("/")
    assert "Alice" in home.text and "Users</a>" not in home.text
    assert home.headers["x-frame-options"] == "DENY" and home.headers["cache-control"] == "no-store"
    t = csrf(c, "/")
    c.post("/profile", data={"displayName": "Alice Kim", "mail": "a@m00nny.kr", "loginShell": "/bin/zsh", "csrf": t})
    assert d.users["alice"].login_shell == "/bin/zsh"
    # shell outside the allowlist is rejected
    c.post("/profile", data={"displayName": "A", "mail": "", "loginShell": "/tmp/evil", "csrf": t})
    assert d.users["alice"].login_shell == "/bin/zsh"
    c.post("/password", data={"old": "alice-password-1", "new": "brand-new-pass-2", "confirm": "brand-new-pass-2", "csrf": t})
    assert k.passwords["alice"] == "brand-new-pass-2"
    assert '"action": "change_password"' in (tmp / "audit.log").read_text()


def test_bad_password_and_throttle(env):
    *_, app, _ = env
    c = TestClient(app)
    for _ in range(5):
        c.post("/login", data={"uid": "alice", "password": "wrong", "csrf": csrf(c)})
    r = c.post("/login", data={"uid": "alice", "password": "alice-password-1", "csrf": csrf(c)}, follow_redirects=False)
    assert r.headers["location"] == "/login"  # blocked even with the right password
    assert "Too many failed attempts" in c.get("/login").text


def test_csrf_required(env):
    *_, app, _ = env
    c, _ = login(app, "alice", "alice-password-1")
    r = c.post("/password", data={"old": "alice-password-1", "new": "x" * 12, "confirm": "x" * 12, "csrf": "nope"})
    assert r.status_code == 403


def test_user_cannot_reach_admin(env):
    *_, app, _ = env
    c, _ = login(app, "alice", "alice-password-1")
    assert c.get("/admin/users").status_code == 403
    assert c.get("/admin/users/new").status_code == 403
    assert c.post("/admin/users/moon/reset", data={"csrf": csrf(c, "/")}).status_code == 403


def test_helpdesk_limits(env):
    s, d, k, ka, app, _ = env
    c, _ = login(app, "helen", "helen-password-1")
    assert c.get("/admin/users").status_code == 200
    page = c.get("/admin/users/alice").text
    assert "Reset password" in page and "Disable account" not in page and "Add to group" not in page
    assert "Reset password</button>" not in c.get("/admin/users/moon").text
    t = csrf(c, "/")
    r = c.post("/admin/users/alice/reset", data={"csrf": t})
    assert r.status_code == 200 and "One-time password" in r.text
    assert k.passwords["alice"] != "alice-password-1" and "alice" in k.expired
    # helpdesk cannot touch an admin, cannot create, disable or change groups
    assert c.post("/admin/users/moon/reset", data={"csrf": t}).status_code == 403
    assert c.post("/admin/users/alice/enabled", data={"csrf": t, "enabled": "0"}).status_code == 403
    assert c.post("/admin/users/alice/groups", data={"csrf": t, "group": "admin", "op": "add"}).status_code == 403
    assert c.get("/admin/users/new").status_code == 403


def test_admin_create_user_then_first_login(env):
    s, d, k, ka, app, _ = env
    c, _ = login(app, "moon", "moon-password-1")
    page = c.get("/admin/users/alice").text
    assert "Disable account" in page and "Add to group" in page
    t = csrf(c, "/")
    r = c.post("/admin/users/new", data={"uid": "bob", "name": "Bob Lee", "mail": "",
                                          "loginShell": "/bin/bash", "csrf": t})
    assert r.status_code == 200
    temp = re.search(r'class="secret"><code>([^<]+)</code>', r.text).group(1)
    assert ka.calls[-1] == ("create", "bob/user@M00NNY.KR", "bob@M00NNY.KR")
    # first login with the temporary password forces a change
    b = TestClient(app)
    r = b.post("/login", data={"uid": "bob", "password": temp, "csrf": csrf(b)}, follow_redirects=False)
    assert r.headers["location"] == "/expired"
    b.post("/expired", data={"uid": "bob", "old": temp, "new": "bobs-own-pass-1", "confirm": "bobs-own-pass-1",
                             "csrf": csrf(b, "/expired")})
    login(app, "bob", "bobs-own-pass-1")


def test_create_rolls_back_ldap_when_kerberos_fails(env):
    s, d, k, ka, app, _ = env
    ka.fail = True
    c, _ = login(app, "moon", "moon-password-1")
    r = c.post("/admin/users/new", data={"uid": "carol", "name": "", "mail": "",
                                          "loginShell": "/bin/bash", "csrf": csrf(c, "/")})
    assert r.status_code == 502 and "carol" not in d.users


def test_admin_cannot_lock_self_out_and_reserved_names(env):
    s, d, k, ka, app, _ = env
    c, _ = login(app, "moon", "moon-password-1")
    t = csrf(c, "/")
    assert c.post("/admin/users/moon/enabled", data={"csrf": t, "enabled": "0"}).status_code == 403
    assert c.post("/admin/users/moon/groups", data={"csrf": t, "group": "admin", "op": "remove"}).status_code == 403
    r = c.post("/admin/users/new", data={"uid": "root", "name": "R", "mail": "",
                                          "loginShell": "/bin/bash", "csrf": t})
    assert "reserved" in r.text and "root" not in d.users
    r = c.post("/admin/users/new", data={"uid": "x,ou=Admins", "name": "R", "mail": "",
                                          "loginShell": "/bin/bash", "csrf": t})
    assert "Username:" in r.text


def test_disabled_user_session_is_dropped(env):
    s, d, k, ka, app, _ = env
    c, _ = login(app, "alice", "alice-password-1")
    m, _ = login(app, "moon", "moon-password-1")
    m.post("/admin/users/alice/enabled", data={"csrf": csrf(m, "/"), "enabled": "0"})
    assert c.get("/", follow_redirects=False).headers["location"] == "/login"


REQUEST = {"uid": "dana", "name": "다나", "mail": "dana@example.org", "purpose": "연구실 신규 인원", "consent": "1"}


def submit_request(app, **over):
    c = TestClient(app)
    return c.post("/request", data={**REQUEST, **over, "csrf": csrf(c, "/request")})


def test_request_needs_consent_and_purpose(env):
    *_, app, tmp = env
    assert "동의해야" in submit_request(app, consent="").text
    assert "사용 목적" in submit_request(app, purpose=" ").text
    assert RequestStore(str(tmp / "requests.db")).list() == []


def test_request_then_admin_approves(env):
    s, d, k, ka, app, tmp = env
    r = submit_request(app)
    assert r.status_code == 200 and "접수" in r.text
    # a taken name gets the same answer and stores nothing (no username enumeration)
    taken = submit_request(app, uid="alice")
    assert "접수" in taken.text
    c, _ = login(app, "moon", "moon-password-1")
    page = c.get("/admin/requests").text
    assert "dana@example.org" in page and "연구실 신규 인원" in page
    rid = re.search(r'/admin/requests/([^/]+)/approve', page).group(1)
    r = c.post(f"/admin/requests/{rid}/approve", data={"csrf": csrf(c, "/"), "loginShell": "/bin/zsh"})
    assert r.status_code == 200 and "One-time password" in r.text
    assert d.users["dana"].mail == "dana@example.org" and d.users["dana"].login_shell == "/bin/zsh"
    assert ka.calls[-1] == ("create", "dana/user@M00NNY.KR", "dana@M00NNY.KR")
    assert "dana" not in [x.uid for x in RequestStore(str(tmp / "requests.db")).list()]
    # approving the same request twice does nothing
    assert c.post(f"/admin/requests/{rid}/approve", data={"csrf": csrf(c, "/"), "loginShell": "/bin/zsh"}).status_code == 403


def test_request_reject_and_permissions(env):
    s, d, k, ka, app, tmp = env
    submit_request(app)
    h, _ = login(app, "helen", "helen-password-1")  # helpdesk cannot review requests
    assert h.get("/admin/requests").status_code == 403
    c, _ = login(app, "moon", "moon-password-1")
    rid = re.search(r'/admin/requests/([^/]+)/reject', c.get("/admin/requests").text).group(1)
    c.post(f"/admin/requests/{rid}/reject", data={"csrf": csrf(c, "/")})
    assert RequestStore(str(tmp / "requests.db")).list() == [] and "dana" not in d.users
    assert '"action": "reject_request"' in (tmp / "audit.log").read_text()


def test_request_throttle(env):
    *_, app, _ = env
    c = TestClient(app)
    for i in range(5):
        c.post("/request", data={**REQUEST, "uid": f"user{i}", "csrf": csrf(c, "/request")})
    r = c.post("/request", data={**REQUEST, "uid": "late", "csrf": csrf(c, "/request")})
    assert "너무 많습니다" in r.text


def test_root_path(tmp_path):
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="", root_path="/account")
    d, k = FakeDirectory(s), FakeKerberos()
    app = create_app(s, d, k, FakeKAdmin(k, d), RequestStore(str(tmp_path / "requests.db")),
                     invites=InviteStore(":memory:"))
    c = TestClient(app)
    page = c.get("/account/login").text
    assert 'href="/account/static/style.css"' in page and 'action="/account/login"' in page
    assert 'href="/account/request"' in page
    assert c.get("/account/static/style.css").status_code == 200
    t = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = c.post("/account/login", data={"uid": "alice", "password": "alice-password-1", "csrf": t}, follow_redirects=False)
    assert r.headers["location"] == "/account/"
    assert "path=/account;" in r.headers["set-cookie"].lower()
    assert "Alice" in c.get("/account/").text
    # nginx may also strip the prefix before passing the request on
    assert c.get("/login").status_code == 200


def invite(c):
    r = c.post("/admin/invites", data={"note": "for Bora", "csrf": csrf(c, "/admin/invites")})
    assert r.status_code == 200
    return re.search(r"<code>(https://\S+?/join/([\w-]+))</code>", r.text).groups()


def join(c, token, **fields):
    data = {"uid": "bora", "password": "bora-chose-this-1", "confirm": "bora-chose-this-1", "consent": "1", **fields}
    return c.post(f"/join/{token}", data={**data, "csrf": csrf(c)})  # any page's: the link may be spent


def test_an_invitation_link_makes_one_account_with_the_users_own_password(env):
    s, d, k, ka, app, tmp = env
    admin, _ = login(app, "moon", "moon-password-1")
    assert "Invite</a>" in admin.get("/").text
    link, token = invite(admin)
    assert link == f"https://www.m00nny.kr/join/{token}"  # PORTAL_PUBLIC_URL, derived from the domain
    assert token not in (tmp / "invites.db").read_bytes().decode(errors="ignore")  # only its hash is kept
    assert "for Bora" in admin.get("/admin/invites").text and token not in admin.get("/admin/invites").text
    anon = TestClient(app)
    assert join(anon, token, uid="moon").status_code == 400  # taken: said so, and the link still works
    assert join(anon, token, confirm="different-pass-1").status_code == 400
    assert join(anon, token, consent="").status_code == 400
    r = join(anon, token)
    assert r.status_code == 200 and "가입했습니다" in r.text
    assert k.passwords["bora"] == "bora-chose-this-1" and "bora" not in k.expired  # no change forced
    assert "bora" in d.groups["user"]
    c, _ = login(app, "bora", "bora-chose-this-1")
    assert c.get("/").status_code == 200
    assert anon.get(f"/join/{token}").status_code == 404  # once only
    assert join(TestClient(app), token, uid="bora2").status_code == 404 and "bora2" not in d.users
    log = (tmp / "audit.log").read_text()
    assert '"action": "create_invite"' in log and "invited by moon" in log


def test_a_failed_sign_up_leaves_the_link_usable(env):
    s, d, k, ka, app, tmp = env
    admin, _ = login(app, "moon", "moon-password-1")
    _, token = invite(admin)
    ka.fail = True
    anon = TestClient(app)
    assert join(anon, token).status_code == 400 and "bora" not in d.users  # LDAP rolled back
    ka.fail = False
    assert join(anon, token).status_code == 200 and "bora" in d.users


def test_invitations_are_for_admins_and_can_be_revoked(env):
    s, d, k, ka, app, tmp = env
    helpdesk, _ = login(app, "helen", "helen-password-1")
    assert "Invite</a>" not in helpdesk.get("/").text
    assert helpdesk.get("/admin/invites").status_code == 403
    assert helpdesk.post("/admin/invites", data={"csrf": csrf(helpdesk, "/")}).status_code == 403
    assert TestClient(app).get("/join/made-up-token").status_code == 404
    admin, _ = login(app, "moon", "moon-password-1")
    _, token = invite(admin)
    iid = re.search(r"/admin/invites/([\w-]+)/revoke", admin.get("/admin/invites").text).group(1)
    admin.post(f"/admin/invites/{iid}/revoke", data={"csrf": csrf(admin, "/admin/invites")})
    assert TestClient(app).get(f"/join/{token}").status_code == 404


def test_ldaps_trusts_ldap_conf_else_the_system(tmp_path):
    from portal.config import _ldap_cacert
    conf = tmp_path / "ldap.conf"
    conf.write_text("BASE dc=m00nny,dc=kr\n# TLS_CACERT /not/this\ntls_cacert  /etc/ldap/private-ca.pem\n")
    assert _ldap_cacert(str(conf)) == "/etc/ldap/private-ca.pem"
    conf.write_text("BASE dc=m00nny,dc=kr\n")
    assert _ldap_cacert(str(conf)).endswith(".crt") or _ldap_cacert(str(conf)).endswith(".pem")  # the system's
