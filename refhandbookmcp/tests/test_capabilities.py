"""Capability records end to end: the user's data mounted into the sandbox, layers the model builds
and a policy stacks, rule proposals as rule records, and the registry's own rules (ownership,
versions, approval of what widens a grant)."""

import threading
import time

import pytest

from refhandbook import Handbook, cap_api, research_api
from refhandbook.agents import sandbox
from refhandbook.kernel import capabilities
from refhandbook.agents.workspace import WorkspaceError
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
    ws.set_policy("builder", actor="user", commands=["sh", "mkdir", "printf", "chmod"])
    out = cap_api.cap("add", kind="layer", name="greeter", body=build,
                      spec={"policy": "builder", "description": "a hello tool"})
    assert "v1 added" in out  # a build runs under a policy already granted: nothing to ask for
    a = _wait_built(ws, "greeter")
    assert a.get("built") == 1, a.get("build_error")
    out = cap_api.cap("add", kind="policy", name="greet", spec={"layers": ["greeter"], "commands": ["sh", "hello"]})
    assert "PROPOSED" in out and "layers greeter" in out
    ws.caps.approve("policy", "greet", 1, actor="user")
    cap_api.cap("add", kind="script", name="say", spec={"policy": "greet", "requires": ["hello"]}, body="hello world\n")
    out = cap_api.run("say", wait=30)
    assert "hello from the layer world" in out, out
    # a layer's build is held to its policy: what that policy does not show, the build cannot run
    cap_api.cap("add", kind="layer", name="nochmod", body="touch /usr/local/x; chmod 755 /usr/local/x\n")
    assert "chmod" in (_wait_built(ws, "nochmod").get("build_error") or "")
    # a new build does not reach a policy until a new version of the policy pins it, which the user approves
    cap_api.cap("update", kind="layer", name="greeter", body=build.replace("from the layer", "from build two"))
    assert _wait_built(ws, "greeter")["built"] == 2
    assert "hello from the layer world" in cap_api.run("say", wait=30)
    out = cap_api.cap("update", kind="policy", name="greet", spec={"layers": ["greeter@2"]})
    assert "PROPOSED" in out and "greeter@2" in out
    # a policy with every command: no command view, the layer's binaries on the PATH
    ws.set_policy("open", actor="user", commands=["*"], layers=["greeter"])
    assert ws.policy("open")["attrs"]["layers"] == ["greeter@2"]
    cap_api.cap("add", kind="script", name="say2", spec={"policy": "open"}, body="hello again\n")
    assert "hello from build two again" in cap_api.run("say2", wait=30)


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


# ── the review's findings, one rule each ─────────────────────────────────

def test_nothing_returns_to_force_by_a_path_that_skips_the_widening_check(ws):
    cap_api.cap("add", kind="policy", name="netp", spec={"network": True})
    ws.caps.approve("policy", "netp", 1, actor="user")
    ws.caps.remove("policy", "netp", actor="user")
    with pytest.raises(KernelError, match="retired: restore it"):
        cap_api.cap("update", kind="policy", name="netp", spec={"description": "again"})
    out = cap_api.cap("restore", kind="policy", name="netp")
    assert "PROPOSED" in out and "the network" in out
    with pytest.raises(WorkspaceError, match="no policy 'netp' in force"):
        ws.policy("netp")
    rec = ws.caps.get("policy", "netp")  # the restored proposal is not retired again by a stale date
    assert rec["attrs"]["retire_at"] > time.time() + 86400


def test_a_users_edit_never_carries_the_models_waiting_version(ws):
    cap_api.cap("add", kind="policy", name="mine", spec={"commands": ["sh"], "timeout": 10})
    assert "PROPOSED" in cap_api.cap("update", kind="policy", name="mine", spec={"network": True})
    ws.set_policy("mine", actor="user", memory_mb=1024)
    p = ws.policy("mine")["attrs"]
    assert p["network"] is False and p["memory_mb"] == 1024
    assert not ws.caps.get("policy", "mine")["attrs"].get("pending")


def test_a_new_policy_is_measured_against_the_users_default(ws):
    ws.set_policy("default", actor="user", commands=["sh"], memory_mb=256)
    out = cap_api.cap("add", kind="policy", name="mine", spec={"commands": ["sh", "cat"], "memory_mb": 2048})
    assert "PROPOSED" in out and "commands cat" in out and "memory_mb" in out
    assert "v1 added" in cap_api.cap("add", kind="policy", name="small", spec={"timeout": 5})  # within the default


