"""The shared sandbox workspace: the user grants a policy once; the model adds, revises and runs
scripts within it as background jobs, with no approval per script or run."""

import os
import threading
import time

import pytest

from refhandbook import Handbook, cli, sandbox_api
from refhandbook.agents import sandbox
from refhandbook.agents.workspace import Runner, Workspace, WorkspaceError
from refhandbook.kernel.graph import Forbidden

USERNS = dict((n, ok) for n, ok, _ in sandbox.check()).get("user namespaces", False)
needs_sandbox = pytest.mark.skipif(not USERNS, reason="user namespaces are not available here")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_RUNNER", "inprocess")
    hb = Handbook(tmp_path / "u.db")
    sandbox_api.configure(lambda: hb, threading.RLock())
    sandbox_api._spaces.clear()
    yield sandbox_api.W()
    for runner, _ in sandbox_api._runners.values():
        runner.close()
    sandbox_api._runners.clear()


def test_the_default_policy_is_the_kernels_and_the_model_cannot_grant(ws):
    p = ws.policy("default")
    assert p["author"] == "kernel" and "sh" in p["attrs"]["commands"] and p["attrs"]["network"] is False
    with pytest.raises(Forbidden, match="the user's grant"):
        ws.set_policy("wide", actor="model", network=True)
    assert "default (by kernel)" in sandbox_api.sandbox_policy()


def test_the_user_grants_on_the_server(ws, capsys):
    assert cli.main(["--db", ws.hb.path, "policy", "net", "--network", "on", "--timeout", "30",
                     "--description", "fetch data"]) == 0
    p = Workspace(Handbook(ws.hb.path)).policy("net")
    assert p["author"] == "user" and p["attrs"]["network"] is True and p["attrs"]["timeout"] == 30
    assert cli.main(["--db", ws.hb.path, "policy", "net", "--add", "no-such-tool-xyz"]) == 1
    assert "not installed on the host" in capsys.readouterr().err


def test_scripts_are_the_models_to_write_and_the_users_stay_the_users(ws):
    out = sandbox_api.sandbox_script("add", "count", body="wc -l \"$1\"\n", description="count lines")
    assert out.startswith("script count saved")
    assert sandbox_api.sandbox_script("update", "count", body="wc -w \"$1\"\n").startswith("script count saved")
    assert "wc -w" in sandbox_api.sandbox_script("show", "count")
    ws.put_script("mine", "echo user\n", actor="user")
    with pytest.raises(Forbidden, match="the user's"):
        sandbox_api.sandbox_script("update", "mine", body="echo model\n")
    with pytest.raises(WorkspaceError, match="not a command of policy"):
        sandbox_api.sandbox_script("add", "x", body="1", interpreter="no-such-interp")


def test_files_stay_inside_the_workspace(ws, tmp_path):
    sandbox_api.sandbox_files("write", "data/a.txt", text="1\n2\n3\n")
    assert sandbox_api.sandbox_files("read", "data/a.txt") == "1\n2\n3\n"
    assert "file" in sandbox_api.sandbox_files("ls", "data")
    for bad in ("../u.db", "/../../etc/passwd", "data/../../u.db"):
        with pytest.raises(WorkspaceError, match="outside the workspace"):
            sandbox_api.sandbox_files("read", bad)
    os.symlink("/etc", ws.work / "etc-link")
    with pytest.raises(WorkspaceError, match="symlink"):
        sandbox_api.sandbox_files("read", "etc-link/hostname")
    sandbox_api.sandbox_files("remove", "data")
    assert not (ws.work / "data").exists()


@needs_sandbox
def test_a_script_runs_as_a_job_on_the_users_files(ws):
    sandbox_api.sandbox_files("write", "nums.txt", text="3\n1\n2\n")
    sandbox_api.sandbox_script("add", "sum", interpreter="python3",
                               body="import sys\nprint(sum(int(x) for x in open(sys.argv[1])))\n"
                                    "open('/work/out.txt', 'w').write('ok')\n")
    out = sandbox_api.sandbox_run("sum", ["/work/nums.txt"], wait=30)
    assert ": done (exit 0" in out and "--- stdout" in out and "\n6\n" in out + "\n"
    assert sandbox_api.sandbox_files("read", "out.txt") == "ok"


