"""Projects (portal/projects.py, /account/api/v1/projects): groups people make themselves — made by a
member, found and joined by policy, managed by owners, archived rather than deleted — over the fake
directory the other tests use."""

import re

from portal.directory import DirectoryError

from .test_account_api import api
from .test_app import env, login  # noqa: F401 — fixture

P = "/projects"


def create(c, s, name, **over):
    return api(c, s, "POST", P, {"name": name, "title": over.pop("title", name.title()), **over})


def test_a_member_makes_a_project_and_owns_it(env):
    s, d, k, ka, app, tmp = env
    c, _ = login(app, "alice", "alice-password-1")
    assert api(c, s, "GET", P).json() == {"projects": [], "may_create": True}
    r = create(c, s, "chain", description="사슬 이미지", join_policy="request")
    assert r.status_code == 201
    v = r.json()
    assert v["cn"] == "chain" and v["gid"] >= s.project_gid_min and v["members"] == ["alice"]
    assert v["owners"] == ["alice"] and v["role"] == "owner" and v["may"]["manage"] and not v["may"]["leave"]
    # the group is a POSIX group under the projects' OU, apart from the site's role groups
    assert d.projects["chain"]["members"] == {"alice"} and d.projects["chain"]["description"] == "사슬 이미지"
    assert "chain" not in api(c, s, "GET", "/me").json()["user"]["groups"]
    # a name a user or a group has, a reserved one, a bad one
    assert create(c, s, "moon").status_code == 502  # the directory refuses: a user has it
    assert create(c, s, "homes").status_code == 400 and create(c, s, "Chain").status_code == 400
    assert create(c, s, "chain").status_code == 400  # taken by this project
    assert api(c, s, "POST", P, {"name": "x2", "join_policy": "whatever"}).status_code == 400
    assert (tmp / "audit.log").read_text().count('"project_create"') == 1


def test_joining_by_policy(env):
    s, d, k, ka, app, _ = env
    a, _ = login(app, "alice", "alice-password-1")
    h, _ = login(app, "helen", "helen-password-1")
    create(a, s, "open-one", join_policy="open")
    create(a, s, "ask-one", join_policy="request")
    create(a, s, "link-one", join_policy="invite")
    create(a, s, "hidden", join_policy="open", listed=False)
    seen = [p["cn"] for p in api(h, s, "GET", P).json()["projects"]]
    assert seen == ["ask-one", "link-one", "open-one"]  # listed ones, by title; the hidden one not at all
    assert api(h, s, "GET", f"{P}/hidden").status_code == 403  # as absent: tells nothing
    # open: in at once
    v = api(h, s, "POST", f"{P}/open-one/join").json()
    assert v["member"] and v["role"] == "member" and d.projects["open-one"]["members"] == {"alice", "helen"}
    assert api(h, s, "POST", f"{P}/open-one/join").status_code == 400  # already in
    # request: waits for an owner; the owner sees it; approving adds
    v = api(h, s, "POST", f"{P}/ask-one/join", {"note": "같이 하고 싶어요"}).json()
    assert not v["member"] and v["requested"] and not v["may"]["join"]
    assert api(h, s, "POST", f"{P}/ask-one/join").status_code == 400  # asked already
    reqs = api(a, s, "GET", f"{P}/ask-one").json()["requests"]
    assert [r["uid"] for r in reqs] == ["helen"] and reqs[0]["note"] == "같이 하고 싶어요"
    assert "requests" not in api(h, s, "GET", f"{P}/ask-one").json()  # not for a non-owner
    v = api(a, s, "POST", f"{P}/ask-one/requests/{reqs[0]['id']}/approve").json()
    assert "helen" in v["members"] and api(a, s, "GET", f"{P}/ask-one").json()["requests"] == []
    assert api(a, s, "POST", f"{P}/ask-one/requests/{reqs[0]['id']}/approve").status_code == 403  # gone
    # a request taken back, and one rejected
    create(a, s, "ask-two", join_policy="request")
    api(h, s, "POST", f"{P}/ask-two/join")
    assert not api(h, s, "POST", f"{P}/ask-two/withdraw").json()["requested"]
    api(h, s, "POST", f"{P}/ask-two/join")
    rid = api(a, s, "GET", f"{P}/ask-two").json()["requests"][0]["id"]
    assert "helen" not in api(a, s, "POST", f"{P}/ask-two/requests/{rid}/reject").json()["members"]
    # invite: a link, used once, by whoever is signed in
    assert api(h, s, "POST", f"{P}/link-one/join").status_code == 403
    r = api(a, s, "POST", f"{P}/link-one/invites", {"note": "헬렌에게"})
    assert r.status_code == 201 and re.search(r"/projects/join/[\w-]+$", r.json()["link"])
    token = r.json()["link"].rsplit("/", 1)[1]
    assert [i["note"] for i in api(a, s, "GET", f"{P}/link-one").json()["invites"]] == ["헬렌에게"]
    assert api(h, s, "POST", f"{P}/join", {"token": token}).json()["member"]
    assert api(h, s, "POST", f"{P}/join", {"token": token}).status_code == 403  # used up
    r = api(a, s, "POST", f"{P}/link-one/invites", {"note": ""})
    token = r.json()["link"].rsplit("/", 1)[1]
    assert api(h, s, "POST", f"{P}/join", {"token": token}).status_code == 400  # already a member…
    assert len(api(a, s, "GET", f"{P}/link-one").json()["invites"]) == 1  # …so the link stays usable
    iid = api(a, s, "GET", f"{P}/link-one").json()["invites"][0]["id"]
    assert api(a, s, "POST", f"{P}/link-one/invites/{iid}/revoke").json() == {"revoked": True}
    assert api(h, s, "POST", f"{P}/join", {"token": token}).status_code == 403


