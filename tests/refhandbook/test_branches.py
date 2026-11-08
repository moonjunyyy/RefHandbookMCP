"""A run's branches (agents/branches.py, docs/agents.md "Branches"): the repositories of a read-write mount are found,
each gets a worktree on the run's branch before the run's first command, the agents' commands see the worktree over the
repository and its git directory at /git/<slug>, and at the run's end the work is committed on the branch and merged
when the run ended done — undone and kept on the branch when it conflicts or would overwrite uncommitted changes.

Git runs here for real; the sandbox is stood in for (this host gives no user namespaces): the same scripts run by sh with
each path inside replaced by its bind's source, and a bind whose source no longer is what was looked at is refused, as
sandbox.Spec.bind_ids makes the launcher do."""

import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from refhandbook import Handbook, cap_api
from refhandbook.agents import branches as B
from refhandbook.agents.workspace import Runner

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")

ENV = {**os.environ, "GIT_AUTHOR_NAME": "me", "GIT_AUTHOR_EMAIL": "me@example.org", "GIT_COMMITTER_NAME": "me",
       "GIT_COMMITTER_EMAIL": "me@example.org", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
RUN = "run:0123abcd"


def git(cwd, *args, check=True):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=ENV)
    if check and p.returncode:
        raise AssertionError(p.stderr)
    return p.stdout.strip()


def repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("one\ntwo\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "first")
    return path


def launch(binds, ids, script, env):
    """The sandbox stood in for: each bind's source checked against what was looked at, then the script with each path
    inside replaced by its source (longest first), run by sh."""
    for host, inside in binds:
        st = os.stat(host)
        if inside in ids and [st.st_dev, st.st_ino] != ids[inside]:
            raise B.BranchError(f"bind source for {inside} changed after it was checked; refused")
    for host, inside in sorted(binds, key=lambda b: -len(b[1])):
        script = script.replace(inside, host)
    p = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env={**ENV, **env})
    return p.returncode, p.stdout


@pytest.fixture
def mount(tmp_path):
    m = tmp_path / "workspace"
    repo(m / "a")
    m.joinpath("notes").mkdir()
    m.joinpath("notes", "x.md").write_text("not in a repository\n")
    return m


def made(tmp_path, mount):
    b = B.Branches(tmp_path / "run", RUN)
    binds, ids = b.views([(str(mount), "/Workspace")], launch)
    return b, binds, ids


# ── which repositories ───────────────────────────────────────────────────────────────────────────────────


def test_a_mount_gives_its_repositories_down_to_the_depth(tmp_path):
    m = tmp_path / "m"
    repo(m / "a")
    repo(m / "a" / "inner")  # inside a repository: not looked into
    repo(m / "b" / "c")  # depth 2
    repo(m / "d" / "e" / "f")  # depth 3: deeper than the default
    repo(m / ".hidden" / "r")
    (m / "link").symlink_to(m / "a")
    (m / "wt").mkdir()
    (m / "wt" / ".git").write_text("gitdir: elsewhere\n")  # another worktree: its .git is a file
    (m / "plain").mkdir()
    got = B.find(str(m), "/W")
    assert [(r.rel, r.inside) for r in got] == [("a", "/W/a"), ("b/c", "/W/b/c")]
    assert got[0].root == str(m / "a") and got[0].slug.startswith("a-") and got[0].slug != got[1].slug
    assert [r.rel for r in B.find(str(m), "/W", depth=3)] == ["a", "b/c", "d/e/f"]
    one = B.find(str(m / "a"), "/W")  # the mount is a repository
    assert [(r.rel, r.inside, r.root) for r in one] == [("", "/W", str(m / "a"))]


# ── the run's branch ─────────────────────────────────────────────────────────────────────────────────────


def test_the_run_works_on_its_branch_and_it_is_merged_when_the_run_ends_done(tmp_path, mount):
    b, binds, ids = made(tmp_path, mount)
    a = mount / "a"
    (r,) = b.load().repos
    wt = Path(r.worktree)
    assert binds == [(str(wt), "/Workspace/a"), (str(a / ".git"), f"/git/{r.slug}")] and set(ids) == {"/Workspace/a", f"/git/{r.slug}"}
    assert (wt / "a.txt").read_text() == "one\ntwo\n" and r.base == git(a, "rev-parse", "HEAD")
    assert git(a, "rev-parse", "run/0123abcd") == r.base  # the branch, from HEAD
    assert (wt / ".git").read_text().startswith("gitdir: ") and r.name and (a / ".git" / "worktrees" / r.name).is_dir()
    assert git(a, "branch", "--show-current") == "main" and (a / "a.txt").read_text() == "one\ntwo\n"
    assert b.views([(str(mount), "/Workspace")], launch)[0] == binds  # made once: the next command sees the same
    # the agents' work, and the person's own meanwhile (another file, committed)
    (wt / "a.txt").write_text("one\nTWO\n")
    (wt / "b.txt").write_text("new\n")
    (a / "c.txt").write_text("mine\n")
    git(a, "add", "c.txt")
    git(a, "commit", "-qm", "my own")
    got = b.finish("done", "tidy the notes\n\nagents run 0123abcd", launch)
    assert got["branch"] == "run/0123abcd" and got["repos"] == [{"repo": "/Workspace/a", "state": "merged", "files": 2, "why": ""}]
    assert (a / "a.txt").read_text() == "one\nTWO\n" and (a / "b.txt").read_text() == "new\n" and (a / "c.txt").read_text() == "mine\n"
    assert "tidy the notes" in git(a, "log", "--format=%s", "-3")
    assert git(a, "branch", "--list", "run/*") == ""  # merged: the branch is gone
    assert not wt.exists() and not (a / ".git" / "worktrees" / r.name).exists()
    assert b.finish("done", "again", launch) == got  # once


