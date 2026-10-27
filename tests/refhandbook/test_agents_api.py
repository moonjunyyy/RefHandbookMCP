"""The agents' JSON API (/agents/api/v1): the same powers as the pages, as JSON, behind the same
sign-in; writes need the pages' header and origin."""

from __future__ import annotations

import pytest

from refhandbook import server
from refhandbook.agents import keys as K
from refhandbook.agents.presets import Presets
from refhandbook.agents.team import Team
from refhandbook.agents.workspace import Workspace

from .test_agents import keyed, pair  # noqa: F401 — fixtures
from .test_remote import BASE, accounts, built, cfg, client, key, site_token  # noqa: F401 — fixtures

V1 = "/agents/api/v1"


def call(c, method, path, json=None, uid="moon", write_header=True, origin=BASE):
    h = {"X-Auth-Token": site_token(c.key, uid)}
    if write_header:
        h["X-Requested-With"] = "fetch"
    if origin:
        h["Origin"] = origin
    return c.request(method, V1 + path, json=json, headers=h)


def grant(*routes, **kw):
    g = {"routes": [{"key": k, "model": m, "roles": r} for k, m, r in routes] or
         [{"key": "anthropic/main", "model": "claude-opus-5-5", "roles": ["lead", "worker", "verifier"]}],
         "max_agents": 2, "max_spawns": 4, "max_steps": 10}
    g.update(kw)
    return g


@pytest.fixture
def api(client, keyed):
    checked, _ = keyed
    # two keys, each with its own models (the provider's list, checked at registration)
    from refhandbook.agents import providers

    async def models_of(provider, secret, fmt, base):
        return ({"anthropic": ["claude-opus-5-5", "claude-haiku-5-5"]}.get(provider, ["qwen3-32b", "llama4"]), "ok")

    pages_check = providers.check_key
    providers.check_key = models_of
    r = call(client, "POST", "/keys", {"provider": "anthropic", "label": "main", "secret": "sk-ant-api03-abcdefghijklmnop"})
    assert r.status_code == 201, r.text
    r = call(client, "POST", "/keys", {"provider": "custom", "label": "gpu", "secret": "", "format": "openai-chat",
                                       "base_url": "https://models.example.org/v1"})
    assert r.status_code == 201, r.text
    yield client
    providers.check_key = pages_check


