"""Flows: a run drawn as blocks and arrows (docs/agents.md "Flows").

A flow is a graph of steps. Each step is one agent: a title, a role, a model (one the grant's routes
offer that role; empty: the role's first route), a goal, and where it sits on the drawing. An arrow
from A to B passes A's result to B: its text, and the notes it carried. The graph has no cycles.

A run with a flow is conducted, not led: its root agent is the crew's conductor, which never calls a
model. It opens each step's agent once every step before it has finished, skips a step when one
before it failed, and when every step is settled it returns the steps' results to the user as the
run's result. The steps themselves are ordinary agents: they may spawn within the grant.
"""

from __future__ import annotations

import re
from typing import Any

from .team import ROLES, TeamError, routes_for

STEP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_STEPS = 32


def check(flow: Any, grant: dict[str, Any]) -> dict[str, Any]:
    """The flow as it is kept: every step and arrow checked against each other and the grant."""
    if not isinstance(flow, dict):
        raise TeamError("a flow is {steps, edges}")
    steps_in, edges_in = flow.get("steps"), flow.get("edges") or []
    if not isinstance(steps_in, list) or not steps_in:
        raise TeamError("a flow has at least one step")
    if len(steps_in) > MAX_STEPS:
        raise TeamError(f"at most {MAX_STEPS} steps")
    steps, ids = [], set()
    for i, s in enumerate(steps_in):
        if not isinstance(s, dict):
            raise TeamError(f"step {i + 1}: an object")
        sid = str(s.get("id", "")).strip()
        if not STEP_ID.match(sid) or sid in ids:
            raise TeamError(f"step {i + 1}: a unique id (lowercase letters, digits, _ -)")
        ids.add(sid)
        role = str(s.get("role", "worker"))
        if role not in ROLES:
            raise TeamError(f"step {sid}: role {', '.join(ROLES)}")
        model = str(s.get("model", "") or "").strip()
        if not routes_for(grant, role, model or None):
            have = ", ".join(sorted({r["model"] for r in grant["routes"] if role in r["roles"]})) or "none"
            raise TeamError(f"step {sid}: no route of the grant runs a {role}{' on ' + model if model else ''}; "
                            f"its models: {have}")
        goal = str(s.get("goal", "")).strip()
        if not goal:
            raise TeamError(f"step {sid}: a goal")
        steps.append({"id": sid, "title": str(s.get("title", "")).strip()[:80] or sid, "role": role, "model": model,
                      "goal": goal[:8000], "x": _num(s.get("x")), "y": _num(s.get("y"))})
    edges, seen = [], set()
    for e in edges_in if isinstance(edges_in, list) else []:
        a, b = str((e or {}).get("from", "")), str((e or {}).get("to", ""))
        if a not in ids or b not in ids:
            raise TeamError(f"an arrow {a or '?'} → {b or '?'} joins steps that are not in the flow")
        if a == b:
            raise TeamError(f"an arrow from {a} to itself")
        if (a, b) not in seen:
            seen.add((a, b))
            edges.append({"from": a, "to": b})
    order(steps, edges)  # refuses a cycle
    return {"steps": steps, "edges": edges}


def _num(v: Any) -> float:
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return 0.0


def order(steps: list[dict[str, Any]], edges: list[dict[str, str]]) -> list[str]:
    """The steps in an order every arrow follows (Kahn's); a cycle is refused, naming its steps."""
    before = {s["id"]: set() for s in steps}
    for e in edges:
        before[e["to"]].add(e["from"])
    out, ready = [], [s["id"] for s in steps if not before[s["id"]]]
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m, deps in before.items():
            if n in deps:
                deps.discard(n)
                if not deps and m not in out and m not in ready:
                    ready.append(m)
    if len(out) != len(steps):
        raise TeamError("the arrows go round in a circle through " + ", ".join(sorted(set(before) - set(out))))
    return out


def fit(grant: dict[str, Any], flow: dict[str, Any]) -> dict[str, Any]:
    """The grant a flow needs at least: the conductor and one step at once, every step a ticket, the
    steps one level below the conductor."""
    n = len(flow["steps"])
    return {**grant, "max_agents": max(int(grant.get("max_agents", 2)), 2),
            "max_spawns": max(int(grant.get("max_spawns", 0)), n + 1), "max_depth": max(int(grant.get("max_depth", 1)), 1)}


def inputs(flow: dict[str, Any], sid: str) -> list[str]:
    return [e["from"] for e in flow["edges"] if e["to"] == sid]


def sinks(flow: dict[str, Any]) -> list[str]:
    starts = {e["from"] for e in flow["edges"]}
    return [s["id"] for s in flow["steps"] if s["id"] not in starts]
