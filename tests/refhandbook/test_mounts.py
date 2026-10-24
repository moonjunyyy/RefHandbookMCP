"""The directories users mount into their sandbox (agents/mounts.py): a policy picks a directory of
the user's by its path; root stages what the policies pick as idmapped binds, refusing (and saying
why) what is not the user's to pick. The mount itself is root's; here a recorder stands in for it,
and mountinfo is a file the test writes."""

from __future__ import annotations

import json
import os
import pwd
from pathlib import Path

import pytest

from refhandbook.agents import mounts as M

ME = os.getuid()


def account(name, uid, gid=None):
    return pwd.struct_passwd((name, "x", uid, gid if gid is not None else uid, "", "/nonexistent", "/bin/sh"))


@pytest.fixture
def site(tmp_path):
    data = tmp_path / "data"
    (data / "users").mkdir(parents=True)
    for u in ("moon", "kim", "root", "ghost", "Bad..name"):
        (data / "users" / f"{u}.db").touch()
    (data / "users" / "._moon.db").touch()  # a macOS sidecar, not a user
    home = tmp_path / "home"
    for d in ("moon/work", "moon/papers", "kim/work", "root/work", "elsewhere"):
        (home / d).mkdir(parents=True)
    (home / "moon" / "out").symlink_to(home / "elsewhere")  # a symlink leading out of moon's directory
    accounts = {"moon": account("moon", ME), "kim": account("kim", ME + 1), "root": account("root", 0)}
    offered = M.parse(f"{home}/{{user}}, {tmp_path}/corpus=corpus:ro")
    (tmp_path / "corpus" / "arxiv").mkdir(parents=True)
    picks = {
        "moon": [(f"{home}/moon/work", True), (f"{home}/moon/papers", False), (f"{home}/kim/work", False),
                 (f"{home}/moon/out", False), (f"{home}/moon/missing", False), ("corpus/arxiv", True)],
        "kim": [(f"{home}/kim/work", False)],
        "root": [(f"{home}/root/work", False)],
    }
    return data, home, (lambda n: accounts[n]), offered, tmp_path / "stage", (lambda db: picks.get(db.stem, []))


def test_the_offers_say_where_users_may_pick_from():
    o = M.parse("/data/{user}, /srv/corpora=corpora:ro")
    assert o == [M.Offer("/data/{user}"), M.Offer("/srv/corpora", "corpora", True)]
    with pytest.raises(M.MountError, match="no '..'"):
        M.source_path("/data/moon/ws/../../kim", o, "moon", 5)
    assert M.source_path("/data/moon/ws", o, "moon", 5) == ("/data/moon/ws", o[0])
    assert M.source_path("corpora/arxiv", o, "moon", 5) == ("/srv/corpora/arxiv", o[1])
    with pytest.raises(M.MountError, match="not in a directory you may mount from"):
        M.source_path("/data/kim/ws", o, "moon", 5)
    for bad in ("relative", "/x=", "/x=a b", "/x=a:rw", "/x=a,/y=a"):
        with pytest.raises(M.MountError):
            M.parse(bad)
    assert M.parse("") == [] and M.DEFAULT == "/home/{user}"


def test_root_stages_what_the_policies_pick_and_says_why_not(site):
    data, home, getpw, offered, stage, sources = site
    p = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw, sources=sources)
    assert [(s.user, s.host, s.ro) for s in p.stages] == [
        ("moon", str(home / "moon" / "work"), False), ("moon", str(home / "moon" / "papers"), False)]
    assert p.stages[0].target == str(M.staged_path(stage, "moon", str(home / "moon" / "work")))
    st = p.status["moon"]
    assert st[str(home / "moon" / "work")] == "ok"
    assert "not in a directory you may mount from" in st[f"{home}/kim/work"]  # another's: not even looked at
    assert "leads outside" in st[str(home / "moon" / "out")]
    assert "does not exist" in st[str(home / "moon" / "missing")]
    assert "may only be mounted read-only" in st[str(Path(str(home)).parent / "corpus" / "arxiv")]
    assert "is not yours" in p.status["kim"][str(home / "kim" / "work")]  # kim's directory, owned by ME here
    skipped = "\n".join(p.skipped)
    assert "root: uid 0 is a system account's" in skipped and "ghost: no such account" in skipped
    assert "Bad..name: not an account name" in skipped and "._moon" not in skipped
    p = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw, group="research", in_group=lambda pw, g: False,
               sources=sources)
    assert p.stages == [] and "moon: not in research" in "\n".join(p.skipped)