def test_the_api_needs_the_sign_in_and_the_pages_own_writes(client, keyed):
    r = client.get(V1 + "/me")
    assert r.status_code == 401 and r.json() == {"error": {"code": "unauthorized", "message": "sign in first"}}
    assert call(client, "GET", "/me").json() == {"uid": "moon"}
    r = call(client, "POST", "/runs", {"goal": "x", "grant": grant()}, write_header=False)
    assert r.status_code == 403 and "x-requested-with" in r.json()["error"]["message"]
    r = call(client, "POST", "/runs", {"goal": "x", "grant": grant()}, origin="https://evil.example")
    assert r.status_code == 403 and r.json()["error"]["message"] == "a request from another site"
    assert call(client, "GET", "/keys", uid="nobody").status_code == 401  # not an account here
    r = client.request("POST", V1 + "/runs", content=b"[1, 2]",
                       headers={"X-Auth-Token": site_token(client.key), "X-Requested-With": "fetch"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid"


def test_each_key_lists_its_own_models(api):
    keys = {k["ref"]: k for k in call(api, "GET", "/keys").json()}
    assert keys["anthropic/main"]["models"] == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert keys["custom/gpu"]["models"] == ["llama4", "qwen3-32b"] and keys["custom/gpu"]["format"] == "openai-chat"
    assert "secret" not in str(keys) and "sk-ant-api03-abcdefghij" not in str(keys)
    assert call(api, "GET", "/keys", uid="kim").json() == []  # one's keys are one's own
    assert call(api, "DELETE", "/keys/custom/gpu").json() == {"deleted": "custom/gpu"}
    assert call(api, "DELETE", "/keys/custom/gpu").status_code == 404
    opts = call(api, "GET", "/options").json()
    assert opts["max_routes"] == 16 and "default" in opts["policies"] and opts["roles"] == ["lead", "worker", "verifier"]


def test_a_run_takes_as_many_routes_as_it_needs(api, cfg):
    routes = [("anthropic/main", "claude-opus-5-5", ["lead"]), ("anthropic/main", "claude-haiku-5-5", ["worker"]),
              ("custom/gpu", "qwen3-32b", ["worker"]), ("custom/gpu", "llama4", ["worker"]),
              ("anthropic/main", "claude-opus-5-5", ["verifier"]), ("custom/gpu", "qwen3-32b", ["verifier"])]
    r = call(api, "POST", "/runs", {"goal": "survey", "title": "s", "grant": grant(*routes), "save_as": "survey"})
    assert r.status_code == 201, r.text
    run = r.json()["id"]
    assert r.json()["phase"] == "approved"
    assert (cfg.data_dir / "users" / "moon.db.sandbox" / "runs" / run.split(":")[1]).exists()  # the runner's marker
    d = call(api, "GET", f"/runs/{run}").json()
    # a goal with a routing table, as before flows: one team block on the route that leads
    assert d["flow"]["steps"][0]["command"] == "survey" and d["flow"]["steps"][0]["team"]
    assert d["grant"]["routes"][0]["model"] == "claude-opus-5-5" and d["approve_url"] is None
    assert d["recipe"]["flow"] == d["flow"] and d["recipe"]["input"] == "" and "routes" not in d["recipe"]["grant"]
    assert [x["id"] for x in call(api, "GET", "/runs").json()] == [run]
    assert [p["name"] for p in call(api, "GET", "/presets").json()] == ["survey"]  # kept as a preset too
    r = call(api, "POST", "/runs", {"goal": "x", "grant": grant(("openai/theirs", "gpt", ["lead"]))})
    assert r.status_code == 400 and "not a key you registered" in r.json()["error"]["message"]
    keys = {k["ref"]: k["used_by"] for k in call(api, "GET", "/keys").json()}
    assert keys == {"anthropic/main": ["survey"], "custom/gpu": []}  # which presets a key would take with it
    assert call(api, "GET", f"/runs/{run}", uid="kim").status_code == 404  # another's store
    assert call(api, "POST", f"/runs/{run}/cancel").json()["id"] == run
    t = Team(Workspace(server._user_store("moon")).g)
    assert t.g.node(run)["attrs"]["cancel"] == "cancelled by the user"
    # a run the model asked for: the API shows it and where to approve it, and cannot approve it
    asked = t.request_run("look", actor="model", proposal={"max_agents": 2})
    d = call(api, "GET", f"/runs/{asked}").json()
    assert d["phase"] == "requested" and d["approve_url"] == f"/approvals/runs/{asked}" and d["proposal"]["max_agents"] == 2


def test_presets_and_schedules(api):
    r = call(api, "PUT", "/presets/daily", {"goal": "report for {date}", "title": "daily", "grant": grant()})
    assert r.status_code == 200 and r.json()["name"] == "daily"
    r = call(api, "POST", "/presets/daily/schedules", {"cron": "0 9 * * mon-fri"})
    assert r.status_code == 201 and r.json()["enabled"] and r.json()["next_at"]
    sid = r.json()["id"]
    assert call(api, "POST", "/presets/daily/schedules", {"cron": "0 9 31 2 *"}).status_code == 400
    assert call(api, "PATCH", f"/schedules/{sid}", {"enabled": False}).json()["enabled"] is False
    assert call(api, "PATCH", f"/schedules/{sid}", {"enabled": "no"}).status_code == 400
    assert call(api, "GET", "/presets").json()[0]["schedules"][0]["id"] == sid
    r = call(api, "POST", "/presets/daily/run")
    assert r.status_code == 201 and r.json()["preset"] == "daily" and r.json()["phase"] == "approved"
    p = call(api, "POST", "/cron", {"cron": "*/15 * * * *"}).json()
    assert len(p["next"]) == 5 and p["next"][1] - p["next"][0] == 900
    assert call(api, "POST", "/cron", {"cron": "nope"}).status_code == 400
    assert call(api, "DELETE", f"/schedules/{sid}").json() == {"deleted": sid}
    assert call(api, "DELETE", "/presets/daily").json() == {"deleted": "daily"}
    assert Presets(Workspace(server._user_store("moon")).g).list() == []
    assert call(api, "PUT", "/presets/Bad Name", {"goal": "x", "grant": grant()}).status_code == 400


def test_the_workspace_read_only(api):
    ws = Workspace(server._user_store("moon"))
    ws.write("out/a.txt", "hello")
    d = call(api, "GET", "/files").json()
    assert d["kind"] == "dir" and {"name": "out", "kind": "dir", "size": 0} in d["entries"]
    assert call(api, "GET", "/files?path=out/a.txt").json() == {"path": "out/a.txt", "kind": "file", "size": 5,
                                                                 "text": "hello"}
    assert call(api, "GET", "/files?path=../../etc/passwd").status_code == 404
    assert str(ws.work) not in call(api, "GET", "/files").text  # no server paths


def test_a_flow_preset_and_a_flow_run(api):
    """A flow is blocks (each its own key, model and command) and named arrows; its routing comes from
    the blocks, so the request needs no routes; a block's key must be one the user registered."""
    flow = {"steps": [{"id": "plan", "title": "계획", "key": "anthropic/main", "model": "claude-opus-5-5",
                       "command": "plan it", "x": 10, "y": 20},
                      {"id": "do", "title": "실행", "key": "custom/gpu", "model": "qwen3-32b", "command": "do it",
                       "x": 200}],
            "edges": [{"from": "plan", "to": "do", "label": "진행"}]}
    r = call(api, "PUT", "/presets/pipeline", {"goal": "", "grant": {"max_agents": 1}, "flow": flow})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["flow"]["steps"][0] == {"id": "plan", "title": "계획", "key": "anthropic/main",
                                     "model": "claude-opus-5-5", "command": "plan it", "team": False, "x": 10.0, "y": 20.0}
    assert p["flow"]["start"] == "plan" and p["flow"]["max_visits"] == 3
    assert [(x["key"], x["model"]) for x in p["grant"]["routes"]] == [("anthropic/main", "claude-opus-5-5"),
                                                                       ("custom/gpu", "qwen3-32b")]
    assert p["grant"]["max_agents"] == 2 and p["grant"]["max_spawns"] >= 7  # raised to what the flow needs
    bad = {**flow, "steps": [*flow["steps"][:1], {**flow["steps"][1], "key": "openai/none"}]}
    r = call(api, "PUT", "/presets/pipeline", {"grant": {}, "flow": bad})
    assert r.status_code == 400 and "not a key you registered" in r.json()["error"]["message"]
    r = call(api, "POST", "/presets/pipeline/run")
    run = r.json()["id"]
    d = call(api, "GET", f"/runs/{run}").json()
    assert d["flow"]["edges"] == [{"from": "plan", "to": "do", "label": "진행"}] and d["phase"] == "approved"
    assert d["flow_path"] == [] and d["goal"].startswith("pipeline · ") and d["input"] == ""  # no input: named for the preset
    r = call(api, "POST", "/runs", {"goal": "ad hoc", "flow": flow, "save_as": "again"})
    assert r.status_code == 201 and call(api, "GET", "/presets").json()[0]["name"] == "again"
