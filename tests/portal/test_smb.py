"""SMB passwords (docs/smb.md): the NT hash and Samba's encodings (portal/ntlm.py), what the directory
writes, and every place the site sets a password or disables an account carrying it to SMB."""
import re
from contextlib import contextmanager

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ldap3 import BASE, MOCK_SYNC, Connection, Server

from portal import deploy, ntlm
from portal.config import Settings
from portal.directory import Directory, DirectoryError, smb_password_mods
from portal.facts import facts
from portal.invites import InviteStore
from portal.main import create_app
from portal.projects import ProjectStore
from portal.requests import RequestStore
from portal.sso import create_app as create_sso
from .test_account_api import api
from .test_app import FakeDirectory, FakeKAdmin, FakeKerberos, csrf, invite, join, login, submit_request

# ── the hash and Samba's encodings ───────────────────────────────────────

# RFC 1320, appendix A.5
MD4 = {"": "31d6cfe0d16ae931b73c59d7e0c089c0", "a": "bde52cb31de33e46245e05fbdbd6fb24",
       "abc": "a448017aaf21d8525fc10ae87aa6729d", "message digest": "d9130a8164549fe818874806e1c7014b",
       "abcdefghijklmnopqrstuvwxyz": "d79e1c308aa5bbcdeea8ed63df412da9",
       "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789": "043f8582f241db351ce627e153e7f0e4",
       "1234567890" * 8: "e33b4ddc9c38f2199c3e7b164fcc0536"}


@pytest.mark.parametrize("text", list(MD4))
def test_md4_is_rfc_1320s(text):
    assert ntlm.md4(text.encode()).hex() == MD4[text]


def test_the_nt_hash_is_ms_nlmps_and_samba_writes_it_in_capitals():
    assert ntlm.nt_hash("Password") == "A4F49C406510BDCAB6824EE7C30FD852"  # MS-NLMP 4.2.2.1.2, NTOWFv1
    assert ntlm.nt_hash("비밀번호") == ntlm.md4("비밀번호".encode("utf-16-le")).hex().upper()


def test_flags_and_rids_as_samba_writes_them():
    assert ntlm.encode_flags({"U"}) == "[U          ]" and ntlm.encode_flags({"U", "D"}) == "[DU         ]"
    assert ntlm.flags_with("", disabled=True) == "[DU         ]"
    assert ntlm.flags_with("[DUX        ]", disabled=False) == "[UX         ]"  # the other letters stay
    assert ntlm.decode_flags("[DU         ]") == {"D", "U"}
    assert ntlm.user_rid(10001, 1000) == 21002


def test_an_entry_gets_its_account_once_and_its_hash_every_time():
    new = smb_password_mods({"objectClass": ["posixAccount"], "uidNumber": 10001}, "S-1-5-21-1-2-3-21002", "AB" * 16, 7)
    assert new["objectClass"][0][1] == ["sambaSamAccount"] and new["sambaSID"][0][1] == ["S-1-5-21-1-2-3-21002"]
    assert new["sambaAcctFlags"][0][1] == ["[U          ]"] and new["sambaNTPassword"][0][1] == ["AB" * 16]
    assert new["sambaPwdLastSet"][0][1] == ["7"] and new["sambaLMPassword"][0][1] == []
    again = smb_password_mods({"objectClass": ["posixAccount", "sambaSamAccount"], "sambaAcctFlags": "[DU         ]"},
                              None, "CD" * 16, 8)
    assert set(again) == {"sambaNTPassword", "sambaPwdLastSet", "sambaLMPassword"}  # the SID and flags stay
    with pytest.raises(DirectoryError):
        smb_password_mods({"objectClass": ["posixAccount"]}, None, "AB" * 16, 7)


# ── the directory (an in-memory LDAP server) ─────────────────────────────

DOMAIN_SID = "S-1-5-21-1-2-3"


