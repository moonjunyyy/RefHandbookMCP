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


# ── egress: only the protocols the policy names, through the supervisor ──

@pytest.fixture
def upstream(monkeypatch):
    import socket as so

    from refhandbook.agents import egress

    monkeypatch.setattr(egress, "ALLOW_PRIVATE", True)
    monkeypatch.setattr(egress, "host_ok", lambda h: True)  # a loopback name, for the test only
    monkeypatch.setattr(egress, "ALLOW_PLAIN", True)  # the echo server speaks no TLS
    srv = so.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            data = c.recv(100)
            c.sendall(b"echo:" + data)
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


CLIENT = """import os, socket, sys
host, port = sys.argv[1], int(sys.argv[2])
assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:3128"
s = socket.create_connection(("127.0.0.1", 3128))
s.sendall(f"CONNECT {host}:{port} HTTP/1.1\\r\\nHost: {host}\\r\\n\\r\\n".encode())
head = s.recv(4096).decode()
print(head.splitlines()[0])
if " 200 " in head:
    s.sendall(b"ping")
    print(s.recv(100).decode())
else:
    print(head.split("\\r\\n\\r\\n", 1)[1].strip())
try:
    socket.create_connection(("127.0.0.1", port), timeout=2)
    print("direct: connected")
except OSError as e:
    print("direct: refused", e.errno)
"""


@needs_sandbox
def test_egress_reaches_only_what_the_policy_names(ws, upstream):
    ws.caps.add("egress", "local", spec={"hosts": ["localhost"], "ports": [upstream]}, actor="user")
    out = cap_api.cap("add", kind="policy", name="fetch", spec={"egress": ["local"], "commands": ["python3"]})
    assert "PROPOSED" in out and "egress local" in out  # reaching out is the user's grant
    ws.caps.approve("policy", "fetch", 1, actor="user")
    cap_api.cap("add", kind="script", name="client", spec={"policy": "fetch", "interpreter": "python3"}, body=CLIENT)
    out = cap_api.run("client", ["localhost", str(upstream)], wait=30)
    assert "HTTP/1.1 200 Connection Established" in out and "echo:ping" in out, out
    assert "direct: refused" in out  # nothing but the relay's port
    out = cap_api.run("client", ["example.com", "443"], wait=30)
    assert "403 Forbidden" in out and "in none of this policy's egress profiles (local)" in out
    logs = [j["attrs"]["egress"] for j in ws.jobs() if j["attrs"].get("egress")]
    refused = [x for x in logs if x["refused"]]
    assert len(logs) == 2 and refused[0]["requests"][0]["host"] == "example.com"
    done = [x for x in logs if not x["refused"]][0]["requests"][0]
    assert done["host"] == "localhost" and done["status"] == "done" and done["down"] == len("echo:ping")


def test_a_models_egress_profile_waits_and_the_known_ones_are_seeded(ws):
    names = {r["attrs"]["name"] for r in ws.caps.list("egress")}
    assert {"pypi", "npm", "crates", "github"} <= names
    out = cap_api.cap("add", kind="egress", name="mirror", spec={"hosts": ["mirror.example.org"]})
    assert "PROPOSED" in out and "hosts mirror.example.org" in out
    with pytest.raises(Forbidden, match="the kernel's"):
        cap_api.cap("update", kind="egress", name="pypi", spec={"hosts": ["evil.example"]})
    dev = ws.policy("dev")["attrs"]  # grants only what the administrator configured: nothing yet
    assert dev["egress"] == [] and dev["exec_work"] is False and dev["commands"] != ["*"]


