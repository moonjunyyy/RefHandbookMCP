"""Agents at work: sealed per-user keys (any provider, or a custom server in a standard format), the
routing policy, the crew's runs on a scripted provider (spawn, wait, finish, route fallback, budgets,
resume, cancel), presets and schedules, the agent tools, and the approval of a run the model asked for."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading

import pytest

from refhandbook.agents import crew as C
from refhandbook.agents import keys as K
from refhandbook.agents import providers as P
from refhandbook.agents.team import TeamError, check_routes, routes_for
from refhandbook.agents.workspace import Workspace
from refhandbook.kernel.graph import Forbidden
from refhandbook.store import Handbook

from .test_remote import BASE, _csrf, accounts, built, cfg, client, key, site_token  # noqa: F401 — fixtures

NOTE = re.compile(r"\[(run:[0-9a-f]+:n\d+)\]")


@pytest.fixture
def pair(tmp_path):
    K.generate(tmp_path / "agent-keys", tmp_path / "agent-keys.pub")
    return K.load_public(tmp_path / "agent-keys.pub"), K.load_private(tmp_path / "agent-keys")


@pytest.fixture
def ks(tmp_path, pair):
    return K.KeyStore(tmp_path / "agent-keys.db", public=pair[0], private=pair[1])


# ── keys ─────────────────────────────────────────────────────────────────


def test_keys_are_sealed_per_user_provider_and_endpoint(ks, tmp_path, pair):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    ks.put("moon", "custom", "lan", "", fmt="openai-chat", base_url="https://models.example.org/v1/",
           models=["qwen3", "llama4"])
    info = {k.ref: k for k in ks.list("moon")}
    assert info["anthropic/main"].format == "anthropic" and info["anthropic/main"].fingerprint == "sk-ant…mnop"
    assert info["custom/lan"].base_url == "https://models.example.org/v1" and info["custom/lan"].models == ["llama4", "qwen3"]
    assert ks.get("moon", "anthropic", "main").secret == "sk-ant-api03-abcdefghijklmnop"
    lan = ks.get("moon", "custom", "lan")
    assert (lan.secret, lan.format, lan.base_url) == ("", "openai-chat", "https://models.example.org/v1")
    assert ks.list("kim") == []
    with pytest.raises(K.KeyError_):
        ks.get("kim", "anthropic", "main")
    # the web process (public key only) can seal but not open
    web = K.KeyStore(tmp_path / "agent-keys.db", public=pair[0])
    with pytest.raises(K.KeyError_):
        web.get("moon", "anthropic", "main")
    # a row whose endpoint was rewritten (to send the key elsewhere) does not open
    db = sqlite3.connect(tmp_path / "agent-keys.db")
    with db:
        db.execute("UPDATE api_keys SET base_url = 'https://evil.example/v1' WHERE label = 'lan'")
        db.execute("UPDATE api_keys SET uid = 'kim' WHERE label = 'main'")
    db.close()
    with pytest.raises(Exception):
        ks.get("moon", "custom", "lan")
    with pytest.raises(Exception):
        ks.get("kim", "anthropic", "main")


def test_key_registration_refuses_what_it_cannot_use(ks):
    for args, kw in ((("moon", "anthropic", "main", ""), {}), (("moon", "openai", "bad label", "sk-123456789"), {}),
                     (("moon", "custom", "x", "k" * 10), {"fmt": "soap", "base_url": "https://a.example"}),
                     (("moon", "custom", "x", "k" * 10), {"fmt": "gemini", "base_url": "ftp://a.example"}),
                     (("moon", "custom", "x", "k" * 10), {"fmt": "gemini", "base_url": "https://u:p@a.example"}),
                     (("moon", "nope", "x", "k" * 10), {})):
        with pytest.raises(K.KeyError_):
            ks.put(*args, **kw)
    # a built-in provider ignores a format and base URL: its own endpoint only
    ks.put("moon", "openai", "w", "sk-proj-123456789", fmt="anthropic", base_url="https://evil.example")
    k = ks.get("moon", "openai", "w")
    assert (k.format, k.base_url) == ("openai", "")


def test_custom_endpoints_must_be_public_https_unless_listed(monkeypatch):
    async def check(url):
        await P.check_endpoint(url)

    for url in ("http://127.0.0.1:11434/v1", "https://localhost/v1", "https://10.1.2.3/v1", "https://[::1]/v1"):
        with pytest.raises(P.EndpointRefused):
            asyncio.run(check(url))
    monkeypatch.setenv("RHB_AGENT_PRIVATE_ENDPOINTS", "127.0.0.1:11434, gpu.lan")
    asyncio.run(check("http://127.0.0.1:11434/v1"))
    asyncio.run(check("http://gpu.lan/v1"))
    with pytest.raises(P.EndpointRefused):
        asyncio.run(check("http://127.0.0.1:8080/v1"))  # another port of a listed host


def test_every_format_has_an_adapter_at_its_base_url():
    assert set(P.ADAPTERS) == set(K.FORMATS)
    assert P.adapter("openai-chat", "http://gpu.lan:8000/v1").base == "http://gpu.lan:8000/v1"
    assert P.adapter("anthropic").base == P.ANTHROPIC_URL and not P.adapter("anthropic").custom


def test_the_chat_completions_adapter_round_trips_tool_calls():
    a = P.OpenAIChat("http://gpu.lan/v1")
    sent = {}

    class Http:
        async def post(self, url, json, headers):  # noqa: A002
            sent.update(url=url, body=json, headers=headers)
            import json as jsonlib  # the parameter `json` is the request body here

            from refhandbook.agents.http import Response

            return Response(200, {}, jsonlib.dumps({"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "reasoning_content": "hmm",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "note", "arguments": '{"text": "x"}'}}]}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3}}).encode())

    step = asyncio.run(a.step(Http(), "", "qwen3", "sys", C.TOOLS[:2], a.user("hi"), P.Options()))
    assert sent["url"] == "http://gpu.lan/v1/chat/completions" and "authorization" not in sent["headers"]
    assert sent["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert step.calls[0].name == "note" and step.calls[0].args == {"text": "x"}
    assert "reasoning_content" not in step.native[0] and step.usage["input"] == 12
    res = a.results([(step.calls[0], "run:1:n1", False)], "mail")
    assert res[0] == {"role": "tool", "tool_call_id": "c1", "content": "run:1:n1"} and res[1]["role"] == "user"


# ── the routing policy ───────────────────────────────────────────────────


def test_routes_name_a_key_a_model_and_roles_and_one_serves_the_lead():
    r = check_routes([{"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["lead", "verifier"]},
                      {"key": "custom/lan", "model": "qwen3", "roles": ["*"]}])
    assert r[1]["roles"] == ["lead", "worker", "verifier"]
    g = {"routes": r}
    assert routes_for(g, "lead") == [0, 1] and routes_for(g, "worker") == [1] and routes_for(g, "lead", "qwen3") == [1]
    for bad in ([], [{"key": "anthropic/main", "model": "m", "roles": ["worker"]}],
                [{"key": "nope/x", "model": "m"}], [{"key": "anthropic/main", "model": ""}]):
        with pytest.raises(TeamError):
            check_routes(bad)


# ── the crew, on a scripted provider ─────────────────────────────────────


def _turns(history):
    return sum(1 for h in history if h.get("role") == "assistant")


def _results(history):
    return [r for h in history if h.get("role") == "user" for r in h.get("results", [])]


def team_policy(agent, history, system):
    """A lead that splits the work in two, waits, and finishes with its workers' notes."""
    t = _turns(history)
    if agent["role"] == "lead":
        if t == 0:
            return {"calls": [("spawn", {"mode": "split", "parts": [{"goal": "count a"}, {"goal": "count b"}]})]}
        if t == 1:
            return {"calls": [("wait", {})]}
        notes = NOTE.findall(" ".join(r["text"] for r in _results(history)))
        return {"calls": [("finish", {"outcome": "done", "text": f"counted: {len(notes)} notes", "refs": notes})]}
    if t == 0:
        return {"calls": [("note", {"text": f"{agent['goal']}: 3", "post": True})]}
    nid = _results(history)[-1]["text"]
    return {"calls": [("finish", {"outcome": "done", "text": "3", "refs": [nid]})]}


