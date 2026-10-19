"""Scopes: the one unit of work.

A scope is a node whose type has kind `scope`. It opens if its type's `pre` rules find nothing that
blocks, and closes if nothing blocks it:

    close(σ)  ⇔  the `close` rules of σ's type find no block            (Self = σ)
              ∧  every attached child scope of σ is closed or carried by σ
              ∧  the `check` rules of every enclosing scope find no block (Self = that scope)

Attachment is the `contains` edge from a scope to a child scope. Detaching moves that edge to an
enclosing scope: the child stops holding its parent open, and the enclosing scope inherits the duty.
A conversation turn, a task, a goal and a background run are all scope types; the kernel knows
none of them by name.
"""

from __future__ import annotations

from typing import Any

from . import rules
from .graph import CARRY, CONTAINS, TOUCHED, Forbidden, Graph, KernelError


class ScopeRefused(KernelError):
    """The gate found blocks. `findings` lists every finding; the message names the blocks."""

    def __init__(self, scope: str, what: str, findings: list[rules.Finding]):
        self.findings = findings
        blocks = [f for f in findings if f.severity == "block"]
        super().__init__(f"REFUSED: {scope} cannot {what}:\n  " + "\n  ".join(f.message for f in blocks))


def _scope(g: Graph, scope_id: str) -> dict[str, Any]:
    n = g.node(scope_id)
    t = g.get_type(n["type"])
    if not t or t["kind"] != "scope":
        raise KernelError(f"{scope_id} is a {n['type']}, not a scope")
    return n


def parent(g: Graph, scope_id: str) -> str | None:
    r = g.db.execute(
        "SELECT e.src FROM k_edges e JOIN k_nodes n ON n.id = e.src JOIN k_types t ON t.name = n.type"
        " WHERE e.type = ? AND e.dst = ? AND t.kind = 'scope'", (CONTAINS, scope_id)).fetchone()
    return r[0] if r else None


def ancestors(g: Graph, scope_id: str) -> list[str]:
    out, cur = [], parent(g, scope_id)
    while cur is not None:
        if cur in out or cur == scope_id:
            raise KernelError(f"scope containment of {scope_id} loops at {cur}")
        out.append(cur)
        cur = parent(g, cur)
    return out


def children(g: Graph, scope_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in g.db.execute(
        "SELECT n.id, n.type, n.state FROM k_edges e JOIN k_nodes n ON n.id = e.dst"
        " JOIN k_types t ON t.name = n.type WHERE e.type = ? AND e.src = ? AND t.kind = 'scope' ORDER BY n.id",
        (CONTAINS, scope_id))]


def open_scope(g: Graph, scope_id: str, type_: str, *, actor: str, parent_id: str | None = None,
               content: str = "", attrs: dict[str, Any] | None = None) -> dict[str, Any]:
    t = g.get_type(type_)
    if not t or t["kind"] != "scope":
        raise KernelError(f"{type_!r} is not a scope type")
    with g.tx():
        if parent_id is not None:
            p = _scope(g, parent_id)
            if p["state"] != "open":
                raise KernelError(f"parent {parent_id} is {p['state']}; a scope opens inside an open scope")
        g.tick()
        g.put_node(scope_id, type_, actor=actor, state="open", content=content, attrs=attrs)
        if parent_id is not None:
            g.link(parent_id, CONTAINS, scope_id, actor=actor)
        pre = rules.evaluate(g, "pre", scope_id, type_)
        if any(f.severity == "block" for f in pre):
            raise ScopeRefused(scope_id, "open", pre)
        g.log(actor, f"open {type_}", scope_id)
    return g.node(scope_id)


def findings(g: Graph, scope_id: str, phase: str = "close") -> list[rules.Finding]:
    """What would decide a close now (or another phase's findings), without changing anything."""
    s = _scope(g, scope_id)
    out = rules.evaluate(g, phase, scope_id, s["type"])
    if phase != "close":
        return out
    carried = {e["dst"] for e in g.edges(src=scope_id, type_=CARRY)}
    for c in children(g, scope_id):
        if c["state"] != "closed" and c["id"] not in carried:
            out.append(rules.Finding("kernel_open_child", "block",
                                     f"child scope {c['id']} ({c['type']}) is still {c['state']}: close it, "
                                     "carry it with a reason, or detach it to an enclosing scope", (c["id"],)))
    for a in ancestors(g, scope_id):
        out += [f for f in rules.evaluate(g, "check", a, g.node(a)["type"])]
    return out


def close(g: Graph, scope_id: str, *, actor: str, expect: int | None = None) -> list[rules.Finding]:
    """Close the scope, or raise ScopeRefused naming what blocks it. Returns the non-blocking
    findings (warnings) of a successful close."""
    with g.tx():
        s = _scope(g, scope_id)
        if s["state"] != "open":
            raise KernelError(f"{scope_id} is {s['state']}, not open")
        fs = findings(g, scope_id)
        if any(f.severity == "block" for f in fs):
            raise ScopeRefused(scope_id, "close", fs)
        g.tick()
        g.update_node(scope_id, actor=actor, expect=expect, state="closed")
        g.log(actor, f"close {s['type']}", scope_id)
    return [f for f in fs if f.severity != "block"]


def touch(g: Graph, scope_id: str, ref: str, *, actor: str) -> None:
    _scope(g, scope_id)
    g.link(scope_id, TOUCHED, ref, actor=actor)


def carry(g: Graph, scope_id: str, ref: str, why: str, *, actor: str) -> None:
    """Defer `ref` (a node, or a child scope) past this scope's close, with a reason."""
    _scope(g, scope_id)
    if not why.strip():
        raise KernelError("carry needs a why")
    g.link(scope_id, CARRY, ref, actor=actor, attrs={"why": why.strip()})


def detach(g: Graph, child: str, to: str, *, actor: str) -> None:
    """Move a child scope's attachment to an enclosing scope (one of its parent's ancestors, or the
    parent's parent). The child keeps running; the scope it now holds open is `to`."""
    _scope(g, child)
    p = parent(g, child)
    if p is None:
        raise KernelError(f"{child} is not attached to any scope")
    if to not in ancestors(g, p):
        raise Forbidden(f"{to} does not enclose {p}: a child is detached outward only")
    with g.tx():
        g.unlink(p, CONTAINS, child, actor=actor)
        g.link(to, CONTAINS, child, actor=actor, attrs={"detached_from": p})
        g.log(actor, f"detach {child} from {p} to {to}", child)
