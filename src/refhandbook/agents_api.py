"""The agent tools: `agent_run` (ask for a run of agents, follow it, read its result, cancel it) and
`agent_keys` (which API keys the user registered, without key material). Plain functions, like
cap_api: the MCP server registers them.

A tool call is the model's. It can ask for a run, never approve one: `request` opens the run as
`requested` and returns the approval page's address, where the user picks the keys and models (the
routing), the limits and the pruning, and approves it. The runner unit does the work.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from .agents.keys import KeyStore
from .agents.team import ROLES, Team, TeamError, render_note
from .store import Handbook

_resolve: Callable[[], Handbook] | None = None
_lock: threading.RLock = threading.RLock()


def configure(resolve: Callable[[], Handbook], lock: threading.RLock) -> None:
    global _resolve, _lock
    _resolve, _lock = resolve, lock


def _team() -> Team:
    from .kernel import runtime

    if _resolve is None:
        raise TeamError("the agent tools are not configured")
    return Team(runtime.attach(_resolve()).g)


def owner(hb: Handbook) -> tuple[str, Path]:
    """The store's user and the data directory its keys live in: users/<uid>.db on a remote server
    (the keys beside users/), else the local account and the store's directory."""
    import getpass

    p = Path(str(hb.path))
    if p.parent.name == "users":
        return p.stem, p.parent.parent
    return getpass.getuser(), p.parent


def keystore(data_dir: Path) -> KeyStore:
    return KeyStore(data_dir / "agent-keys.db")


def approval_url(run: str) -> str:
    return f"{os.environ.get('RHB_PUBLIC_URL', '').rstrip('/')}/agents/runs/{run}"


def _usage(u: dict[str, int]) -> str:
    return f"{u.get('input', 0)} in / {u.get('output', 0)} out" + (f" ({u['cache_read']} cached)" if u.get("cache_read") else "")


def _tree(nodes: list[dict[str, Any]], depth: int = 0) -> list[str]:
    out = []
    for n in nodes:
        out.append(f"{'  ' * depth}- {n['id']} {n['role']} [{n['status']}] {n['model']} · {n['steps']} turns · "
                   f"{_usage(n['usage'])}: {n['goal'][:120]}")
        out += _tree(n["children"], depth + 1)
    return out