def test_apply_mounts_with_the_users_ids_mapped_to_the_services(site, tmp_path):
    data, home, getpw, offered, stage, sources = site
    p = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw, sources=sources)
    calls = []
    info = tmp_path / "mountinfo"
    info.write_text("")
    done = M.apply(p, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    work = p.stages[0]
    assert calls[0] == ["mount", "--bind", "-o", f"X-mount.idmap=u:{ME}:990:1 g:{ME}:968:1", work.host, work.target]
    assert len(done) == 2 and oct(os.stat(stage).st_mode & 0o777) == "0o755"
    said = M.status_of(stage, "moon")  # for the policy page: what became of each pick
    assert said[str(home / "moon" / "work")] == "ok" and "leads outside" in said[str(home / "moon" / "out")]
    # mounted now: a second run changes nothing
    info.write_text("".join(f"1 2 0:1 / {s.target} rw - zfs x rw\n" for s in p.stages))
    calls.clear()
    assert M.apply(p, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info)) == []
    # a mount made with another mapping (the reversed one of an earlier version) is made again
    state = stage / M.STATE
    old = json.loads(state.read_text())
    old[work.target]["idmap"] = f"u:990:{ME}:1 g:968:{ME}:1"
    state.write_text(json.dumps(old))
    M.apply(p, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    assert calls == [["umount", "--lazy", work.target],
                     ["mount", "--bind", "-o", f"X-mount.idmap=u:{ME}:990:1 g:{ME}:968:1", work.host, work.target]]
    # the policy no longer picks papers: it goes
    calls.clear()
    p2 = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw,
                sources=lambda db: [(f"{home}/moon/work", True)] if db.stem == "moon" else [])
    M.apply(p2, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    assert calls == [["umount", "--lazy", p.stages[1].target]] and not Path(p.stages[1].target).exists()


def test_the_store_says_what_its_policies_pick(tmp_path, monkeypatch):
    from refhandbook.agents.workspace import Workspace
    from refhandbook.store import Handbook

    (tmp_path / "users").mkdir()
    ws = Workspace(Handbook(tmp_path / "users" / "me.db"))
    (tmp_path / "home" / ws.owner / "w").mkdir(parents=True)
    monkeypatch.setenv("RHB_SANDBOX_MOUNTS", f"{tmp_path}/home/{{user}}")
    src = f"{tmp_path}/home/{ws.owner}/w"
    ws.set_policy("p", actor="user", mounts=[{"source": src, "target": "/mnt/w", "rw": True}])
    assert (src, True) in M.picked(tmp_path / "users" / "me.db")
    assert (tmp_path / M.REQUESTS).exists()  # root is asked to stage it at once


def test_mountinfo_escapes(tmp_path):
    info = tmp_path / "mountinfo"
    info.write_text("1 2 0:1 / /run/x-mounts/moon/my\\040data rw - zfs x rw\n1 2 0:1 / /run/other rw - tmpfs x rw\n")
    assert M.mounted(Path("/run/x-mounts"), str(info)) == {"/run/x-mounts/moon/my data"}


def test_the_sandbox_binds_the_staged_mount_and_says_why_it_cannot(tmp_path, monkeypatch):
    import threading

    from refhandbook import cap_api
    from refhandbook.kernel.graph import KernelError
    from refhandbook.store import Handbook

    hb = Handbook(tmp_path / "u.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    ws = cap_api.W()
    stage = tmp_path / "stage"
    monkeypatch.setenv("RHB_SANDBOX_MOUNTS", "/home/{user},/srv/corpus=corpus:ro")
    monkeypatch.setenv("RHB_SANDBOX_MOUNT_STAGE", str(stage))
    from refhandbook.agents.capkinds import mount_resolve

    src = f"/home/{ws.owner}/ws"
    # saved before root has staged it: the policy takes it (root mounts it after the save)
    ws.set_policy("x", actor="user", mounts=[{"source": src, "target": "/mnt/ws", "rw": True}])
    with pytest.raises(KernelError, match="not ready yet"):
        mount_resolve(ws, src)
    (stage / ws.owner).mkdir(parents=True)
    (stage / ws.owner / M.STATUS).write_text(json.dumps({src: f"{src} is not yours (it belongs to uid 0)"}))
    with pytest.raises(KernelError, match="is not yours"):
        mount_resolve(ws, src)
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(M.staged_path(stage, ws.owner, src)))
    assert mount_resolve(ws, src) == (str(M.staged_path(stage, ws.owner, src)), False)
    with pytest.raises(KernelError, match="read-only"):
        ws.set_policy("y", actor="user", mounts=[{"source": "corpus/x", "target": "/c", "rw": True}])
    with pytest.raises(KernelError, match="not in a directory you may mount from"):
        ws.set_policy("y", actor="user", mounts=[{"source": "/etc", "target": "/c"}])