def test_the_dev_policy_follows_the_servers_configuration(ws, monkeypatch):
    from refhandbook.agents.workspace import Workspace

    monkeypatch.setenv("RHB_SANDBOX_EGRESS", "pypi npm nonsense")
    monkeypatch.setenv("RHB_SANDBOX_DEV_EXEC", "1")
    dev = Workspace(ws.hb).policy("dev")["attrs"]
    assert dev["egress"] == ["npm", "pypi"] and dev["exec_work"] is True and dev["commands"] == ["*"]
    ws.set_policy("dev", actor="user", egress=["pypi"])  # the user's edit: the kernel no longer moves it
    monkeypatch.delenv("RHB_SANDBOX_EGRESS")
    assert Workspace(ws.hb).policy("dev")["attrs"]["egress"] == ["pypi"]


@needs_sandbox
def test_the_servers_layers_are_built_once_and_every_users_dev_policy_stacks_them(tmp_path, monkeypatch, capsys):
    from refhandbook import cli

    monkeypatch.setenv("RHB_RUNNER", "inprocess")
    rec = tmp_path / "recipes"
    rec.mkdir()
    (rec / "recipes.toml").write_text(
        '[base]\ndescription = "a tool"\nenv = { GREETING = "hello", PATH = "/opt/base/bin:$PATH" }\n'
        '[top]\ndescription = "on base"\nparents = ["base"]\nenv = { GREETING = "$GREETING from top" }\n')
    (rec / "base.sh").write_text("mkdir -p /opt/base/bin\nprintf '#!/bin/sh\\necho \"$GREETING\" \"$@\"\\n' "
                                 "> /opt/base/bin/greet\nchmod 755 /opt/base/bin/greet\n")
    (rec / "top.sh").write_text("mkdir -p /opt/top && echo top > /opt/top/mark\n")
    data = tmp_path / "data"
    (data / "users").mkdir(parents=True)
    hb = Handbook(data / "users" / "moon.db")
    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    ws = cap_api.W()
    assert ws.policy("dev")["attrs"]["layers"] == []  # nothing built yet
    assert cli.main(["layers", "build", "--data-dir", str(data), "--recipes", str(rec)]) == 0
    out = capsys.readouterr().out
    assert "building sys:base@1" in out and "building sys:top@1" in out and "moon: dev stacks sys:top@1" in out
    assert cli.main(["layers", "list", "--data-dir", str(data)]) == 0
    assert "sys:top@1" in capsys.readouterr().out
    cap_api._spaces.clear()
    ws = cap_api.W()
    assert ws.policy("dev")["attrs"]["layers"] == ["sys:top@1"]
    cap_api.cap("add", kind="script", name="hi", spec={"policy": "dev"}, body="greet world; cat /opt/top/mark\n")
    out = cap_api.run("hi", wait=30)
    assert "hello from top world" in out and "top" in out, out
    with pytest.raises(KernelError, match="not built on this server"):
        ws.set_policy("x", actor="user", layers=["sys:top@7"])
    for runner, _ in cap_api._runners.values():
        runner.close()
    cap_api._runners.clear()


def _client_hello(sni: str | None, ech: bool = False) -> bytes:
    ext = b""
    if sni is not None:
        name = sni.encode()
        entry = b"\x00" + len(name).to_bytes(2, "big") + name
        lst = len(entry).to_bytes(2, "big") + entry
        ext += b"\x00\x00" + len(lst).to_bytes(2, "big") + lst
    if ech:
        ext += b"\xfe\x0d\x00\x01\x00"
    body = b"\x03\x03" + bytes(32) + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00" + len(ext).to_bytes(2, "big") + ext
    hs = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + len(hs).to_bytes(2, "big") + hs