def test_a_conflict_leaves_the_branch_and_the_checkout_as_they_were(tmp_path, mount):
    b, _, _ = made(tmp_path, mount)
    a, (r,) = mount / "a", b.load().repos
    Path(r.worktree, "a.txt").write_text("one\nTWO\n")
    (a / "a.txt").write_text("one\nzwei\n")
    git(a, "commit", "-qam", "mine")
    got = b.finish("done", "change two", launch)["repos"][0]
    assert got["state"] == "kept" and "conflicts:" in got["why"] and "a.txt" in got["why"]
    assert (a / "a.txt").read_text() == "one\nzwei\n" and not (a / ".git" / "MERGE_HEAD").exists()
    assert git(a, "status", "--porcelain") == ""
    assert git(a, "show", "run/0123abcd:a.txt") == "one\nTWO"  # the work, on the branch
    assert not Path(r.worktree).exists() and not (a / ".git" / "worktrees" / r.name).exists()


def test_a_merge_that_would_overwrite_uncommitted_changes_is_not_made(tmp_path, mount):
    b, _, _ = made(tmp_path, mount)
    a, (r,) = mount / "a", b.load().repos
    Path(r.worktree, "a.txt").write_text("one\nTWO\n")
    (a / "a.txt").write_text("one\nnot committed\n")
    got = b.finish("done", "change two", launch)["repos"][0]
    assert got["state"] == "kept" and got["why"]
    assert (a / "a.txt").read_text() == "one\nnot committed\n"
    assert git(a, "show", "run/0123abcd:a.txt") == "one\nTWO"


@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
def test_a_run_that_did_not_end_done_keeps_its_work_on_the_branch(tmp_path, mount, outcome):
    b, _, _ = made(tmp_path, mount)
    a, (r,) = mount / "a", b.load().repos
    Path(r.worktree, "a.txt").write_text("one\nTWO\n")
    got = b.finish(outcome, "half done", launch)["repos"][0]
    assert got == {"repo": "/Workspace/a", "state": "kept", "files": 1, "why": f"the run ended {outcome}"}
    assert (a / "a.txt").read_text() == "one\ntwo\n" and git(a, "show", "run/0123abcd:a.txt") == "one\nTWO"


def test_a_branch_that_gained_nothing_is_deleted_and_an_agents_own_commit_counts(tmp_path, mount):
    b, _, _ = made(tmp_path, mount)
    a = mount / "a"
    assert b.finish("done", "nothing", launch)["repos"][0]["state"] == "unchanged"
    assert git(a, "branch", "--list", "run/*") == ""
    b2 = B.Branches(tmp_path / "run2", "run:89abcdef")
    b2.views([(str(mount), "/Workspace")], launch)
    (r,) = b2.load().repos
    Path(r.worktree, "z.txt").write_text("z\n")
    git(r.worktree, "add", "z.txt")
    git(r.worktree, "commit", "-qm", "the agent's own commit")
    assert b2.finish("done", "x", launch)["repos"][0]["state"] == "merged" and (a / "z.txt").read_text() == "z\n"


def test_runs_side_by_side_work_on_branches_side_by_side(tmp_path, mount):
    one, _, _ = made(tmp_path, mount)
    two = B.Branches(tmp_path / "run2", "run:89abcdef")
    two.views([(str(mount), "/Workspace")], launch)
    a = mount / "a"
    Path(one.load().repos[0].worktree, "one.txt").write_text("1\n")
    Path(two.load().repos[0].worktree, "two.txt").write_text("2\n")
    assert not (a / "one.txt").exists() and not (a / "two.txt").exists()  # nothing reaches the checkout before the end
    assert one.finish("done", "1", launch)["repos"][0]["state"] == "merged"
    assert two.finish("done", "2", launch)["repos"][0]["state"] == "merged"
    assert (a / "one.txt").read_text() == "1\n" and (a / "two.txt").read_text() == "2\n"


def test_without_git_in_the_policy_the_run_works_in_place(tmp_path, mount):
    b = B.Branches(tmp_path / "run", RUN)
    assert b.views([(str(mount), "/Workspace")], launch, "the policy offers no git") == ([], {})
    assert b.listing() == {"branch": "run/0123abcd", "why": "the policy offers no git", "repos": []}
    assert git(mount / "a", "branch", "--list", "run/*") == ""


