"""Capability records end to end: the user's data mounted into the sandbox, layers the model builds
and a policy stacks, rule proposals as rule records, and the registry's own rules (ownership,
versions, approval of what widens a grant)."""

import threading
import time

import pytest

from refhandbook import Handbook, cap_api, research_api
from refhandbook.agents import sandbox
from refhandbook.kernel import capabilities
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


@pytest.fixture
def data(tmp_path, monkeypatch, ws):
    root = tmp_path / "data"
    mine = root / ws.owner / "papers"
    mine.mkdir(parents=True)
    (mine / "a.txt").write_text("from the user's data\n")
    (root / "someone-else").mkdir()
    monkeypatch.setenv("RHB_SANDBOX_MOUNT_ROOTS", str(root / "{user}"))
    return root


def test_a_mount_is_the_users_grant_under_the_servers_roots(ws, data, monkeypatch):
    src = str(data / "{user}" / "papers")
    out = cap_api.cap("add", kind="policy", name="papers", spec={"mounts": [{"source": src, "target": "/data"}]})
    assert "PROPOSED" in out and "mount" in out  # the model asks; the user decides
    with pytest.raises(KernelError, match="outside the directories"):
        ws.set_policy("x", actor="user", mounts=[{"source": str(data / "someone-else"), "target": "/data"}])
    with pytest.raises(KernelError, match="mount target"):
        ws.set_policy("x", actor="user", mounts=[{"source": src, "target": "/usr/local"}])
    monkeypatch.delenv("RHB_SANDBOX_MOUNT_ROOTS")
    with pytest.raises(KernelError, match="mounts are off on this server"):
        ws.set_policy("x", actor="user", mounts=[{"source": src, "target": "/data"}])


@needs_sandbox
def test_a_mounted_directory_is_read_only_unless_granted_rw(ws, data):
    src = str(data / "{user}" / "papers")
    ws.set_policy("papers", actor="user", mounts=[{"source": src, "target": "/data"}])
    cap_api.cap("add", kind="script", name="peek", spec={"policy": "papers"},
                body="cat /data/a.txt; echo x > /data/b.txt && echo wrote || echo refused\n")
    out = cap_api.run("peek", wait=30)
    assert "from the user's data" in out and "refused" in out
    ws.set_policy("papers", actor="user", mounts=[{"source": src, "target": "/data", "rw": True}])
    out = cap_api.run("peek", wait=30)
    assert "wrote" in out and (data / ws.owner / "papers" / "b.txt").read_text() == "x\n"


def _wait_built(ws, name, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with cap_api._lock:
            a = ws.caps.get("layer", name)["attrs"]
        if a.get("built") == a.get("version") or a.get("build_error"):
            return a
        time.sleep(0.3)
    raise AssertionError(f"layer {name} did not build")


@needs_sandbox
def test_a_layer_the_model_builds_brings_binaries_a_policy_stacks(ws):
    build = ("mkdir -p /usr/local/bin\n"
             "printf '#!/bin/sh\\necho hello from the layer \"$@\"\\n' > /usr/local/bin/hello\n"
             "chmod 755 /usr/local/bin/hello\n")
    out = cap_api.cap("add", kind="layer", name="greeter", body=build, spec={"description": "a hello tool"})
    assert "v1 added" in out  # no network: no grant to ask for
    a = _wait_built(ws, "greeter")
    assert a["built"] == 1, a.get("build_error")
    out = cap_api.cap("add", kind="policy", name="greet", spec={"layers": ["greeter"], "commands": ["sh", "hello"]})
    assert "PROPOSED" in out and "layers greeter" in out
    ws.caps.approve("policy", "greet", 1, actor="user")
    cap_api.cap("add", kind="script", name="say", spec={"policy": "greet", "requires": ["hello"]}, body="hello world\n")
    out = cap_api.run("say", wait=30)
    assert "hello from the layer world" in out, out
    # a network build is a grant
    out = cap_api.cap("add", kind="layer", name="fetcher", body="true\n", spec={"network": True})
    assert "PROPOSED" in out and "network" in out
    # a policy with every command: no command view, the layer's binaries on the PATH
    ws.set_policy("open", actor="user", commands=["*"], layers=["greeter"])
    cap_api.cap("add", kind="script", name="say2", spec={"policy": "open"}, body="hello again\n")
    assert "hello from the layer again" in cap_api.run("say2", wait=30)


def test_a_layer_still_building_cannot_be_stacked(ws, monkeypatch):
    monkeypatch.setattr(ws, "on_queue", lambda: None)  # nothing builds it
    cap_api.cap("add", kind="layer", name="slow", body="true\n")
    with pytest.raises(KernelError, match="is not built: it is still building"):
        ws.set_policy("p", actor="user", layers=["slow"])


def test_rule_proposals_are_rule_records(tmp_path):
    hb = Handbook(tmp_path / "r.db")
    research_api.bind(hb)
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    s = research_api.research_begin("geo").split()[1]
    rule = {"id": "rv_says_drops", "phase": "check", "severity": "block", "message": "{R}: says 'drops'",
            "body": 'rv_says_drops(R) :- rs_row(Self, X, R, "H"), content(X, C), match(C, "drops").'}
    out = research_api.research_review("geo", session=s, why="a gap", rules=[rule])
    assert out.startswith("DEPRECATED research_review_rules") and "PROPOSED rv_says_drops" in out
    reg = capabilities.Registry(research_api.R().k.g, {"hb": hb})
    rec = reg.get("rule", "rv_says_drops")
    assert rec["author"] == "model" and rec["attrs"]["version"] == 1
    assert hb._kernel.g.get_rule("rv_says_drops")["authority"] == "proposed"
    # the model revises it as a new version, and withdraws it
    _, msg = reg.update("rule", "rv_says_drops", spec={"message": "{R}: the word 'drops'"}, actor="model")
    assert "v2 in force" in msg and "Trial" in msg
    assert reg.remove("rule", "rv_says_drops", actor="model", why="not a gap after all").endswith(
        "(its history is kept; restore brings it back)")
    assert hb._kernel.g.get_rule("rv_says_drops")["state"] == "retired"


def test_the_registry_keeps_owners_versions_and_approvals_apart(tmp_path):
    from refhandbook.kernel import capkinds  # noqa: F401
    from refhandbook.kernel import runtime

    hb = Handbook(tmp_path / "k.db")
    reg = capabilities.Registry(runtime.attach(hb).g, {"hb": hb})
    reg.add("card", "disk-full", spec={"title": "Disk full", "condition": "ENOSPC"}, actor="user")
    with pytest.raises(Forbidden, match="the user's"):
        reg.update("card", "disk-full", spec={"title": "x"}, actor="model")
    reg.add("card", "slow-build", spec={"title": "Slow build", "condition": "build over 10 min"}, actor="model")
    assert hb.exists("slow-build")
    _, msg = reg.update("card", "slow-build", spec={"objective": "find the slow step"}, actor="model")
    assert "v2" in msg and hb.get_entry("slow-build")["objective"] == "find the slow step"
    assert [v["version"] for v in reg.history("card", "slow-build")] == [1, 2]
    reg.remove("card", "slow-build", actor="model")
    assert not hb.exists("slow-build")
    rec = reg.get("card", "slow-build")
    events = reg.sweep(now=rec["attrs"]["retired_at"] + capabilities.RETENTION + 1, force=True)
    assert "card slow-build: purged" in events and reg.find("card", "slow-build") is None
    with pytest.raises(KernelError, match="rs-\\* cards are the research package's"):
        reg.add("card", "rs-n9", spec={"title": "x"}, actor="model")