@pytest.fixture
def ldap(monkeypatch):
    s = Settings()
    conn = Connection(Server("mock"), user="cn=admin", password="x", client_strategy=MOCK_SYNC, raise_exceptions=True)
    conn.strategy.add_entry("cn=admin", {"objectClass": ["person"], "cn": "admin", "sn": "admin", "userPassword": "x"})
    conn.strategy.add_entry(s.base_dn, {"objectClass": ["domain"], "dc": s.base_dn.split(",")[0][3:]})
    conn.strategy.add_entry(s.samba_domain_dn, {"objectClass": ["sambaDomain"], "sambaDomainName": s.workgroup,
                                                "sambaSID": DOMAIN_SID, "sambaAlgorithmicRidBase": "1000"})
    for i, uid in enumerate(("alice", "bob")):
        conn.strategy.add_entry(s.user_dn(uid), {"objectClass": ["inetOrgPerson", "posixAccount"], "uid": uid,
                                                 "uidNumber": str(10001 + i), "cn": uid, "sn": uid})
    conn.bind()

    @contextmanager
    def bound(self, creds=None):
        yield conn

    monkeypatch.setattr(Directory, "_conn", bound)
    d = Directory.__new__(Directory)  # no TLS context: nothing connects
    d.s = s
    return s, d, conn


def entry(conn, dn):
    """An entry's attributes, each as one value when it has one."""
    conn.search(dn, "(objectClass=*)", BASE, attributes=["*"])
    return {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in conn.response[0]["attributes"].items()}


def test_the_portal_gives_an_account_its_smb_side_once(ldap):
    s, d, conn = ldap
    d.set_smb_password("alice", "Password")
    a = entry(conn, s.user_dn("alice"))
    assert "sambaSamAccount" in a["objectClass"] and a["sambaNTPassword"] == "A4F49C406510BDCAB6824EE7C30FD852"
    assert a["sambaSID"] == f"{DOMAIN_SID}-21002" and a["sambaAcctFlags"] == "[U          ]"  # 10001 * 2 + 1000
    d.set_smb_password("alice", "another-one-1")
    a = entry(conn, s.user_dn("alice"))
    assert a["sambaNTPassword"] == ntlm.nt_hash("another-one-1") and a["sambaSID"] == f"{DOMAIN_SID}-21002"


def test_a_sid_held_elsewhere_or_no_domain_entry_is_refused(ldap):
    s, d, conn = ldap
    conn.strategy.add_entry(f"cn=other,{s.base_dn}", {"objectClass": ["device"], "cn": "other",
                                                       "sambaSID": f"{DOMAIN_SID}-21004"})  # bob's would-be SID
    with pytest.raises(DirectoryError, match="held by"):
        d.set_smb_password("bob", "Password")
    conn.delete(s.samba_domain_dn)
    with pytest.raises(DirectoryError, match="samba.ldif"):
        d.set_smb_password("alice", "Password")


def test_disabling_flags_the_smb_account_and_nothing_without_one(ldap):
    s, d, conn = ldap
    d.set_smb_enabled("bob", False)  # no SMB side yet: nothing to flag
    assert "sambaAcctFlags" not in entry(conn, s.user_dn("bob"))
    d.set_smb_password("alice", "Password")
    d.set_smb_enabled("alice", False)
    assert entry(conn, s.user_dn("alice"))["sambaAcctFlags"] == "[DU         ]"
    d.set_smb_enabled("alice", True)
    assert entry(conn, s.user_dn("alice"))["sambaAcctFlags"] == "[U          ]"


# ── where the site sets passwords ───────────────────────────────────────

@pytest.fixture
def smb_env(tmp_path):
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="", smb_passwords=True)
    d, k = FakeDirectory(s), FakeKerberos()
    ka = FakeKAdmin(k, d)
    app = create_app(s, d, k, ka, RequestStore(str(tmp_path / "requests.db")),
                     invites=InviteStore(str(tmp_path / "invites.db")), projects=ProjectStore(str(tmp_path / "projects.db")))
    return s, d, k, ka, app, tmp_path