@needs_sandbox
def test_a_script_calls_only_what_its_policy_shows(ws):
    sandbox_api.sandbox_script("add", "fetch", body="curl --version || echo no-curl; ls /usr/bin | wc -l\n")
    out = sandbox_api.sandbox_run("fetch", wait=30)
    assert "no-curl" in out
    assert int(out.split("--- stdout")[1].split("\n")[2]) == len(ws.policy("default")["attrs"]["commands"])


@needs_sandbox
def test_a_long_job_runs_on_while_the_conversation_does_other_work(ws):
    sandbox_api.sandbox_script("add", "slow", body="sleep 2; echo finished\n")
    out = sandbox_api.sandbox_run("slow", wait=0)
    jid = out.split()[0]
    assert ": queued" in out or ": running" in out
    sandbox_api.sandbox_files("write", "meanwhile.txt", text="other work")
    out = sandbox_api.sandbox_job("wait", jid, wait=30)
    assert ": done" in out and "finished" in out
    assert jid in sandbox_api.sandbox_job("list")


@needs_sandbox
def test_a_job_can_be_cancelled(ws):
    sandbox_api.sandbox_script("add", "forever", body="sleep 60\n")
    jid = sandbox_api.sandbox_run("forever", wait=0).split()[0]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sandbox_api._lock:  # the runner's threads share the store's connection
            if ws.job(jid)["state"] == "running":
                break
        time.sleep(0.1)
    sandbox_api.sandbox_job("cancel", jid)
    out = sandbox_api.sandbox_job("wait", jid, wait=20)
    assert ": cancelled" in out


def test_a_run_longer_than_the_policy_is_refused(ws):
    sandbox_api.sandbox_script("add", "s", body="true\n")
    with pytest.raises(WorkspaceError, match=r"timeout must be in \(0, 120\]"):
        sandbox_api.sandbox_run("s", timeout=1000)


@needs_sandbox
def test_the_runner_unit_runs_jobs_queued_by_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_RUNNER", "external")
    users = tmp_path / "users"
    users.mkdir()
    hb = Handbook(users / "moonny.db")
    sandbox_api.configure(lambda: hb, threading.RLock())
    sandbox_api._spaces.clear()
    sandbox_api.sandbox_script("add", "hi", body="echo hi from the runner\n")
    out = sandbox_api.sandbox_run("hi", wait=0.5)
    assert ": queued" in out  # nothing runs jobs in this process
    jid = out.split()[0]
    assert cli.main(["runner", "--data-dir", str(tmp_path), "--once"]) == 0
    w = Workspace(Handbook(users / "moonny.db"))
    assert w.job(jid)["state"] == "done" and w.output(w.job(jid)) == "hi from the runner\n"


def test_a_job_whose_runner_died_is_lost(ws):
    sandbox_api.sandbox_script("add", "s", body="true\n")
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
    sandbox_api.configure(server.handbook, server._CALLS)
    sandbox_api._spaces.clear()
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"sandbox_script", "sandbox_run", "sandbox_job", "sandbox_files", "sandbox_policy"} <= tools

    async def call(tool, **arguments):
        return (await server.mcp.call_tool(tool, arguments)).content[0].text

    asyncio.run(call("sandbox_script", action="add", name="slow", body="sleep 2; echo done-slow\n"))
    done = {}

    def slow():
        done["run"] = asyncio.run(call("sandbox_run", script="slow", wait=20))
        done["run_at"] = time.monotonic()

    t = threading.Thread(target=slow)
    t.start()
    time.sleep(0.5)
    asyncio.run(call("sandbox_files", action="ls"))
    other_at = time.monotonic()
    t.join(30)
    assert "done-slow" in done["run"] and other_at < done["run_at"]
    for runner, _ in sandbox_api._runners.values():
        runner.close()
    sandbox_api._runners.clear()


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
