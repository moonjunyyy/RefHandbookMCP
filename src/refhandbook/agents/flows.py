"""Flows: a run drawn as blocks and arrows (docs/agents.md "Flows").

A block is one agent: a title, a key and model of the user's, and a command (what it is told to do).
A team block's agent leads: it may split its command among helpers it spawns (any of the flow's models)
and returns one result; a plain block does its command itself.
An arrow from A to B is a next action, named (a label, e.g. "검토 필요", "완료"). When a block's agent
finishes, it chooses which of its arrows to follow (finish(next=<label>)); with one arrow there is
nothing to choose, with none the flow ends there. The block the arrow leads to gets the previous
block's result (its text, and the notes it carried) after its own command. Arrows may lead back: a
block runs at most `max_visits` times in a run, and the flow stops when one would run once more.

A run with a flow is conducted, not led: its root agent is the crew's conductor, which never calls a
model. The run's routing is the blocks' keys and models; the user sets only the limits and levels.

Every preset is a flow; a goal with a routing table (a preset or run of before flows, or a run Claude
asked for) reads as a flow of one team block (from_grant), so all of them open in the same editor.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from portal.i18n import t

from .team import ROLES, TeamError, check_grant

STEP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_STEPS = 32
MAX_VISITS = 20


def check(flow: Any, keys: set[str] | None = None) -> dict[str, Any]:
    """The flow as it is kept: every block and arrow checked against each other (and, given the user's
    keys, every block's key)."""
    if not isinstance(flow, dict):
        raise TeamError("a flow is {steps, edges, start}")
    steps_in, edges_in = flow.get("steps"), flow.get("edges") or []
    if not isinstance(steps_in, list) or not steps_in:
        raise TeamError("a flow has at least one block")
    if len(steps_in) > MAX_STEPS:
        raise TeamError(f"at most {MAX_STEPS} blocks")
    steps, ids = [], set()
    for i, s in enumerate(steps_in):
        if not isinstance(s, dict):
            raise TeamError(f"block {i + 1}: an object")
        sid = str(s.get("id", "")).strip()
        if not STEP_ID.match(sid) or sid in ids:
            raise TeamError(f"block {i + 1}: a unique id (lowercase letters, digits, _ -)")
        ids.add(sid)
        title = str(s.get("title", "")).strip()[:80] or sid
        key = str(s.get("key", "")).strip()
        if "/" not in key:
            raise TeamError(f"block {title}: a key")
        if keys is not None and key not in keys:
            raise TeamError(f"block {title}: {key} is not a key you registered")
        model = str(s.get("model", "")).strip()
        if not model or len(model) > 200 or any(c.isspace() for c in model):
            raise TeamError(f"block {title}: a model")
        command = str(s.get("command", "")).strip()
        if not command:
            raise TeamError(f"block {title}: a command (what it is told to do)")
        steps.append({"id": sid, "title": title, "key": key, "model": model, "command": command[:8000],
                      "team": bool(s.get("team")), "x": _num(s.get("x")), "y": _num(s.get("y"))})
    titles = {s["id"]: s["title"] for s in steps}
    edges, seen = [], set()
    for e in edges_in if isinstance(edges_in, list) else []:
        a, b = str((e or {}).get("from", "")), str((e or {}).get("to", ""))
        if a not in ids or b not in ids:
            raise TeamError(f"an arrow {a or '?'} → {b or '?'} joins blocks that are not in the flow")
        label = " ".join(str((e or {}).get("label", "")).split())[:60] or titles[b]
        if (a, label.lower()) in seen:
            raise TeamError(f"two arrows out of {titles[a]} are both named {label!r}")
        seen.add((a, label.lower()))
        edges.append({"from": a, "to": b, "label": label})
    start = str(flow.get("start") or steps[0]["id"])
    if start not in ids:
        raise TeamError(f"the start block {start!r} is not in the flow")
    try:
        visits = int(flow.get("max_visits") or 3)
    except (TypeError, ValueError) as e:
        raise TeamError("max_visits: a number") from e
    if not 1 <= visits <= MAX_VISITS:
        raise TeamError(f"max_visits: 1–{MAX_VISITS}")
    return {"steps": steps, "edges": edges, "start": start, "max_visits": visits}


def fill(goal: str, at: dt.datetime) -> str:
    """The goal with {date}, {time} and {datetime} filled in (only these: a goal is not a format string)."""
    for k, v in (("{datetime}", at.strftime("%Y-%m-%d %H:%M")), ("{date}", at.strftime("%Y-%m-%d")),
                 ("{time}", at.strftime("%H:%M"))):
        goal = goal.replace(k, v)
    return goal


def dated(flow: dict[str, Any], at: dt.datetime) -> dict[str, Any]:
    """The flow as it runs at `at`: each block's command with {date}, {time} and {datetime} filled in."""
    return {**flow, "steps": [{**s, "command": fill(s.get("command", ""), at)} for s in flow["steps"]]}


def from_grant(goal: str, grant: dict[str, Any] | None) -> dict[str, Any]:
    """A goal and a routing table as a flow: one team block on the route that leads (the first route
    serving the lead, else the first), told the goal. Not checked: a grant with no route gives a
    block with no key or model, for the user to choose."""
    routes = (grant or {}).get("routes") or []
    lead = next((r for r in routes if "lead" in r.get("roles", []) or "*" in r.get("roles", [])),
                routes[0] if routes else {})
    return {"steps": [{"id": "main", "title": t("실행"), "key": lead.get("key", ""), "model": lead.get("model", ""),
                       "command": goal.strip(), "team": True, "x": 40.0, "y": 60.0}],
            "edges": [], "start": "main", "max_visits": 3}


def limits(grant: dict[str, Any] | None) -> dict[str, Any]:
    """A grant without its routing and its bookkeeping: what a flow's run is given besides its blocks."""
    return {k: v for k, v in (grant or {}).items() if k not in ("routes", "run", "approved")}


def _num(v: Any) -> float:
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return 0.0


def routes(flow: dict[str, Any]) -> list[dict[str, Any]]:
    """The run's routing: each distinct key and model of the blocks, for any role."""
    out, seen = [], set()
    for s in flow["steps"]:
        if (s["key"], s["model"]) not in seen:
            seen.add((s["key"], s["model"]))
            out.append({"key": s["key"], "model": s["model"], "roles": list(ROLES)})
    return out


def fit(grant: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    """The grant a flow runs under, checked: its blocks' routing, the conductor and one block at once, a
    ticket per block run (each block at most max_visits times), the blocks one level below the conductor.
    The user's limits stand where they are larger (a block may spawn helpers of its own)."""
    cfg = check_grant({**grant, "routes": routes(flow)})
    n = len(flow["steps"]) * flow["max_visits"] + 1
    return check_grant({**cfg, "max_agents": max(cfg["max_agents"], 2), "max_spawns": min(1024, max(cfg["max_spawns"], n)),
                        "max_depth": max(cfg["max_depth"], 1)})


def step(flow: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in flow["steps"] if s["id"] == sid)


def outs(flow: dict[str, Any], sid: str) -> list[dict[str, str]]:
    return [e for e in flow["edges"] if e["from"] == sid]


def choose(flow: dict[str, Any], sid: str, choice: str | None) -> dict[str, str] | None:
    """The arrow to follow out of a block: the only one, or the one its agent named; None: the end."""
    out = outs(flow, sid)
    if len(out) <= 1:
        return out[0] if out else None
    want = " ".join((choice or "").split()).lower()
    return next((e for e in out if e["label"].lower() == want), None)