def test_every_password_the_portal_sets_is_the_smb_password(smb_env):
    s, d, k, ka, app, _ = smb_env
    c, _ = login(app, "alice", "alice-password-1")
    c.post("/password", data={"old": "alice-password-1", "new": "brand-new-pass-2", "confirm": "brand-new-pass-2",
                              "csrf": csrf(c, "/")})
    assert d.smb["alice"] == ("portal", "brand-new-pass-2") == ("portal", k.passwords["alice"])
    r = api(c, s, "POST", "/me/password", {"old": "brand-new-pass-2", "new": "third-pass-333", "confirm": "third-pass-333"})
    assert r.json() == {"changed": True} and d.smb["alice"] == ("portal", "third-pass-333")

    admin, _ = login(app, "moon", "moon-password-1")
    r = admin.post("/admin/users/new", data={"uid": "bob", "name": "", "mail": "", "loginShell": "/bin/bash",
                                             "csrf": csrf(admin, "/")})
    temp = re.search(r'class="secret"><code>([^<]+)</code>', r.text).group(1)
    assert d.smb["bob"] == ("portal", temp)
    b = TestClient(app)
    b.post("/login", data={"uid": "bob", "password": temp, "csrf": csrf(b)})
    b.post("/expired", data={"uid": "bob", "old": temp, "new": "bobs-own-pass-1", "confirm": "bobs-own-pass-1",
                             "csrf": csrf(b, "/expired")})
    assert d.smb["bob"] == ("portal", "bobs-own-pass-1")

    r = api(admin, s, "POST", "/users", {"uid": "cora", "name": "", "mail": "", "loginShell": "/bin/bash"})
    assert d.smb["cora"] == ("portal", r.json()["password"]) and "warning" not in r.json()
    assert d.smb["alice"] == ("portal", "third-pass-333")
    r = api(admin, s, "POST", "/users/alice/reset")
    assert r.json()["password"] == k.passwords["alice"] and d.smb["alice"] == ("portal", k.passwords["alice"])
    admin.post("/admin/users/alice/reset", data={"csrf": csrf(admin, "/")})
    assert d.smb["alice"] == ("portal", k.passwords["alice"])

    submit_request(app)
    rid = api(admin, s, "GET", "/requests").json()[0]["id"]
    r = api(admin, s, "POST", f"/requests/{rid}/approve", {"loginShell": "/bin/bash"})
    assert d.smb["dana"] == ("portal", r.json()["password"])
    _, token = invite(admin)
    join(TestClient(app), token)
    assert d.smb["bora"] == ("portal", "bora-chose-this-1")


def test_a_disabled_account_is_disabled_for_smb(smb_env):
    s, d, k, ka, app, _ = smb_env
    admin, _ = login(app, "moon", "moon-password-1")
    assert api(admin, s, "PATCH", "/users/alice", {"enabled": False}).json()["disabled"] is True
    assert "alice" in d.smb_disabled
    admin.post("/admin/users/alice/enabled", data={"csrf": csrf(admin, "/"), "enabled": "1"})
    assert "alice" not in d.smb_disabled


def test_without_smb_passwords_nothing_reaches_smb(tmp_path):
    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"), kadmin_policy="")
    assert not s.smb_passwords  # off unless the site says so
    d, k = FakeDirectory(s), FakeKerberos()
    app = create_app(s, d, k, FakeKAdmin(k, d), RequestStore(str(tmp_path / "requests.db")),
                     invites=InviteStore(str(tmp_path / "invites.db")), projects=ProjectStore(str(tmp_path / "projects.db")))
    c, _ = login(app, "moon", "moon-password-1")
    api(c, s, "POST", "/me/password", {"old": "moon-password-1", "new": "moons-new-pass-1", "confirm": "moons-new-pass-1"})
    api(c, s, "POST", "/users/alice/reset")
    api(c, s, "PATCH", "/users/alice", {"enabled": False})
    assert d.smb == {} and d.smb_disabled == set()


def test_a_failing_smb_step_keeps_the_kerberos_change_and_says_so(smb_env):
    s, d, k, ka, app, tmp = smb_env
    d.fail_smb = DirectoryError("no Samba domain entry")
    c, _ = login(app, "alice", "alice-password-1")
    r = api(c, s, "POST", "/me/password", {"old": "alice-password-1", "new": "brand-new-pass-2",
                                           "confirm": "brand-new-pass-2"})
    assert r.status_code == 200 and r.json()["changed"] and "SMB" in r.json()["warning"]
    assert k.passwords["alice"] == "brand-new-pass-2" and "alice" not in d.smb
    log = (tmp / "audit.log").read_text()
    assert '"action": "smb_password"' in log and "no Samba domain entry" in log
    r = c.post("/password", data={"old": "brand-new-pass-2", "new": "third-pass-333", "confirm": "third-pass-333",
                                  "csrf": csrf(c, "/")})
    assert k.passwords["alice"] == "third-pass-333" and "SMB" in r.text  # the page says it too
    admin, _ = login(app, "moon", "moon-password-1")
    r = api(admin, s, "POST", "/users/alice/reset")
    assert r.json()["password"] == k.passwords["alice"] and "SMB" in r.json()["warning"]
    r = api(admin, s, "PATCH", "/users/alice", {"enabled": False})
    assert r.json()["disabled"] is True and "SMB" in r.json()["warning"]