def agent_run(
    action: Annotated[Literal["request", "status", "tree", "log", "result", "cancel", "presets"], Field(
        description="request: ask the user for a run (returns the approval page); status: one run, or all; "
                    "tree: its agents; log: its messages and shared notes; result: what the lead returned; "
                    "cancel: stop it; presets: the runs the user keeps ready (and their schedules)")],
    goal: Annotated[str, Field(description="request: what the team should achieve, with what done looks like")] = "",
    run: Annotated[str, Field(description="the run's id (run:…), for every action but request")] = "",
    title: str = "",
    suggest: Annotated[dict[str, Any] | None, Field(
        description="request: what you suggest for the grant, shown to the user, who decides: e.g. "
                    "{max_agents, max_spawns, max_depth, max_steps, context, roles: {lead: model, worker: model}}")] = None,
    why: str = "",
    preset: Annotated[str, Field(description="request: start from this preset of the user's (its goal, unless "
                                             "goal is given, and its grant, prefilled for the user's approval)")] = "",
) -> str:
    """Runs of autonomous agents on the user's own API keys (Claude, OpenAI, Gemini or a compatible
    server), in the user's sandbox. You can only ask for a run: the user approves it on the approval
    page, choosing the keys, models, limits and pruning. Never ask the user to approve in chat; give
    the address and go on."""
    with _lock:
        t = _team()
        if action == "presets":
            from .agents.presets import Presets

            ps = Presets(t.g)
            sched = ps.schedules()
            out = []
            for p in ps.list():
                a = p["attrs"]
                whens = [f"{x['attrs']['cron']}{'' if x['attrs'].get('enabled') else ' (off)'}" for x in sched
                         if x["attrs"]["preset"] == a["name"]]
                out.append(f"{a['name']}: {a['title']} — {p['content'][:200]}"
                           + (f" [schedules: {', '.join(whens)}]" if whens else ""))
            return "\n".join(out) or "no presets; the user saves them on the page /agents/presets"
        if action == "request":
            proposal = _suggest(suggest)
            if preset:
                from .agents.presets import Presets, fill

                p = Presets(t.g).get(preset)
                proposal = {**p["attrs"]["grant"], "preset": preset}  # the user's own settings, for the form
                goal = goal.strip() or fill(p["content"], dt.datetime.now())
                title = title or p["attrs"]["title"]
            if not goal.strip():
                raise TeamError("request needs a goal")
            rid = t.request_run(goal, actor="model", proposal=proposal, title=title)
            return (f"run {rid} requested. Nothing runs until the user approves it at {approval_url(rid)} (keys, "
                    f"models, limits). Follow it with agent_run(action='status', run='{rid}').")
        if action == "status" and not run:
            rows = t.runs()[:20]
            return "\n".join(f"{r['id']} [{r['attrs'].get('phase')}] {r['attrs'].get('title', '')}" for r in rows) \
                or "no runs"
        r = t.g.node(run)
        if r["type"] != "run":
            raise TeamError(f"{run} is not a run")
        a = r["attrs"]
        if action == "status":
            out = [f"{run} [{a.get('phase')}] {a.get('title', '')}", f"goal: {r['content'][:500]}"]
            if a.get("phase") == "requested":
                out.append(f"waiting for the user's approval: {approval_url(run)}")
            else:
                agents = t.agents(run)
                live = [x for x in agents if x["state"] == "open"]
                out.append(f"agents: {len(live)} working, {len(agents)} in all · usage {_usage(t.run_usage(run))}")
            if a.get("error"):
                out.append(f"error: {a['error']}")
            res = t.result(run)
            if res:
                out.append(f"result ({res['attrs'].get('outcome')}): {res['content'][:2000]}")
            return "\n".join(out)
        if action == "tree":
            return "\n".join(_tree(t.tree(run))) or "no agents yet"
        if action == "log":
            packets = [p for p in t._nodes("packet", run)][-30:]
            lines = [f"{p['id']} {p['attrs'].get('from')} → {p['attrs'].get('kind')}: {p['content'][:300]}"
                     for p in packets]
            lines += ["shared: " + render_note(n, full=False) for n in t.board(run)[-20:]]
            return "\n".join(lines) or "nothing yet"
        if action == "result":
            res = t.result(run)
            if res is None:
                return f"{run} has no result yet ({a.get('phase')})"
            notes = t.carried(res["id"])
            return f"{res['attrs'].get('outcome')}: {res['content']}" + "".join("\n" + render_note(n) for n in notes)
        if action == "cancel":
            t.request_cancel(run, why or "cancelled by the model", by="model")
            return f"{run}: cancellation requested"
    raise TeamError(f"unknown action {action!r}")


def _suggest(s: dict[str, Any] | None) -> dict[str, Any]:
    """The model's suggestion, kept to what the approval page shows (it decides nothing)."""
    if not isinstance(s, dict):
        return {}
    keep = {k: s[k] for k in ("max_agents", "max_spawns", "max_depth", "max_steps", "max_tokens", "context",
                              "handoff", "retention", "policy", "effort") if k in s}
    roles = s.get("roles")
    if isinstance(roles, dict):
        keep["roles"] = {r: str(m)[:200] for r, m in roles.items() if r in ROLES}
    return json.loads(json.dumps(keep, default=str))


def agent_keys() -> str:
    """The API keys the user registered for agents (provider, label, format, endpoint, fingerprint),
    never the keys themselves. Keys are added and removed on the page /agents/keys only."""
    with _lock:
        if _resolve is None:
            raise TeamError("the agent tools are not configured")
        uid, data = owner(_resolve())
    rows = keystore(data).list(uid)
    if not rows:
        return f"no keys registered; the user adds them at {os.environ.get('RHB_PUBLIC_URL', '').rstrip('/')}/agents/keys"
    return "\n".join(f"{k.ref} [{k.status}] {k.format}" + (f" at {k.base_url}" if k.base_url else "")
                     + f" · {k.fingerprint}" + (f" · {len(k.models)} models" if k.models else "") for k in rows)


WRITE_TOOLS = [agent_run]
READ_TOOLS = [agent_keys]