def test_a_git_directory_swapped_for_a_link_is_not_bound(tmp_path, mount):
    b, _, _ = made(tmp_path, mount)
    a = mount / "a"
    (tmp_path / "elsewhere").mkdir()
    os.rename(a / ".git", tmp_path / "real-git")
    (a / ".git").symlink_to(tmp_path / "elsewhere")
    assert b.views([(str(mount), "/Workspace")], launch) == ([], {})  # the repository is no longer one: nothing bound
    got = b.finish("done", "x", launch)["repos"][0]
    assert got["state"] == "lost" and not (tmp_path / "elsewhere" / "worktrees").exists()


def test_what_a_script_prints_is_read_by_repository():
    out = "noise\n@@rhb 0 merged 3\n@@rhb 1 kept 2\nconflicts:\na.txt\n@@rhb 2 unchanged 0\n"
    assert B.said(out) == {0: (["merged", "3"], ""), 1: (["kept", "2"], "conflicts:\na.txt"), 2: (["unchanged", "0"], "")}


# ── the runner: an agent's command, and the run's end ────────────────────────────────────────────────────


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_RUNNER", "inprocess")
    hb = Handbook(tmp_path / "u.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    yield cap_api.W()
    cap_api._runners.clear()


def test_an_agents_command_sees_the_worktree_and_the_run_end_merges_it(ws, tmp_path, monkeypatch):
    root = tmp_path / "data"
    m = root / ws.owner / "workspace"
    repo(m / "a")
    monkeypatch.setenv("RHB_SANDBOX_MOUNTS", str(root / "{user}"))
    ws.set_policy("dev", actor="user", commands=["sh", "git"], mounts=[{"source": str(m), "target": "/Workspace", "rw": True}])
    runner = Runner(ws, cgroups=False)
    monkeypatch.setattr(runner, "_git", lambda pol, binds, ids, script, env, run: launch(binds, ids, script, env))
    real = ws.g.get_node
    monkeypatch.setattr(ws.g, "get_node", lambda nid: {"attrs": {"run": RUN}} if nid == "agent:1" else real(nid))
    blob = ws.g.put_blob(b"true\n")
    job = {"id": "job:00ff00ff00", "attrs": {"policy": "dev", "blob": blob, "interpreter": "sh", "args": [], "timeout": 5}}
    plain = runner._spec(job, tmp_path / "j1")
    assert plain.binds_rw == [(os.path.realpath(m), "/Workspace")]  # the person's own command: the mount as it is
    spec = runner._spec({**job, "attrs": {**job["attrs"], "agent": "agent:1"}}, tmp_path / "j2")
    (src, _), (wt, inside), (gd, gin) = spec.binds_rw
    assert (src, inside, gd) == (os.path.realpath(m), "/Workspace/a", os.path.join(os.path.realpath(m), "a", ".git"))
    assert gin.startswith("/git/a-") and {"/Workspace", inside, gin} <= set(spec.bind_ids) and Path(wt, "a.txt").exists()
    Path(wt, "a.txt").write_text("one\nTWO\n")
    got = runner.end_branches(RUN, "dev", "done", "change two\nmore words")
    assert got["repos"] == [{"repo": "/Workspace/a", "state": "merged", "files": 1, "why": ""}]
    assert (m / "a" / "a.txt").read_text() == "one\nTWO\n" and git(m / "a", "log", "-1", "--format=%s") == "change two"
    assert runner.end_branches("run:ffffffff", "dev", "done", "x") is None  # a run that made no branch
    ws.set_policy("bare", actor="user", commands=["sh"], mounts=[{"source": str(m), "target": "/Workspace", "rw": True}])
    monkeypatch.setattr(ws.g, "get_node", lambda nid: {"attrs": {"run": "run:eeeeeeee"}} if nid == "agent:2" else real(nid))
    bare = runner._spec({**job, "attrs": {**job["attrs"], "policy": "bare", "agent": "agent:2"}}, tmp_path / "j3")
    assert bare.binds_rw == [(os.path.realpath(m), "/Workspace")]
    assert "offers no git" in runner.end_branches("run:eeeeeeee", "bare", "done", "x")["why"]


@pytest.mark.parametrize("failure", ["stage", "launch", "detached"])
def test_finalization_failure_preserves_the_uncommitted_work(tmp_path, mount, failure):
    b, _, _ = made(tmp_path, mount)
    (r,) = b.load().repos
    wt = Path(r.worktree)
    (wt / "only.txt").write_text("only copy")
    finalize = launch
    if failure == "stage":
        (wt / "nested").mkdir()
        git(wt / "nested", "init", "-q")
    elif failure == "detached":
        git(wt, "checkout", "-q", "--detach")
    else:
        def finalize(*args):
            raise B.BranchError("sandbox refused")

    got = b.finish("done", "work", finalize)["repos"][0]
    assert got["state"] == "failed" and "worktree preserved" in got["why"]
    assert (wt / "only.txt").read_text() == "only copy"
    assert (mount / "a" / ".git" / "worktrees" / r.name).is_dir()
    assert git(mount / "a", "rev-parse", "run/0123abcd") == r.base
