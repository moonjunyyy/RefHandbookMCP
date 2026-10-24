"""Staging the offered mount directories as idmapped binds (agents/mounts.py): who is staged, what is
mounted with which mapping, and what goes when the offer changes. The mount itself is root's; here a
recorder stands in for it, and mountinfo is a file the test writes."""

from __future__ import annotations

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
    (home / "moon" / "data").mkdir(parents=True)
    (home / "kim" / "data").mkdir(parents=True)
    (home / "root" / "data").mkdir(parents=True)
    accounts = {"moon": account("moon", ME), "kim": account("kim", ME + 1), "root": account("root", 0)}

    def getpw(name):
        return accounts[name]

    offered = M.parse(f"{home}/{{user}}/data=data, {home}/{{user}}/papers=papers:ro")
    return data, home, getpw, offered, tmp_path / "stage"


def test_only_real_users_who_own_the_directory_are_staged(site):
    data, home, getpw, offered, stage = site
    stages, skipped = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw)
    assert [(s.user, s.host, s.target, s.ro) for s in stages] == [
        ("moon", str(home / "moon" / "data"), str(stage / "moon" / "data"), False)]
    text = "\n".join(skipped)
    assert "root: uid 0 is a system account's" in text and "ghost: no such account" in text
    assert "Bad..name: not an account name" in text
    assert f"kim/data: {home / 'kim' / 'data'} belongs to uid {ME}, not kim" in text  # not kim's own: refused
    assert "._moon" not in text
    stages, skipped = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw, group="research",
                             in_group=lambda pw, g: False)
    assert stages == [] and "moon: not in research" in "\n".join(skipped)


def test_a_symlink_to_someone_elses_directory_is_not_staged(site, tmp_path):
    data, home, getpw, offered, stage = site
    (home / "moon" / "data").rmdir()
    (home / "moon" / "data").symlink_to(home / "kim" / "data")  # kim's (here: owned by ME, but kim is ME+1)
    accounts = {"moon": account("moon", ME + 5)}
    stages, skipped = M.plan(data, stage, 990, offered, min_uid=1000, getpw=lambda n: accounts[n])
    assert stages == [] and any("belongs to uid" in s for s in skipped)


def test_apply_mounts_with_the_users_ids_mapped_to_the_services(site, tmp_path):
    data, home, getpw, offered, stage = site
    (home / "moon" / "papers").mkdir()
    stages, _ = M.plan(data, stage, 990, offered, min_uid=1000, getpw=getpw)
    calls = []
    info = tmp_path / "mountinfo"
    info.write_text("")
    done = M.apply(stages, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    assert calls == [
        ["mount", "--bind", "-o", f"X-mount.idmap=u:{ME}:990:1 g:{ME}:968:1", str(home / "moon" / "data"),
         str(stage / "moon" / "data")],
        ["mount", "--bind", "-o", f"X-mount.idmap=u:{ME}:990:1 g:{ME}:968:1,ro", str(home / "moon" / "papers"),
         str(stage / "moon" / "papers")]]
    assert len(done) == 2 and oct(os.stat(stage).st_mode & 0o777) == "0o755"
    # mounted now: a second run changes nothing
    info.write_text("".join(f"1 2 0:1 / {s.target} rw - zfs x rw\n" for s in stages))
    calls.clear()
    assert M.apply(stages, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info)) == []
    assert calls == []
    # a mount made with another mapping (the reversed one of an earlier version) is made again
    state = stage / M.STATE
    import json
    old = json.loads(state.read_text())
    old[stages[0].target]["idmap"] = f"u:990:{ME}:1 g:968:{ME}:1"
    state.write_text(json.dumps(old))
    M.apply(stages, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    assert calls == [["umount", "--lazy", stages[0].target],
                     ["mount", "--bind", "-o", f"X-mount.idmap=u:{ME}:990:1 g:{ME}:968:1", stages[0].host, stages[0].target]]
    calls.clear()
    # papers is no longer offered and data turns read-only: papers goes, data is mounted again, ro
    offered2 = M.parse(f"{home}/{{user}}/data=data:ro")
    stages2, _ = M.plan(data, stage, 990, offered2, min_uid=1000, getpw=getpw)
    M.apply(stages2, stage, 990, 968, run=lambda c: calls.append(c) or 0, mountinfo=str(info))
    assert ["umount", "--lazy", str(stage / "moon" / "papers")] in calls
    assert ["umount", "--lazy", str(stage / "moon" / "data")] in calls
    assert calls[-1][3].endswith(",ro") and calls[-1][-1] == str(stage / "moon" / "data")
    assert not (stage / "moon" / "papers").exists()


def test_mountinfo_escapes_and_bad_offers(tmp_path):
    info = tmp_path / "mountinfo"
    info.write_text("1 2 0:1 / /run/x-mounts/moon/my\\040data rw - zfs x rw\n1 2 0:1 / /run/other rw - tmpfs x rw\n")
    assert M.mounted(Path("/run/x-mounts"), str(info)) == {"/run/x-mounts/moon/my data"}
    for bad in ("relative=data", "/x=", "/x=a b", "/x=a:rw", "/x=a,/y=a"):
        with pytest.raises(M.MountError):
            M.parse(bad)


def test_the_policy_resolves_a_name_to_its_staged_mount(tmp_path, monkeypatch):
    import threading

    from refhandbook import cap_api
    from refhandbook.kernel.graph import KernelError
    from refhandbook.store import Handbook

    hb = Handbook(tmp_path / "u.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    ws = cap_api.W()
    stage = tmp_path / "stage"
    (stage / ws.owner / "data" / "2024").mkdir(parents=True)  # what root staged for this user
    monkeypatch.setenv("RHB_SANDBOX_MOUNTS", "/home/{user}/data=data,/srv/corpus=corpus:ro")
    monkeypatch.setenv("RHB_SANDBOX_MOUNT_STAGE", str(stage))
    from refhandbook.agents.capkinds import mount_resolve

    assert mount_resolve(ws, "data/2024")[0] == str(stage / ws.owner / "data" / "2024")
    with pytest.raises(KernelError, match="not prepared for you"):
        ws.set_policy("x", actor="user", mounts=[{"source": "corpus", "target": "/c"}])