def test_the_sign_in_writes_a_changed_password_as_the_person(tmp_path):
    s = Settings(session_secret="x" * 40, sso_secret="y" * 40, cookie_secure=False,
                 audit_log=str(tmp_path / "audit.log"), smb_passwords=True)
    k, d = FakeKerberos(), FakeDirectory(s)
    app = create_sso(s, k, Ed25519PrivateKey.generate(), d)
    k.expired.add("alice")
    c = TestClient(app)
    c.post("/auth/expired", data={"uid": "alice", "old": "alice-password-1", "new": "fresh-password-22",
                                  "confirm": "fresh-password-22", "csrf": csrf(c, "/auth/expired")})
    assert k.passwords["alice"] == "fresh-password-22" and d.smb["alice"] == ("self", "fresh-password-22")
    d.fail_smb = DirectoryError("no ticket")
    k.expired.add("alice")
    r = c.post("/auth/expired", data={"uid": "alice", "old": "fresh-password-22", "new": "fresher-password-3",
                                      "confirm": "fresher-password-3", "csrf": csrf(c, "/auth/expired")})
    assert k.passwords["alice"] == "fresher-password-3" and "SMB" in r.text


# ── the installer and the facts ──────────────────────────────────────────

@pytest.fixture
def fresh(monkeypatch):
    facts.cache_clear()
    yield monkeypatch
    facts.cache_clear()


def test_the_workgroup_derives_from_the_realm(fresh, tmp_path):
    fresh.setenv("PORTAL_REALM", "LAB.EXAMPLE.ORG")
    s = tmp_path / "site.toml"
    s.write_text("")
    assert facts(str(s)).workgroup == "LAB"
    s.write_text('[site]\nworkgroup = "OTHER"\nsmb_passwords = "1"\n')
    facts.cache_clear()
    assert facts(str(s)).workgroup == "OTHER" and facts(str(s)).extra["smb_passwords"] == "1"


def test_the_installer_renders_sambas_side(fresh, tmp_path):
    fresh.setenv("PORTAL_REALM", "EXAMPLE.ORG")
    fresh.setattr(deploy, "_net_sid", lambda: "S-1-5-21-9-8-7")
    s = tmp_path / "site.toml"
    s.write_text("")
    files = deploy.rendered(facts(str(s)), s)
    conf = files["/etc/example/directory/smb-passdb.conf"][0]
    for line in ("passdb backend = ldapsam:ldapi:///", "ldap suffix = dc=example,dc=org", "ldap user suffix = ou=Users",
                 "ldap group suffix = ou=Groups", "ldap admin dn = uid=samba,ou=Services,dc=example,dc=org",
                 "workgroup = EXAMPLE"):
        assert line in conf.splitlines()
    ldif = files["/etc/example/directory/samba.ldif"][0]
    assert "dn: sambaDomainName=EXAMPLE,dc=example,dc=org" in ldif and "sambaSID: S-1-5-21-9-8-7" in ldif
    assert "uid: samba\\n" in ldif and "@@" not in conf + ldif
    acl = files["/etc/example/directory/slapd-acl.ldif"][0]
    rules = re.findall(r"^olcAccess: \{(\d+)\}to (.*)$", acl, flags=re.M)
    assert [int(n) for n, _ in rules] == list(range(len(rules)))  # numbered in order
    hashes = next(i for i, (_, r) in enumerate(rules) if "sambaNTPassword" in r)
    block = acl.split(f"olcAccess: {{{hashes}}}")[1].split("olcAccess:")[0]
    assert 'by dn.exact="uid=samba,ou=Services,dc=example,dc=org" read' in block and "by * none" in block
    assert "by self =w" in block and " write" not in block.replace("=w", "")  # the portal and the person: write only
    # nothing before it reaches the hash: only rules naming other attributes, or none of a user's entry
    for _, r in rules[:hashes]:
        assert "attrs=" in r and "samba" not in r.lower() and not r.startswith("*")
    assert rules[-1][1] == "* by * read"