def test_a_tunnel_must_speak_tls_to_the_name_it_asked_for(monkeypatch):
    import asyncio
    import socket as so

    from refhandbook.agents import egress

    assert egress.client_hello_sni(_client_hello("pypi.org")) == ("pypi.org", "")
    assert egress.client_hello_sni(_client_hello("pypi.org", ech=True))[1] == "encrypted ClientHello"
    assert egress.client_hello_sni(_client_hello(None))[1] == "no server name"
    assert egress.client_hello_sni(b"GET / HTTP/1.1\r\n")[1] == "not TLS"
    for a in ("64:ff9b::7f00:1", "::127.0.0.1", "::ffff:10.0.0.1", "2002:7f00:1::1", "169.254.169.254", "127.0.0.1"):
        assert not egress.public(a), a
    assert egress.public("1.1.1.1") and egress.public("2606:4700::1111")

    monkeypatch.setattr(egress, "ALLOW_PRIVATE", True)
    up = so.socket()
    up.bind(("127.0.0.1", 0))
    up.listen(4)
    got = []
    threading.Thread(target=lambda: got.append(up.accept()[0].recv(4096)), daemon=True).start()
    port = up.getsockname()[1]
    sup = egress.Supervisor()
    d = sup.open("t", egress.Rules(allow=[("relay.test", (port,))], names=["t"]), egress.socket_root())
    import socket as _s
    orig = sup.loop.getaddrinfo

    async def fake(host, p, **kw):  # the test's name resolves to the local upstream
        return [(_s.AF_INET, _s.SOCK_STREAM, 6, "", ("127.0.0.1", p))]

    sup.loop.getaddrinfo = fake

    def tunnel(sni):
        c = so.socket(so.AF_UNIX)
        c.connect(str(d / "sock"))
        c.sendall(f"CONNECT relay.test:{port} HTTP/1.1\r\n\r\n".encode())
        assert b" 200 " in c.recv(100)
        c.sendall(_client_hello(sni))
        c.settimeout(5)
        try:
            return c.recv(10)
        except OSError:
            return b""
        finally:
            c.close()

    tunnel("evil.example")
    tunnel("relay.test")
    time.sleep(0.5)
    log = sup.close("t")
    whys = [r.get("why", "") for r in log["requests"]]
    assert any("the TLS server name 'evil.example' is not relay.test" in w for w in whys), log
    assert got and got[0] == _client_hello("relay.test")  # the admitted hello reached the upstream whole
    sup.loop.getaddrinfo = orig
    up.close()


def test_a_layer_may_not_set_what_makes_programs_load_something_else(ws):
    for k in ("LD_PRELOAD", "BASH_ENV", "PYTHONSTARTUP", "NODE_OPTIONS", "HTTPS_PROXY", "SSL_CERT_FILE"):
        with pytest.raises(KernelError, match=k):
            cap_api.cap("add", kind="layer", name="x", body="true\n", spec={"env": {k: "/work/x"}})


@needs_sandbox
def test_rebuilding_a_layer_rebuilds_what_stands_on_it_and_keeps_what_is_pinned(tmp_path, capsys):
    from refhandbook import cli
    from refhandbook.agents.layers import LayerStore

    rec = tmp_path / "recipes"
    rec.mkdir()
    (rec / "recipes.toml").write_text('[base]\ndescription = "b"\n[top]\ndescription = "t"\nparents = ["base"]\n')
    (rec / "base.sh").write_text("mkdir -p /opt/b\n")
    (rec / "top.sh").write_text("mkdir -p /opt/t\n")
    data = tmp_path / "data"
    (data / "users").mkdir(parents=True)
    hb = Handbook(data / "users" / "moon.db")
    args = ["layers", "build", "--data-dir", str(data), "--recipes", str(rec), "--keep", "1"]
    assert cli.main(args) == 0
    from refhandbook.agents.workspace import Workspace

    w = Workspace(hb)
    w.set_policy("mine", actor="user", layers=["sys:top@1"])  # the user's own pin
    assert cli.main([*args, "base"]) == 0
    out = capsys.readouterr().out
    assert "building sys:base@2" in out and "building sys:top@2" in out  # the stack stays whole
    names = {x.name for x in LayerStore(data / "layers").list()}
    assert {"base.v2", "top.v2", "top.v1", "base.v1"} <= names  # top@1 is pinned, and base@1 under it
    assert Workspace(Handbook(data / "users" / "moon.db")).policy("dev")["attrs"]["layers"] == ["sys:top@2"]