def _grant(**kw):
    g = {"routes": [{"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["*"]}], "max_agents": 3,
         "max_spawns": 4, "max_steps": 10}
    g.update(kw)
    return g


def _crew(tmp_path, ks, policy, adapter_for=None):
    (tmp_path / "users").mkdir(exist_ok=True)
    hb = Handbook(tmp_path / "users" / "moon.db")
    ws = Workspace(hb)
    fake = P.Fake(policy)
    return C.Crew(ws, threading.RLock(), ks, adapter_for=adapter_for or (lambda k: fake))


def _start(crew, goal="count things", **grant):
    run = crew.team.request_run(goal, actor="user")
    crew.team.approve(run, _grant(**grant), actor="user")
    C.mark(crew.ws, run)
    return run


async def _drive(crew, run, ticks=400):
    try:
        for _ in range(ticks):
            await crew.tick()
            # the runner never leaves a write transaction open between steps: another process (the
            # handbook's pages and tools) must be able to write the store at any time
            assert not crew.g.db.in_transaction
            if crew.g.node(run)["state"] == "closed" and not crew.tasks:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"run did not close: {crew.team.tree(run)}")
    finally:
        await asyncio.gather(*crew.tasks.values(), return_exceptions=True)
        await crew.http.aclose()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(C, "POLL", 0.02)
    monkeypatch.setattr(C, "JOB_POLL", 0.02)


def test_a_run_splits_waits_and_returns_the_workers_notes(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, team_policy)
    run = _start(crew)
    asyncio.run(_drive(crew, run))
    t = crew.team
    assert crew.g.node(run)["attrs"]["phase"] == "done"
    res = t.result(run)
    assert res["attrs"]["outcome"] == "done" and res["content"] == "counted: 2 notes"
    assert {n["content"] for n in t.carried(res["id"])} == {"count a: 3", "count b: 3"}
    tree = t.tree(run)
    assert len(tree) == 1 and tree[0]["role"] == "lead" and len(tree[0]["children"]) == 2
    assert all(c["status"] == "done" for c in tree[0]["children"])
    assert t.run_usage(run)["output"] == 10 * 7  # 3 lead turns, 2 per worker
    assert not (crew.ws.base / "runs" / run.split(":")[1]).exists()  # the marker went with the run
    lines = C.Transcript(C.run_dir(crew.ws, run) / "transcripts" / "a1.jsonl").lines()
    assert [x["kind"] for x in lines] == ["user", "turn", "results", "turn", "results", "turn", "results"]
    assert "You lead the run" in lines[0]["entries"][0]["text"]


def test_a_refused_key_moves_the_agent_to_the_next_route(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    ks.put("moon", "custom", "lan", "", fmt="openai-chat", base_url="https://models.example.org/v1")

    class Refused(P.Adapter):
        name = "anthropic"

        def user(self, text):
            return [{"role": "user", "text": text}]

        async def step(self, *a, **k):
            raise P.ProviderError("anthropic 401: invalid x-api-key sk-ant-api03-abcdefghijklmnop", status=401, auth=True)

    fake = P.Fake(lambda agent, history, system: {"calls": [("finish", {"outcome": "done", "text": "ok"})]})
    crew = _crew(tmp_path, ks, None, adapter_for=lambda k: Refused() if k.provider == "anthropic" else fake)
    crew_check = P.check_endpoint

    async def public(url):  # the custom endpoint is a name of the test, not a real address
        return None

    P.check_endpoint = public
    try:
        run = _start(crew, routes=[{"key": "gemini/none", "model": "gemini-x", "roles": ["lead"]},
                                   {"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["lead"]},
                                   {"key": "custom/lan", "model": "qwen3", "roles": ["lead"]}])
        asyncio.run(_drive(crew, run))
    finally:
        P.check_endpoint = crew_check
    lead = crew.g.node(crew.team.root(run))["attrs"]
    assert (lead["provider"], lead["key"], lead["model"]) == ("custom", "lan", "qwen3")
    assert "sk-ant-api03" not in lead["last_switch"] and "[key]" in lead["last_switch"]
    assert "gemini" not in [k.provider for k in ks.list("moon")]
    assert ks.info("moon", "anthropic", "main").status == "rejected"
    assert crew.team.result(run)["content"] == "ok" and crew.g.node(run)["attrs"]["phase"] == "done"


def test_with_no_route_left_the_run_fails_with_the_reason(tmp_path, ks):
    crew = _crew(tmp_path, ks, team_policy)
    run = _start(crew, routes=[{"key": "openai/none", "model": "gpt-x", "roles": ["*"]}])
    asyncio.run(_drive(crew, run))
    a = crew.g.node(run)["attrs"]
    assert a["phase"] == "failed" and "no route left" in a["error"] and "openai/none" in a["error"]


def test_the_step_budget_ends_an_agent_that_never_finishes(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    seen = []

    def chatty(agent, history, system):
        seen.append(_results(history)[-1]["text"] if _results(history) else "")
        return {"calls": [("recall", {"query": "anything"})]}

    crew = _crew(tmp_path, ks, chatty)
    run = _start(crew, max_steps=5)
    asyncio.run(_drive(crew, run))
    assert crew.g.node(run)["attrs"]["phase"] == "failed"
    assert "5 model turns" in crew.team.result(run)["content"]
    assert len(seen) == 5


def test_plain_text_answers_are_nudged_then_taken_as_the_exit(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, lambda agent, history, system: {"text": "the answer is 42"})
    run = _start(crew)
    asyncio.run(_drive(crew, run))
    assert crew.team.result(run)["content"] == "the answer is 42"
    assert crew.g.node(crew.team.root(run))["attrs"]["steps"] == C.NUDGES + 1


def test_a_lead_cannot_finish_before_reading_its_children(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    refusals = []

    def hasty(agent, history, system):
        t = _turns(history)
        if agent["role"] == "worker":
            return {"calls": [("finish", {"outcome": "done", "text": "w"})]}
        if t == 0:
            return {"calls": [("spawn", {"mode": "fresh", "role": "worker", "goal": "w"})]}
        res = _results(history)
        if res and "REFUSED" in res[-1]["text"]:
            refusals.append(res[-1]["text"])
            return {"calls": [("wait", {})]}
        if t >= 3:
            return {"calls": [("finish", {"outcome": "done", "text": "after reading"})]}
        return {"calls": [("finish", {"outcome": "done", "text": "too soon"})]}

    crew = _crew(tmp_path, ks, hasty)
    run = _start(crew)
    asyncio.run(_drive(crew, run))
    # refused while the child is open (the kernel), or done but its result unread (the agents package)
    assert refusals and ("still open" in refusals[0] or "unread" in refusals[0])
    assert crew.team.result(run)["content"] == "after reading"


def test_the_web_process_can_write_while_a_run_is_going(tmp_path, ks):
    """The runner and the handbook's pages are two processes on one store: opening agents, queueing
    spawns and numbering notes must leave no write lock behind."""
    from refhandbook.agents.team import Team

    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, team_policy)
    run = _start(crew)
    with crew.lock:
        root = crew.team.open_agent(run, role="lead", goal="g", mode="root", actor="kernel")
        crew.team.queue_spawn(run, root, {"role": "worker", "goal": "w"})
        crew.team.artifact(run, root, "a.txt", "0" * 64, 1)
    assert not crew.g.db.in_transaction
    other = Handbook(tmp_path / "users" / "moon.db")  # another connection, as the web process has
    other.db.execute("PRAGMA busy_timeout = 200")
    t = Team(Workspace(other).g)
    t.request_run("from the page", actor="user")  # fails "database is locked" if the runner held it


def test_a_killed_runner_resumes_without_replaying_tool_calls(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    seen = []

    def resumed(agent, history, system):
        seen.append(_results(history))
        return {"calls": [("finish", {"outcome": "done", "text": "resumed"})]}

    crew = _crew(tmp_path, ks, resumed)
    run = _start(crew)
    with crew.lock:
        root = crew.team.open_agent(run, role="lead", goal="count things", mode="root", actor="kernel")
    tr = C.Transcript(C.run_dir(crew.ws, run) / "transcripts" / "a1.jsonl")
    tr.append(0, "user", [{"role": "user", "text": "brief"}])
    tr.append(0, "turn", [{"role": "assistant", "text": "", "calls": []}],
              [P.ToolCall("c9", "sh", {"cmd": "rm -rf build"})])
    asyncio.run(_drive(crew, run))
    assert seen[0][-1]["id"] == "c9" and seen[0][-1]["error"] and "not re-run" in seen[0][-1]["text"]
    assert crew.team.result(run)["content"] == "resumed" and root


def test_cancelling_a_run_stops_its_agents(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")

    def forever(agent, history, system):
        if agent["role"] == "lead" and _turns(history) == 0:
            return {"calls": [("spawn", {"mode": "fresh", "role": "worker", "goal": "spin"})]}
        return {"calls": [("wait", {})] if agent["role"] == "lead" else [("recall", {"query": "x"})]}

    crew = _crew(tmp_path, ks, forever)
    run = _start(crew, max_steps=500)

    async def go():
        for _ in range(30):
            await crew.tick()
            await asyncio.sleep(0.01)
        with crew.lock:
            crew.team.request_cancel(run, "enough", by="user")
        await _drive(crew, run)

    asyncio.run(go())
    assert crew.g.node(run)["attrs"]["phase"] == "cancelled"
    assert all(a["state"] == "closed" for a in crew.team.agents(run))


def test_a_clone_continues_from_its_parents_transcript(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    clone_saw = []

    def cloning(agent, history, system):
        t = _turns(history)
        if agent.get("variant"):
            clone_saw.append(_results(history)[-1]["text"])
            return {"calls": [("finish", {"outcome": "done", "text": agent["variant"]})]}
        if t == 0:
            return {"calls": [("note", {"text": "base fact", "pin": True})]}
        if t == 1:
            return {"calls": [("spawn", {"mode": "clone", "n": 2, "variants": ["try A", "try B"]})]}
        if t == 2:
            return {"calls": [("wait", {})]}
        return {"calls": [("finish", {"outcome": "done", "text": "picked"})]}

    crew = _crew(tmp_path, ks, cloning)
    run = _start(crew)
    asyncio.run(_drive(crew, run))
    assert sorted(clone_saw) == sorted([f"You are the clone {run}:a2, not the agent that spawned you. Continue the task "
                                        "on your own with this variant: try A; finish when done.",
                                        f"You are the clone {run}:a3, not the agent that spawned you. Continue the task "
                                        "on your own with this variant: try B; finish when done."])
    held = [n["content"] for n, _ in crew.team.held(f"{run}:a2")]
    assert held == ["base fact"]


# ── the agent tools ──────────────────────────────────────────────────────


def test_the_model_asks_for_a_run_and_only_the_user_approves_it(tmp_path, ks, monkeypatch):
    from refhandbook import agents_api

    monkeypatch.setenv("RHB_PUBLIC_URL", "https://www.example.org")
    (tmp_path / "users").mkdir()
    hb = Handbook(tmp_path / "users" / "moon.db")
    agents_api.configure(lambda: hb, threading.RLock())
    out = agents_api.agent_run("request", goal="survey the logs", suggest={"max_agents": 2, "roles": {"worker": "m"},
                                                                          "evil": 1})
    run = re.search(r"run (run:[0-9a-f]+)", out).group(1)
    assert f"https://www.example.org/approvals/runs/{run}" in out
    t = agents_api._team()
    assert t.g.node(run)["attrs"]["proposal"] == {"max_agents": 2, "roles": {"worker": "m"}}
    with pytest.raises(Forbidden):
        t.approve(run, _grant(), actor="model")
    assert "waiting for the user's approval" in agents_api.agent_run("status", run=run)
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    listed = agents_api.agent_keys()
    assert "anthropic/main" in listed and "sk-ant-api03-abcdefghijklmnop" not in listed
    agents_api.agent_run("cancel", run=run, why="not needed")
    assert t.g.node(run)["attrs"]["phase"] == "cancelled" and t.g.node(run)["state"] == "closed"


# ── the pages ────────────────────────────────────────────────────────────


@pytest.fixture
def keyed(monkeypatch, tmp_path, pair):

    K.generate(tmp_path / "k", tmp_path / "k.pub")
    monkeypatch.setenv("RHB_AGENT_KEYS_PUB", str(tmp_path / "k.pub"))
    checked = []

    async def fake_check(provider, secret, fmt, base):
        checked.append((provider, fmt, base))
        if secret == "sk-refused-0000":
            raise K.KeyError_("제공자가 키를 거부했습니다 (401)")
        return ["claude-opus-5-5", "claude-haiku-5-5"], "ok"

    monkeypatch.setattr(P, "check_key", fake_check)
    return checked, K.load_private(tmp_path / "k")


def test_an_agents_sh_runs_in_the_sandbox_in_its_runs_directory(tmp_path, ks, monkeypatch):
    from refhandbook.agents.workspace import Runner

    monkeypatch.setenv("RHB_CGROUPS", "0")
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    out = []

    def shell(agent, history, system):
        t = _turns(history)
        if t == 0:
            return {"calls": [("sh", {"cmd": "echo hi > a.txt; pwd; cat a.txt; ls /work/runs"})]}
        if t == 1:
            out.append(_results(history)[-1]["text"])
            return {"calls": [("read", {"path": "a.txt"})]}
        out.append(_results(history)[-1]["text"])
        return {"calls": [("finish", {"outcome": "done", "text": "ok"})]}

    crew = _crew(tmp_path, ks, shell)
    crew.runner = Runner(crew.ws, lock=crew.lock)
    run = _start(crew)
    try:
        asyncio.run(_drive(crew, run))
    finally:
        crew.runner.close()
    hexid = run.split(":")[1]
    assert out[0].startswith("done, exit 0") and f"/work/runs/{hexid}\nhi\n{hexid}" in out[0], out
    assert out[1] == "hi"
    assert (crew.ws.work / "runs" / hexid / "a.txt").read_text() == "hi\n"


# ── the HTTP client and what the installed code may import ───────────────


def test_the_http_client_returns_every_status_and_follows_no_redirect():
    import http.server
    import socket

    from refhandbook.agents.http import Client, HttpError

    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["content-length"]))
            seen.append((self.path, self.headers.get("x-api-key"), json.loads(body)))
            if self.path == "/moved":
                self.send_response(302)
                self.send_header("location", "http://elsewhere.example/steal")
                self.end_headers()
                return
            code = 429 if self.path == "/busy" else 200
            self.send_response(code)
            self.send_header("retry-after", "3")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": self.path}).encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    async def go():
        async with Client(timeout=5) as c:
            r = await c.post(base + "/v1", json={"q": "한"}, headers={"x-api-key": "k"})
            busy = await c.post(base + "/busy", json={})
            moved = await c.post(base + "/moved", json={}, headers={"x-api-key": "k"})
            with socket.socket() as s:  # a port nobody listens on
                s.bind(("127.0.0.1", 0))
                dead = s.getsockname()[1]
            with pytest.raises(HttpError):
                await c.get(f"http://127.0.0.1:{dead}/")
            return r, busy, moved

    try:
        r, busy, moved = asyncio.run(go())
    finally:
        srv.shutdown()
    assert r.status_code == 200 and r.json() == {"ok": "/v1"} and seen[0] == ("/v1", "k", {"q": "한"})
    assert busy.status_code == 429 and busy.headers["retry-after"] == "3"
    assert moved.status_code == 302 and len(seen) == 3  # the key went nowhere else


def test_the_installed_code_imports_without_the_dev_packages():
    """The server installs with `uv sync --no-dev`: no module may need pytest or httpx (a dev
    dependency here, absent on the server)."""
    import pathlib
    import subprocess
    import sys

    src = pathlib.Path(__file__).resolve().parents[2] / "src"
    mods = sorted(".".join(p.relative_to(src).with_suffix("").parts).removesuffix(".__init__")
                  for p in src.rglob("*.py") if not p.name.startswith("._")
                  and not {"__pycache__", "recipes"} & set(p.parts))  # recipes are scripts the sandbox runs
    code = ("import sys, importlib\n"
            "for dev in ('httpx', 'pytest'): sys.modules[dev] = None\n"
            f"for m in {mods!r}:\n"
            "    if m.endswith('__main__'): continue\n"
            "    importlib.import_module(m)\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=src)
    assert r.returncode == 0, r.stderr[-2000:]


# ── presets and schedules ────────────────────────────────────────────────

import datetime as dt  # noqa: E402

from refhandbook.agents import cron  # noqa: E402
from refhandbook.agents.presets import Presets  # noqa: E402


def test_cron_fires_as_cron_does():
    t = dt.datetime(2026, 10, 24, 10, 30)  # a Saturday
    assert cron.parse("0 9 * * mon-fri").next_after(t) == dt.datetime(2026, 10, 26, 9, 0)
    assert cron.parse("*/15 * * * *").next_after(t) == dt.datetime(2026, 10, 24, 10, 45)
    assert cron.parse("30 10 * * *").next_after(t) == dt.datetime(2026, 10, 25, 10, 30)  # strictly after
    assert cron.parse("@monthly").next_after(t) == dt.datetime(2026, 11, 1, 0, 0)
    assert cron.parse("0 12 29 2 *").next_after(t) == dt.datetime(2028, 2, 29, 12, 0)
    # day-of-month and day-of-week both given: either day fires
    assert cron.parse("0 0 1 * sun").next_after(t) == dt.datetime(2026, 10, 25, 0, 0)
    assert cron.parse("0 0 * * 7").next_after(t) == dt.datetime(2026, 10, 25, 0, 0)  # 7 is Sunday too
    for bad in ("0 0 31 2 *", "60 * * * *", "* * *", "0 9 * * xyz", "*/0 * * * *"):
        with pytest.raises(cron.CronError):
            cron.parse(bad)


def _presets(tmp_path):
    (tmp_path / "users").mkdir(exist_ok=True)
    ws = Workspace(Handbook(tmp_path / "users" / "moon.db"))
    return Presets(ws.g, C.schedules_marker(ws)), ws


def test_a_schedule_fires_its_preset_once_per_time_and_not_over_a_running_one(tmp_path):
    ps, ws = _presets(tmp_path)
    with pytest.raises(TeamError):
        ps.save("daily", "x", {"routes": []})  # checked as a grant is
    with pytest.raises(TeamError):
        ps.save("daily", "x", _grant(), actor="model")  # the user's only
    ps.save("daily", "report for {date}", _grant(), title="daily report")
    t0 = dt.datetime(2026, 10, 24, 8, 59)
    s = ps.schedule("daily", "0 9 * * *", now=t0)
    assert C.schedules_marker(ws).exists()
    assert ps.due(t0) == []  # not yet
    runs = ps.due(dt.datetime(2026, 10, 24, 9, 0, 5))
    assert len(runs) == 1
    r = ws.g.node(runs[0])
    assert r["content"] == "report for 2026-10-24" and r["attrs"]["phase"] == "approved"
    assert r["attrs"]["preset"] == "daily" and r["attrs"]["schedule"] == s["id"] and r["origin"] == "user"
    assert ps.due(dt.datetime(2026, 10, 24, 9, 0, 30)) == []  # once
    # the next day, the first run still going: skipped, and said so
    assert ps.due(dt.datetime(2026, 10, 25, 9, 0)) == []
    a = ws.g.node(s["id"])["attrs"]
    assert a["skipped"] == 1 and "still running" in a["last_note"]
    # after a long stop it fires once, then on time
    Team = __import__("refhandbook.agents.team", fromlist=["Team"]).Team
    Team(ws.g).cancel_run(runs[0], "done with it", actor="user")
    assert len(ps.due(dt.datetime(2026, 10, 30, 12, 0))) == 1
    assert ws.g.node(s["id"])["attrs"]["next_at"] == dt.datetime(2026, 10, 31, 9, 0).timestamp()
    # off: nothing fires, and the marker goes when no schedule is on
    ps.set_enabled(s["id"], False)
    assert not C.schedules_marker(ws).exists() and ps.due(dt.datetime(2026, 11, 5, 9, 0)) == []
    with pytest.raises(TeamError):
        ps.set_enabled(s["id"], True, actor="model")
    ps.delete("daily")
    assert ps.schedules() == [] and ps.list() == []


def test_the_runner_fires_a_due_schedule_and_runs_it(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, lambda agent, history, system: {"calls": [("finish", {"outcome": "done", "text": "ok"})]})
    crew.presets.save("ping", "say ok", _grant())
    s = crew.presets.schedule("ping", "* * * * *", now=dt.datetime.now() - dt.timedelta(minutes=5))

    async def go():
        await crew.tick()
        run = crew.g.node(s["id"])["attrs"]["last_run"]
        await _drive(crew, run)
        return run

    run = asyncio.run(go())
    assert crew.team.result(run)["content"] == "ok" and crew.g.node(run)["attrs"]["phase"] == "done"




def test_a_run_the_model_asked_for_is_approved_on_the_approval_page(client, keyed, cfg):
    """The approvals stay server pages: a run the model asked for gets its grant there (prefilled from
    a preset when it asked from one); its own page is the pages app's."""
    from refhandbook import agents_api, server
    from refhandbook.agents.presets import Presets
    from refhandbook.agents.team import Team

    c, tok = client, {"X-Auth-Token": site_token(client.key), "Origin": BASE}
    ws = Workspace(server._user_store("moon"))
    ks = K.KeyStore.for_web(cfg.data_dir)
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop", models=["claude-opus-5-5", "claude-haiku-5-5"])
    ks.put("moon", "custom", "gpu", "", fmt="openai-chat", base_url="https://models.example.org/v1", models=["qwen3"])
    routes = [{"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["lead"]}] + [
        {"key": "custom/gpu", "model": "qwen3", "roles": ["worker"]}] * 5
    Presets(ws.g).save("weekly", "summarize the week", {**_grant(), "routes": routes})
    agents_api.configure(lambda: server._user_store("moon"), server._CALLS)
    out = agents_api.agent_run("request", preset="weekly")
    asked = re.search(r"run (run:[0-9a-f]+)", out).group(1)
    assert f"/approvals/runs/{asked}" in out
    page = c.get(f"/approvals/runs/{asked}", headers=tok).text
    assert "summarize the week" in page and page.count("name=route") >= 6 * 5  # six routes drawn, not four
    assert "list='models-custom/gpu'" in page and "<datalist id='models-custom/gpu'><option value='qwen3'>" in page
    f = {"csrf": _csrf(page), "route0_key": "anthropic/main", "route0_model": "claude-opus-5-5", "route0_lead": "on",
         **{k: v for i in range(1, 6) for k, v in ((f"route{i}_key", "custom/gpu"), (f"route{i}_model", "qwen3"),
                                                     (f"route{i}_worker", "on"))},
         "max_agents": "2", "max_spawns": "4", "max_depth": "1", "max_steps": "10", "max_tokens": "0",
         "context": "trim", "handoff": "digest", "retention": "verified", "policy": "default", "effort": ""}
    r = c.post(f"/approvals/runs/{asked}/approve", data=f, headers=tok, follow_redirects=False)
    assert r.headers["location"].startswith(f"/agents/runs/{asked}")
    t = Team(ws.g)
    assert len(t.grant(asked)["routes"]) == 6 and t.g.node(asked)["attrs"]["phase"] == "approved"
    # approved: nothing to approve any more, the page sends to the run's own
    r = c.get(f"/approvals/runs/{asked}", headers=tok, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/agents/runs/{asked}"
    # another one, rejected
    other = t.request_run("no", actor="model")
    r = c.post(f"/approvals/runs/{other}/reject", data={"csrf": _csrf(page)}, headers=tok, follow_redirects=False)
    assert "ok=" in r.headers["location"] and t.g.node(other)["attrs"]["phase"] == "cancelled"
    r = c.post(f"/approvals/runs/{other}/approve", data=f, headers={**tok, "Origin": "https://evil.example"},
               follow_redirects=False)
    assert r.status_code == 403
    # until the pages app is published, /agents/ points to the approvals
    assert c.get("/agents/", headers=tok, follow_redirects=False).headers["location"] == "/approvals"


def test_no_approval_page_tells_how_the_site_is_built(client, keyed):
    from tests.portal.test_app import BACKEND_WORDS

    from refhandbook import server
    from refhandbook.agents.team import Team

    c, tok = client, {"X-Auth-Token": site_token(client.key)}
    asked = Team(Workspace(server._user_store("moon")).g).request_run("look", actor="model")
    for path in ("/approvals", f"/approvals/runs/{asked}"):
        page = c.get(path, headers=tok).text
        found = BACKEND_WORDS.search(page)
        assert not found, (path, found and page[max(0, found.start() - 80):found.end() + 40])


# ── flows ────────────────────────────────────────────────────────────────

from refhandbook.agents import flows  # noqa: E402

DIAMOND = {"steps": [{"id": "a", "title": "A", "role": "worker", "goal": "count a"},
                     {"id": "b", "title": "B", "role": "worker", "goal": "count b"},
                     {"id": "c", "title": "C", "role": "worker", "goal": "add them up"}],
           "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}]}


def test_a_flow_is_checked_against_itself_and_the_grant():
    g = {"routes": [{"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["lead", "worker"]},
                    {"key": "anthropic/main", "model": "claude-haiku-5-5", "roles": ["worker"]}]}
    f = flows.check(DIAMOND, g)
    assert flows.order(f["steps"], f["edges"]) == ["a", "b", "c"] and flows.sinks(f) == ["c"]
    assert flows.fit({"max_agents": 1, "max_spawns": 1, "max_depth": 0}, f) == \
        {"max_agents": 2, "max_spawns": 4, "max_depth": 1}
    for bad, why in (({"steps": []}, "at least one step"),
                     ({**DIAMOND, "edges": DIAMOND["edges"] + [{"from": "c", "to": "a"}]}, "circle"),
                     ({**DIAMOND, "edges": [{"from": "a", "to": "zz"}]}, "not in the flow"),
                     ({"steps": [{"id": "a", "role": "verifier", "goal": "x"}]}, "no route of the grant runs a verifier"),
                     ({"steps": [{"id": "a", "role": "worker", "model": "gpt-9", "goal": "x"}]}, "its models: claude"),
                     ({"steps": [{"id": "A B", "goal": "x"}]}, "unique id"),
                     ({"steps": [{"id": "a", "goal": ""}]}, "a goal")):
        with pytest.raises(TeamError, match=why):
            flows.check(bad, g)


def flow_policy(fail=()):
    def policy(agent, history, system):
        goal = agent["goal"]
        if any(goal.startswith(x) for x in fail):
            return {"calls": [("finish", {"outcome": "failed", "text": "could not"})]}
        if _turns(history) == 0:
            return {"calls": [("note", {"text": f"{goal.splitlines()[0]}: 3"})]}
        return {"calls": [("finish", {"outcome": "done", "text": f"did: {goal}", "refs": [_results(history)[-1]["text"]]})]}
    return policy


def test_a_flow_runs_each_step_after_the_ones_before_it(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, flow_policy())
    run = crew.team.begin("count and add", _grant(max_agents=2), flow=DIAMOND)
    C.mark(crew.ws, run)
    asyncio.run(_drive(crew, run))
    t = crew.team
    root = crew.g.node(t.root(run))["attrs"]
    placed = root["flow_agents"]
    c = crew.g.node(placed["c"])
    assert "From step 'A' (done): did: count a" in c["content"] and "From step 'B' (done)" in c["content"]
    assert {n["content"] for n, _ in t.held(placed["c"])} >= {"count a: 3", "count b: 3"}  # the notes came along
    assert c["attrs"]["created_at"] >= max(crew.g.node(placed[x])["attrs"]["ended"] for x in "ab")
    res = t.result(run)
    assert res["attrs"]["outcome"] == "done" and res["content"].index("## A") < res["content"].index("## C")
    assert crew.g.node(run)["attrs"]["phase"] == "done"
    assert crew.g.node(placed["a"])["attrs"]["variant"] == "A"  # each step agent says which step it is


def test_a_failed_step_skips_the_ones_after_it(tmp_path, ks):
    ks.put("moon", "anthropic", "main", "sk-ant-api03-abcdefghijklmnop")
    crew = _crew(tmp_path, ks, flow_policy(fail=("count a",)))
    run = crew.team.begin("count and add", _grant(), flow=DIAMOND)
    C.mark(crew.ws, run)
    asyncio.run(_drive(crew, run))
    res = crew.team.result(run)
    assert res["attrs"]["outcome"] == "partial" and "## C (skipped: after A did not finish)" in res["content"]
    assert "c" not in crew.g.node(crew.team.root(run))["attrs"]["flow_agents"]