def test_owners_members_and_the_last_owner(env):
    s, d, k, ka, app, _ = env
    a, _ = login(app, "alice", "alice-password-1")
    h, _ = login(app, "helen", "helen-password-1")
    create(a, s, "team", join_policy="invite")
    # a non-owner manages nothing
    assert api(h, s, "PUT", f"{P}/team/members/helen", {}).status_code == 403
    assert api(h, s, "PATCH", f"{P}/team", {"title": "x"}).status_code == 403
    # the owner adds, makes an owner, steps down, leaves
    assert api(a, s, "PUT", f"{P}/team/members/nobody", {}).status_code == 403  # no such user
    v = api(a, s, "PUT", f"{P}/team/members/helen", {}).json()
    assert v["members"] == ["alice", "helen"] and v["owners"] == ["alice"]
    assert api(a, s, "PUT", f"{P}/team/members/helen", {}).status_code == 400  # already in
    assert api(a, s, "DELETE", f"{P}/team/owners/alice").status_code == 403  # the last owner
    assert api(a, s, "POST", f"{P}/team/leave").status_code == 403
    assert api(a, s, "DELETE", f"{P}/team/members/alice").status_code == 403
    assert api(a, s, "PUT", f"{P}/team/owners/helen", {}).json()["owners"] == ["alice", "helen"]
    assert api(a, s, "DELETE", f"{P}/team/owners/alice").json()["owners"] == ["helen"]
    assert api(a, s, "GET", f"{P}/team").json()["role"] == "member"
    v = api(a, s, "POST", f"{P}/team/leave").json()
    assert not v["member"] and v["role"] == "none" and d.projects["team"]["members"] == {"helen"}
    assert "requests" not in api(a, s, "GET", f"{P}/team").json()  # listed, so still seen; no longer managed
    # removing an owner who is not the last one drops the ownership too
    api(h, s, "PUT", f"{P}/team/members/alice", {})
    api(h, s, "PUT", f"{P}/team/owners/alice", {})
    v = api(h, s, "DELETE", f"{P}/team/members/alice").json()
    assert v["owners"] == ["helen"] and v["members"] == ["helen"]


def test_settings_archiving_and_the_admin(env):
    s, d, k, ka, app, _ = env
    a, _ = login(app, "alice", "alice-password-1")
    m, _ = login(app, "moon", "moon-password-1")
    h, _ = login(app, "helen", "helen-password-1")
    create(a, s, "paper", join_policy="open", description="first")
    v = api(a, s, "PATCH", f"{P}/paper", {"title": "The Paper", "description": "second", "listed": False}).json()
    assert v["title"] == "The Paper" and d.projects["paper"]["description"] == "second" and not v["listed"]
    assert api(a, s, "PATCH", f"{P}/paper", {}).status_code == 400
    # the admin manages every project without being in any
    v = api(m, s, "GET", f"{P}/paper").json()
    assert v["role"] == "admin" and not v["member"] and v["may"]["manage"] and "requests" in v
    assert [p["cn"] for p in api(m, s, "GET", P).json()["projects"]] == ["paper"]  # unlisted, still seen
    assert api(h, s, "GET", P).json()["projects"] == []
    # archived: no changes, no joining; members and admins still see it; restored: as before
    v = api(m, s, "POST", f"{P}/paper/archive").json()
    assert v["archived"] and v["may"]["restore"] and not v["may"]["archive"]
    assert api(a, s, "PATCH", f"{P}/paper", {"title": "x"}).status_code == 403
    assert api(h, s, "POST", f"{P}/paper/join").status_code == 403
    assert api(a, s, "POST", f"{P}/paper/archive").status_code == 403
    assert d.projects["paper"]["members"] == {"alice"}  # the group stays
    assert api(a, s, "GET", f"{P}/paper").json()["archived"]
    assert api(a, s, "POST", f"{P}/paper/restore").json()["archived"] is None
    assert api(a, s, "POST", f"{P}/paper/restore").status_code == 400