def test_any_port_survives_later_edits(ws):
    ws.set_policy("web", actor="user", network=True, ports="any")
    ws.set_policy("web", actor="user", description="web access")
    assert ws.policy("web")["attrs"]["ports"] == "any"


def test_a_rule_the_user_approved_is_not_the_models_to_retire(tmp_path):
    from refhandbook.kernel import capkinds, proposals, runtime  # noqa: F401

    hb = Handbook(tmp_path / "k.db")
    research_api.bind(hb)
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    g = runtime.attach(hb).g
    reg = capabilities.Registry(g, {"hb": hb})
    reg.add("rule", "my_check", spec={"phase": "check", "message": "{R}",
                                      "body": 'my_check(R) :- rs_row(Self, X, R, "H"), content(X, C), match(C, "zzz").'},
            actor="model")
    proposals.approve(g, "my_check", proposals.approval_sha(g, "my_check")[:12], actor="user")
    for op in (lambda: reg.remove("rule", "my_check", actor="model"),
               lambda: reg.deprecate("rule", "my_check", actor="model", why="x")):
        with pytest.raises(Forbidden, match="approved by the user"):
            op()
    assert g.get_rule("my_check")["state"] == "active"


def test_a_rejected_version_is_not_proposed_again(ws):
    cap_api.cap("add", kind="policy", name="wide", spec={"network": True})
    ws.caps.reject("policy", "wide", 1, actor="user")
    with pytest.raises(Forbidden, match="rejected this version"):
        cap_api.cap("restore", kind="policy", name="wide")


def test_the_default_removed_by_the_user_stays_removed(ws):
    from refhandbook.agents.workspace import Workspace

    ws.caps.remove("policy", "default", actor="user")
    rec = ws.caps.get("policy", "default")
    ws.caps.sweep(now=rec["attrs"]["retired_at"] + capabilities.RETENTION + 1, force=True)
    assert ws.caps.find("policy", "default") is None
    w = Workspace(ws.hb)
    assert w.caps.find("policy", "default") is None and "default" not in w.policies()


def test_a_card_record_commits_or_rolls_back_with_its_card(ws, monkeypatch):
    from refhandbook.kernel import capkinds

    def boom(*a, **k):
        raise capabilities.CapError("injected")

    monkeypatch.setattr(capkinds.CardKind, "report", boom)
    with pytest.raises(capabilities.CapError, match="injected"):
        ws.caps.add("card", "half", spec={"title": "Half"}, actor="model")
    assert ws.caps.find("card", "half") is None and not ws.hb.exists("half")


def test_a_layer_link_out_of_its_tree_resolves_to_nothing(tmp_path):
    from refhandbook.agents.capkinds import resolve_command

    tree = tmp_path / "tree"
    (tree / "usr/local/bin").mkdir(parents=True)
    secret = tmp_path / "secret-tool"
    secret.write_text("#!/bin/sh\n")
    secret.chmod(0o755)
    (tree / "usr/local/bin/python3").symlink_to(secret)  # absolute, to a host file
    (tree / "usr/local/bin/rel").symlink_to("../../../../secret-tool")  # relative, climbing out
    (tree / "opt").mkdir()
    (tree / "usr/local/sbin").symlink_to(tmp_path)  # a directory link out of the tree
    for name in ("python3", "rel", "secret-tool"):
        p = resolve_command(name, [str(tree)])
        assert p is None or not p.startswith(str(tmp_path)), (name, p)
    real = tree / "usr/local/bin/hello"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    (tree / "usr/local/bin/hi").symlink_to("hello")
    assert resolve_command("hi", [str(tree)]) == str(real)


def test_layer_builds_of_similar_names_are_kept_apart(ws, tmp_path):
    from refhandbook.agents.capkinds import prune_layers

    store = ws.layer_store()
    for d in ("tools.v1", "tools.v1.v1"):
        (store.root / "layers" / d / "tree").mkdir(parents=True)
        (store.root / "layers" / d / "layer.json").write_text(
            '{"name": "%s", "base": "host", "parents": [], "description": "", "created": "", "network": false}' % d)
    assert prune_layers(ws.caps, "tools") == ["tools.v1"]
    assert (store.root / "layers" / "tools.v1.v1").is_dir()
