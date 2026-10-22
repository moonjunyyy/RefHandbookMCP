"""The shared sandbox workspace: the user grants a policy once; the model adds, revises and runs
scripts within it as background jobs, with no approval per script or run."""

import os
import threading
import time

import pytest

from refhandbook import Handbook, cap_api, cli
from refhandbook.agents import sandbox
from refhandbook.agents.workspace import Runner, Workspace, WorkspaceError
from refhandbook.kernel.graph import Forbidden, KernelError

USERNS = dict((n, ok) for n, ok, _ in sandbox.check()).get("user namespaces", False)
needs_sandbox = pytest.mark.skipif(not USERNS, reason="user namespaces are not available here")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_RUNNER", "inprocess")
    hb = Handbook(tmp_path / "u.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    yield cap_api.W()
    for runner, _ in cap_api._runners.values():
        runner.close()
    cap_api._runners.clear()


def test_the_default_policy_is_the_kernels_and_a_models_widening_waits_for_the_user(ws):
    p = ws.policy("default")
    rec = ws.caps.get("policy", "default")
    assert rec["author"] == "kernel" and "sh" in p["attrs"]["commands"] and p["attrs"]["network"] is False
    out = cap_api.cap("add", kind="policy", name="wide", spec={"network": True})
    assert "v1 PROPOSED" in out and "the network" in out
    with pytest.raises(WorkspaceError, match="no policy 'wide' in force"):
        ws.policy("wide")
    narrow = cap_api.cap("add", kind="policy", name="narrow", spec={"commands": ["sh", "cat"], "timeout": 10})
    assert "v1 added" in narrow and ws.policy("narrow")["attrs"]["commands"] == ["sh", "cat"]  # narrower: at once
    with pytest.raises(Forbidden, match="only the user approves"):
        ws.caps.approve("policy", "wide", 1, actor="model")
    assert "approved" in ws.caps.approve("policy", "wide", 1, actor="user")
    assert ws.policy("wide")["attrs"]["network"] is True
    with pytest.raises(Forbidden, match="the kernel's"):
        cap_api.cap("update", kind="policy", name="default", spec={"timeout": 5})
    assert "default" in cap_api.cap("list", kind="policy")


def test_the_user_grants_on_the_server(ws, capsys):
    assert cli.main(["--db", ws.hb.path, "policy", "net", "--network", "on", "--timeout", "30",
                     "--description", "fetch data"]) == 0
    w = Workspace(Handbook(ws.hb.path))
    p = w.policy("net")
    assert w.caps.get("policy", "net")["author"] == "user" and p["attrs"]["network"] is True
    assert p["attrs"]["timeout"] == 30
    assert cli.main(["--db", ws.hb.path, "policy", "net", "--add", "no-such-tool-xyz"]) == 1
    assert "not installed on the host" in capsys.readouterr().err


def test_scripts_are_versioned_and_the_users_stay_the_users(ws):
    out = cap_api.cap("add", kind="script", name="count", body="wc -l \"$1\"\n", spec={"description": "count lines"})
    assert out.startswith("script count v1 added")
    assert "v2 in force" in cap_api.cap("update", kind="script", name="count", body="wc -w \"$1\"\n")
    assert "wc -w" in cap_api.cap("show", kind="script", name="count")
    hist = cap_api.cap("history", kind="script", name="count")
    assert "v1 " in hist and "v2 " in hist and "(in force)" in hist
    assert "v3 in force" in cap_api.cap("restore", kind="script", name="count", version=1)
    assert "wc -l" in cap_api.cap("show", kind="script", name="count")
    ws.put_script("mine", "echo user\n", actor="user")
    with pytest.raises(Forbidden, match="the user's"):
        cap_api.cap("update", kind="script", name="mine", body="echo model\n")
    with pytest.raises(KernelError, match="not a command of policy"):
        cap_api.cap("add", kind="script", name="x", body="1", spec={"interpreter": "no-such-interp"})
    with pytest.raises(KernelError, match="not a command of policy"):
        cap_api.cap("add", kind="script", name="y", body="curl x", spec={"requires": ["curl"]})


def test_deprecate_warns_then_retires_and_remove_keeps_the_history(ws):
    cap_api.cap("add", kind="script", name="old", body="echo old\n")
    cap_api.cap("add", kind="script", name="new", body="echo new\n")
    out = cap_api.cap("deprecate", kind="script", name="old", why="superseded", replaced_by="new")
    assert "deprecated" in out
    rec, _, warn = ws.caps.in_force("script", "old")
    assert warn.startswith("DEPRECATED script old: superseded; use new")
    events = ws.caps.sweep(now=rec["attrs"]["retire_at"] + 1, force=True)
    assert "script old: retired (superseded)" in events
    with pytest.raises(KernelError, match="retired"):
        cap_api.run("old")
    assert "retired" in cap_api.cap("list", kind="script", retired=True)
    assert "v2 in force" in cap_api.cap("restore", kind="script", name="old")
    assert cap_api.cap("remove", kind="script", name="new", why="tidy").startswith("script new retired")
    assert len(ws.caps.history("script", "new")) == 1


def test_a_review_renews_what_passes_and_deprecates_what_fails(ws):
    cap_api.cap("add", kind="policy", name="tools", spec={"commands": ["sh", "cat"]})
    cap_api.cap("add", kind="script", name="cat-it", body="cat \"$1\"\n", spec={"policy": "tools", "requires": ["cat"]})
    rec = ws.caps.get("script", "cat-it")
    due = rec["attrs"]["review_after"] + 1
    assert "script cat-it: renewed" in ws.caps.sweep(now=due, force=True)
    # the user narrows the policy: the script's requirement is gone, and its next review says so
    ws.set_policy("tools", actor="user", commands=["sh"])
    rec = ws.caps.get("script", "cat-it")
    events = ws.caps.sweep(now=rec["attrs"]["review_after"] + 1, force=True)
    assert any(e.startswith("script cat-it: deprecated (failed its review: not a command of policy 'tools': cat")
               for e in events)
    assert ws.g.db.execute("SELECT value FROM k_meta WHERE key = 'cap:signals'").fetchone()[0] == "1"
    # the owner answers with a new version: active again
    out = cap_api.cap("update", kind="script", name="cat-it", body="while read l; do echo $l; done < \"$1\"\n",
                      spec={"requires": []})
    assert "v2 in force" in out and ws.caps.get("script", "cat-it")["state"] == "active"


def test_the_kernels_default_repairs_itself(ws, monkeypatch):
    rec = ws.caps.get("policy", "default")
    import refhandbook.agents.capkinds as ck

    real = ck.resolve_command
    monkeypatch.setattr(ck, "resolve_command", lambda n, t: None if n == "jq" else real(n, t))
    if "jq" not in ws.policy("default")["attrs"]["commands"]:
        pytest.skip("jq is not installed here")
    events = ws.caps.sweep(now=rec["attrs"]["review_after"] + 1, force=True)
    assert any(e.startswith("policy default: repaired") for e in events)
    assert "jq" not in ws.policy("default")["attrs"]["commands"]


def test_old_tool_names_work_with_a_warning_until_their_alias_retires(ws):
    out = cap_api.sandbox_script("add", "legacy", body="echo hi\n")
    assert out.startswith("DEPRECATED sandbox_script: this call worked, but every later call must use cap(kind='script'")
    assert cap_api.sandbox_policy().startswith("DEPRECATED sandbox_policy")
    rec = ws.caps.get("alias", "sandbox-script")
    ws.caps.sweep(now=rec["attrs"]["retire_at"] + 1, force=True)
    with pytest.raises(KernelError, match="sandbox_script has been removed"):
        cap_api.sandbox_script("list")
    assert cap_api.cap("list", kind="script").count("legacy") == 1  # the new name goes on


def test_an_alias_runs_its_script_with_fixed_arguments(ws):
    cap_api.cap("add", kind="script", name="echo-all", body="echo \"$@\"\n")
    cap_api.cap("add", kind="alias", name="greet", spec={"target": "script:echo-all", "args": ["hello"]})
    assert "alias greet" in cap_api.cap("list", kind="alias")
    if USERNS:
        out = cap_api.run("greet", ["world"], wait=30)
        assert "hello world" in out


def test_files_stay_inside_the_workspace(ws, tmp_path):
    cap_api.files("write", "data/a.txt", text="1\n2\n3\n")
    assert cap_api.files("read", "data/a.txt") == "1\n2\n3\n"
    assert "file" in cap_api.files("ls", "data")
    for bad in ("../u.db", "/../../etc/passwd", "data/../../u.db"):
        with pytest.raises(WorkspaceError, match="outside the workspace"):
            cap_api.files("read", bad)
    os.symlink("/etc", ws.work / "etc-link")
    with pytest.raises(WorkspaceError, match="symlink"):
        cap_api.files("read", "etc-link/hostname")
    cap_api.files("remove", "data")
    assert not (ws.work / "data").exists()


@needs_sandbox
def test_a_script_runs_as_a_job_on_the_users_files(ws):
    cap_api.files("write", "nums.txt", text="3\n1\n2\n")
    cap_api.cap("add", kind="script", name="sum", spec={"interpreter": "python3"},
                               body="import sys\nprint(sum(int(x) for x in open(sys.argv[1])))\n"
                                    "open('/work/out.txt', 'w').write('ok')\n")
    out = cap_api.run("sum", ["/work/nums.txt"], wait=30)
    assert ": done (exit 0" in out and "--- stdout" in out and "\n6\n" in out + "\n"
    assert cap_api.files("read", "out.txt") == "ok"


@needs_sandbox
def test_a_script_calls_only_what_its_policy_shows(ws):
    cap_api.cap("add", kind="script", name="fetch", body="curl --version || echo no-curl; ls /usr/bin | wc -l\n")
    out = cap_api.run("fetch", wait=30)
    assert "no-curl" in out
    assert int(out.split("--- stdout")[1].split("\n")[2]) == len(ws.policy("default")["attrs"]["commands"])


@needs_sandbox
def test_a_long_job_runs_on_while_the_conversation_does_other_work(ws):
    cap_api.cap("add", kind="script", name="slow", body="sleep 2; echo finished\n")
    out = cap_api.run("slow", wait=0)
    jid = out.split()[0]
    assert ": queued" in out or ": running" in out
    cap_api.files("write", "meanwhile.txt", text="other work")
    out = cap_api.job("wait", jid, wait=30)
    assert ": done" in out and "finished" in out
    assert jid in cap_api.job("list")


@needs_sandbox
def test_a_job_can_be_cancelled(ws):
    cap_api.cap("add", kind="script", name="forever", body="sleep 60\n")
    jid = cap_api.run("forever", wait=0).split()[0]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with cap_api._lock:  # the runner's threads share the store's connection
            if ws.job(jid)["state"] == "running":
                break
        time.sleep(0.1)
    cap_api.job("cancel", jid)
    out = cap_api.job("wait", jid, wait=20)
    assert ": cancelled" in out


def test_a_run_longer_than_the_policy_is_refused(ws):
    cap_api.cap("add", kind="script", name="s", body="true\n")
    with pytest.raises(WorkspaceError, match=r"timeout must be in \(0, 120\]"):
        cap_api.run("s", timeout=1000)


@needs_sandbox
def test_the_runner_unit_runs_jobs_queued_by_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_RUNNER", "external")
    users = tmp_path / "users"
    users.mkdir()
    hb = Handbook(users / "moonny.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    cap_api.cap("add", kind="script", name="hi", body="echo hi from the runner\n")
    out = cap_api.run("hi", wait=0.5)
    assert ": queued" in out  # nothing runs jobs in this process
    jid = out.split()[0]
    assert cli.main(["runner", "--data-dir", str(tmp_path), "--once"]) == 0
    w = Workspace(Handbook(users / "moonny.db"))
    assert w.job(jid)["state"] == "done" and w.output(w.job(jid)) == "hi from the runner\n"


def test_a_job_whose_runner_died_is_lost(ws):
    cap_api.cap("add", kind="script", name="s", body="true\n")
    jid = ws.submit("s", [], actor="model")
    r = Runner(ws)
    j = ws.job(jid)
    ws.g.update_node(jid, actor="kernel", state="running", expect=j["version"], attrs={"lease": time.time() - 1})
    assert r.reap_lost() == 1 and ws.job(jid)["state"] == "lost"
    r.close()


@needs_sandbox
def test_through_the_server_a_waiting_run_does_not_hold_up_other_calls(tmp_path, monkeypatch):
    import asyncio

    from refhandbook import server

    monkeypatch.setenv("RHB_RUNNER", "inprocess")
    hb = Handbook(tmp_path / "s.db")
    monkeypatch.setattr(server, "_handbook", hb)
    cap_api.configure(server.handbook, server._CALLS)
    cap_api._spaces.clear()
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"cap", "run", "job", "files", "sandbox_script", "sandbox_run"} <= tools

    async def call(tool, **arguments):
        return (await server.mcp.call_tool(tool, arguments)).content[0].text

    asyncio.run(call("cap", action="add", kind="script", name="slow", body="sleep 2; echo done-slow\n"))
    done = {}

    def slow():
        done["run"] = asyncio.run(call("run", name="slow", wait=20))
        done["run_at"] = time.monotonic()

    t = threading.Thread(target=slow)
    t.start()
    time.sleep(0.5)
    asyncio.run(call("files", action="ls"))
    other_at = time.monotonic()
    t.join(30)
    assert "done-slow" in done["run"] and other_at < done["run_at"]
    for runner, _ in cap_api._runners.values():
        runner.close()
    cap_api._runners.clear()


def test_a_name_swapped_to_a_symlink_never_leads_the_host_outside(ws, tmp_path):
    """The sandbox writes the workspace while the host reads it: a job swapping a file for a symlink
    (the review's race) must never make read/write/remove act outside."""
    outside = tmp_path / "secret"
    outside.write_text("SECRET")
    (tmp_path / "outdir").mkdir()
    stop = threading.Event()

    def swapper():
        f, link, tmp = ws.work / "f", ws.work / "f.link", ws.work / "f.tmp"
        d, dlink = ws.work / "d", ws.work / "d.link"
        while not stop.is_set():
            for real, l, target in ((f, link, outside), (d, dlink, tmp_path / "outdir")):
                try:
                    if not l.is_symlink():
                        os.symlink(target, l)
                    if real.is_dir() or not real.exists():
                        real.mkdir(exist_ok=True) if real == d else real.write_text("inside")
                    os.rename(l, tmp)
                    os.rename(real, l)
                    os.rename(tmp, real)
                except OSError:
                    pass

    t = threading.Thread(target=swapper)
    t.start()
    try:
        for _ in range(3000):
            try:
                assert "SECRET" not in ws.read("f")
            except WorkspaceError:
                pass
            try:
                ws.write("d/planted", "x")
            except WorkspaceError:
                pass
    finally:
        stop.set()
        t.join()
    assert outside.read_text() == "SECRET"
    assert not (tmp_path / "outdir" / "planted").exists()


def test_a_fifo_or_device_is_refused_at_once(ws):
    os.mkfifo(ws.work / "p")
    t0 = time.monotonic()
    with pytest.raises(WorkspaceError, match="not a regular file|special"):
        ws.read("p")
    with pytest.raises(WorkspaceError):
        ws.write("p", "x")
    assert time.monotonic() - t0 < 1


def test_removing_a_symlink_removes_the_link(ws, tmp_path):
    target = tmp_path / "keep"
    target.write_text("keep")
    os.symlink(target, ws.work / "l")
    ws.remove("l")
    assert target.read_text() == "keep" and not (ws.work / "l").is_symlink()