def test_an_owner_deletes_a_project_after_typing_its_name(env):
    s, d, k, ka, app, tmp = env
    a, _ = login(app, "alice", "alice-password-1")
    h, _ = login(app, "helen", "helen-password-1")
    gid = create(a, s, "gone", join_policy="open").json()["gid"]
    api(h, s, "POST", f"{P}/gone/join")
    assert api(h, s, "DELETE", f"{P}/gone?confirm=gone").status_code == 403  # a member, not an owner
    assert api(a, s, "DELETE", f"{P}/gone?confirm=gon").status_code == 400  # the name, typed again
    assert api(a, s, "DELETE", f"{P}/gone?confirm=gone").json() == {"deleted": "gone"}
    assert "gone" not in d.projects and api(a, s, "GET", f"{P}/gone").status_code == 403
    assert api(h, s, "GET", P).json()["projects"] == []
    assert '"project_delete"' in (tmp / "audit.log").read_text()
    # the name is free again, the gid is not: files left with it stay with no one
    assert create(a, s, "gone").json()["gid"] == gid + 1
    # an archived project can be deleted too, and the admin may delete any
    create(a, s, "old")
    api(a, s, "POST", f"{P}/old/archive")
    m, _ = login(app, "moon", "moon-password-1")
    assert api(m, s, "DELETE", f"{P}/old?confirm=old").json() == {"deleted": "old"}


def test_only_admins_make_projects_when_the_site_says_so(tmp_path):
    from dataclasses import replace

    from portal.config import Settings
    from portal.invites import InviteStore
    from portal.main import create_app
    from portal.projects import ProjectStore
    from portal.requests import RequestStore

    from .test_app import FakeDirectory, FakeKAdmin, FakeKerberos

    s = Settings(session_secret="x" * 40, cookie_secure=False, audit_log=str(tmp_path / "audit.log"),
                 kadmin_policy="", project_create="admin")
    d, k = FakeDirectory(s), FakeKerberos()
    stores = {"requests": RequestStore(":memory:"), "invites": InviteStore(":memory:")}
    app = create_app(s, d, k, FakeKAdmin(k, d), projects=ProjectStore(":memory:"), **stores)
    a, _ = login(app, "alice", "alice-password-1")
    assert api(a, s, "GET", P).json()["may_create"] is False
    assert create(a, s, "no").status_code == 403
    m, _ = login(app, "moon", "moon-password-1")
    assert create(m, s, "yes").status_code == 201
    # a site that does not have projects at all answers nothing for them
    off = create_app(replace(s, projects_enabled=False), d, k, FakeKAdmin(k, d), **stores)
    m, _ = login(off, "moon", "moon-password-1")
    assert api(m, s, "GET", P).status_code == 404


def test_a_group_under_the_ou_that_the_portal_did_not_make_is_not_a_project(env):
    s, d, k, ka, app, _ = env
    d.projects["stray"] = {"gid": 30999, "members": {"alice"}, "description": ""}
    a, _ = login(app, "alice", "alice-password-1")
    assert api(a, s, "GET", P).json()["projects"] == [] and api(a, s, "GET", f"{P}/stray").status_code == 403


def test_the_directory_refusing_is_a_reference_and_leaves_no_half_project(env):
    s, d, k, ka, app, _ = env
    a, _ = login(app, "alice", "alice-password-1")
    d.fail_projects = DirectoryError("no such object: ou=Projects")
    r = create(a, s, "half")
    assert r.status_code == 502 and "reference" in r.json()["error"]["message"]
    d.fail_projects = None
    assert api(a, s, "GET", P).json()["projects"] == []
    assert create(a, s, "half").status_code == 201  # the name is free: nothing was kept
