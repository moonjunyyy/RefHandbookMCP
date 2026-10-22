"""A model's rule proposal and its approval, in one place for every channel (the CLI, /agents).

What a proposal changes is data, not prose: the rules it replaces are recorded beside it
(k_meta `proposal:<id>`, a JSON list), never read back out of a log line the model wrote. An
approval names everything it changes: the hash the user approves covers what the proposal says and
what each rule it retires says, so a proposal revised, or a replaced rule changed, after the user
looked is not approved.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .graph import Forbidden, Graph, KernelError, rule_sha


def record(g: Graph, rule_id: str, replaces: list[str] | str | None) -> list[str]:
    ids = replaces.split() if isinstance(replaces, str) else list(replaces or [])
    for rid in ids:
        r = g.get_rule(rid)
        if r is None or r["state"] != "active":
            raise KernelError(f"proposal {rule_id}: replaces {rid!r}, which is not an active rule")
        if rid == rule_id:
            raise KernelError(f"proposal {rule_id} cannot replace itself")
    with g.tx():
        g.db.execute("INSERT OR REPLACE INTO k_meta VALUES (?, ?)", (f"proposal:{rule_id}", json.dumps(ids)))
    return ids


def replaces(g: Graph, rule_id: str) -> list[str]:
    row = g.db.execute("SELECT value FROM k_meta WHERE key = ?", (f"proposal:{rule_id}",)).fetchone()
    return json.loads(row[0]) if row else []


def approval_sha(g: Graph, rule_id: str) -> str:
    r = g.get_rule(rule_id)
    if r is None:
        raise KernelError(f"no rule {rule_id!r}")
    h = hashlib.sha256(rule_sha(r).encode())
    for rid in replaces(g, rule_id):
        old = g.get_rule(rid)
        h.update(f"|{rid}:{rule_sha(old) if old else 'gone'}".encode())
    return h.hexdigest()


def open_proposals(g: Graph) -> list[dict[str, Any]]:
    out = []
    for r in g.db.execute("SELECT * FROM k_rules WHERE authority = 'proposed' AND state = 'active' ORDER BY id"):
        r = dict(r)
        why = g.db.execute("SELECT event FROM k_log WHERE ref = ? AND event LIKE 'proposal %' ORDER BY seq DESC "
                           "LIMIT 1", (r["id"],)).fetchone()
        r["why"] = why[0] if why else ""
        r["replaces"] = [g.get_rule(x) or {"id": x, "body": "(gone)", "message": ""} for x in replaces(g, r["id"])]
        r["approval"] = approval_sha(g, r["id"])[:12]
        out.append(r)
    return out


def approve(g: Graph, rule_id: str, seen: str, *, actor: str) -> list[str]:
    """Seal the proposal and retire the rules it replaces, if `seen` is the approval hash shown."""
    if actor != "user":
        raise Forbidden("only the user approves a proposal (through the approval page, not a tool call)")
    now = approval_sha(g, rule_id)
    if len(seen or "") < 8 or not now.startswith(seen.lower()):
        raise KernelError(f"proposal {rule_id!r} is not the version shown ({seen}); it is now {now[:12]}: "
                          "review it again")
    old = replaces(g, rule_id)
    with g.tx():
        g.approve("rule", rule_id, actor=actor)
        for rid in old:
            g.retire_rule(rid, actor=actor)
        g.db.execute("DELETE FROM k_meta WHERE key = ?", (f"proposal:{rule_id}",))
    return old


def reject(g: Graph, rule_id: str, *, actor: str) -> None:
    r = g.get_rule(rule_id)
    if r is None or r["authority"] != "proposed":
        raise KernelError(f"{rule_id!r} is not an open proposal")
    with g.tx():
        g.retire_rule(rule_id, actor=actor)
        g.db.execute("DELETE FROM k_meta WHERE key = ?", (f"proposal:{rule_id}",))
