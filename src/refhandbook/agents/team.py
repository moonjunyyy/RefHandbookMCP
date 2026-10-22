"""Runs, agents and their knowledge on the kernel graph (docs/agents.md §3–5).

Everything the runner, the MCP tools and the approval page do to a team goes through `Team`. The
actor is the caller's to say and the server's to decide: a write that follows from a model's tool
call is `model`; the runner's bookkeeping (leases, usage, slot and ticket claims, cancellation) is
`kernel`; a grant and its slots and tickets come only from the approval page, as `user`.

Knowledge moves by reference: a note exists once per run (deduplicated by content hash), and
transfer, share, split and clone add edges to it, never copies.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any

from ..kernel import scopes
from ..kernel.graph import CONTAINS, Forbidden, Graph, KernelError
from . import package

K = "kernel"
CONTEXT_LEVELS = ("full", "trim", "digest", "minimal")
HANDOFF_LEVELS = ("refs", "digest", "full")
RETENTION_LEVELS = ("all", "verified", "exits", "purge")
NOTE_KINDS = ("fact", "finding", "plan", "decision", "question", "digest", "artifact")
AGENT_LIVE = ("ready", "running", "waiting")

DEFAULT_GRANT: dict[str, Any] = {
    "max_agents": 4,  # slots: agents open at once
    "max_spawns": 16,  # tickets: agents over the whole run
    "max_depth": 3,
    "max_steps": 60,  # model turns per agent
    "max_tokens": 0,  # input + output tokens over the run; 0: only counted
    "providers": [],  # [{"provider": "anthropic", "model": "...", "key": "<label>"}], first is the default
    "layers": [],
    "network": False,
    "context": "trim",
    "handoff": "digest",
    "retention": "verified",
    "limits": {},  # sandbox.Limits fields
    "disk_mb": 4096,
}


class TeamError(KernelError):
    pass


def _now() -> float:
    return round(time.time(), 3)


def _sha(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:20]


def _attr(n: dict[str, Any], key: str, default: Any = None) -> Any:
    return n["attrs"].get(key, default)


class Team:
    def __init__(self, g: Graph):
        self.g = g
        package.install(g)

    # ── ids ──────────────────────────────────────────────────────────────

    def _seq(self, run: str, kind: str) -> int:
        key = f"agseq:{run}:{kind}"
        self.g.db.execute("INSERT OR IGNORE INTO k_meta VALUES (?, '0')", (key,))
        self.g.db.execute("UPDATE k_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = ?", (key,))
        return int(self.g.db.execute("SELECT value FROM k_meta WHERE key = ?", (key,)).fetchone()[0])

    def _run_of(self, node_id: str) -> str:
        n = self.g.node(node_id)
        if n["type"] == "run":
            return node_id
        r = _attr(n, "run")
        if not r:
            raise TeamError(f"{node_id} belongs to no run")
        return r

    def _nodes(self, type_: str, run: str, state: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id FROM k_nodes WHERE type = ? AND json_extract(attrs, '$.run') = ?"
        args: list[Any] = [type_, run]
        if state is not None:
            sql += " AND state = ?"
            args.append(state)
        return [self.g.node(r[0]) for r in self.g.db.execute(sql + " ORDER BY created, id", args)]

    # ── runs ─────────────────────────────────────────────────────────────

    def request_run(self, goal: str, *, actor: str = "model", proposal: dict[str, Any] | None = None,
                    title: str = "", ledger: str | None = None) -> str:
        """Open a run awaiting the user's approval. `proposal` is what the requester suggests for
        the grant; the approval page shows it, and the user decides."""
        if not goal.strip():
            raise TeamError("a run needs a goal")
        run = f"run:{secrets.token_hex(4)}"
        with self.g.tx():
            scopes.open_scope(self.g, run, "run", actor=actor, content=goal.strip(), attrs={
                "phase": "requested", "title": title or goal.strip().splitlines()[0][:80],
                "proposal": proposal or {}, "ledger": ledger, "requested": _now()})
        return run

    def approve(self, run: str, grant: dict[str, Any], *, actor: str = "user") -> dict[str, Any]:
        """Write the grant, its slots and its tickets, as the user. Only the approval page calls this
        with actor 'user'; the gates refuse slots and tickets anyone else wrote."""
        if actor != "user":
            raise Forbidden("only the user approves a run (through the approval page, not a tool call)")
        r = self.g.node(run)
        if r["type"] != "run" or r["state"] != "open":
            raise TeamError(f"{run} is not an open run")
        if _attr(r, "phase") != "requested":
            raise TeamError(f"{run} is {_attr(r, 'phase')}, not awaiting approval")
        cfg = {**DEFAULT_GRANT, **{k: v for k, v in grant.items() if k in DEFAULT_GRANT}}
        for k in ("max_agents", "max_spawns", "max_depth", "max_steps", "max_tokens", "disk_mb"):
            cfg[k] = int(cfg[k])
        if not (1 <= cfg["max_agents"] <= 64 and 1 <= cfg["max_spawns"] <= 1024 and 0 <= cfg["max_depth"] <= 16):
            raise TeamError("limits out of range: 1–64 agents at once, 1–1024 spawns, depth 0–16")
        if cfg["max_spawns"] < cfg["max_agents"]:
            cfg["max_spawns"] = cfg["max_agents"]
        if cfg["context"] not in CONTEXT_LEVELS or cfg["handoff"] not in HANDOFF_LEVELS \
                or cfg["retention"] not in RETENTION_LEVELS:
            raise TeamError("pruning levels: context " + "|".join(CONTEXT_LEVELS) + ", handoff "
                            + "|".join(HANDOFF_LEVELS) + ", retention " + "|".join(RETENTION_LEVELS))
        if not cfg["providers"]:
            raise TeamError("a grant names at least one provider and model")
        g = f"{run}:grant"
        with self.g.tx():
            self.g.put_node(g, "grant", actor="user", attrs={**cfg, "run": run, "approved": _now()})
            self.g.link(run, "governed_by", g, actor="user")
            for i in range(cfg["max_agents"]):
                self.g.put_node(f"{run}:slot:{i}", "slot", actor="user", attrs={"run": run})
            for i in range(cfg["max_spawns"]):
                self.g.put_node(f"{run}:ticket:{i}", "ticket", actor="user", attrs={"run": run})
            self.g.update_node(run, actor=K, attrs={"phase": "approved", "approved": _now()})
            self.g.log(actor, "run approved", run)
        return cfg

    def grant(self, run: str) -> dict[str, Any]:
        n = self.g.get_node(f"{run}:grant")
        if n is None or n["author"] != "user":
            raise TeamError(f"{run} has no grant")
        return n["attrs"]

    def runs(self, phase: str | None = None) -> list[dict[str, Any]]:
        out = [self.g.node(r[0]) for r in self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'run' ORDER BY created DESC")]
        return [r for r in out if phase is None or _attr(r, "phase") == phase]

    def set_phase(self, run: str, phase: str, **attrs: Any) -> None:
        self.g.update_node(run, actor=K, attrs={"phase": phase, **attrs})

    def cancel_run(self, run: str, why: str, *, actor: str) -> None:
        """Cancel every open agent (deepest first), then close the run with a result saying so."""
        with self.g.tx():
            r = self.g.node(run)
            if r["state"] != "open":
                return
            root = self.root(run)
            if root and self.g.node(root)["state"] == "open":
                self.cancel_agent(root, why, actor=actor)
            if not self._result(run):
                self._packet(run, frm=run, to=None, kind="exit", text=f"cancelled: {why}", refs=[],
                             actor=K, audience="user", outcome="cancelled")
            self.g.update_node(run, actor=K, attrs={"phase": "cancelled", "ended": _now()})
            self._close(run, actor)

    def _close(self, scope: str, actor: str) -> list[Any]:
        return scopes.close(self.g, scope, actor=actor)

    def close_run(self, run: str, *, actor: str = K) -> list[Any]:
        """Close the run (the gates decide) and apply the grant's retention."""
        with self.g.tx():
            warnings = self._close(run, actor)
            if _attr(self.g.node(run), "phase") not in ("cancelled", "failed"):
                self.g.update_node(run, actor=K, attrs={"phase": "done", "ended": _now()})
            self.retain(run)
        return warnings

    def _result(self, run: str) -> str | None:
        r = self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'packet' AND json_extract(attrs, '$.run') = ?"
            " AND json_extract(attrs, '$.audience') = 'user' ORDER BY created DESC LIMIT 1", (run,)).fetchone()
        return r[0] if r else None

    def result(self, run: str) -> dict[str, Any] | None:
        p = self._result(run)
        return self.g.node(p) if p else None

    # ── agents ───────────────────────────────────────────────────────────

    def root(self, run: str) -> str | None:
        for c in scopes.children(self.g, run):
            if c["type"] == "agent":
                return c["id"]
        return None

    def agents(self, run: str, state: str | None = None) -> list[dict[str, Any]]:
        return self._nodes("agent", run, state)

    def free_slot(self, run: str) -> str | None:
        r = self.g.db.execute(
            "SELECT s.id FROM k_nodes s WHERE s.type = 'slot' AND s.author = 'user'"
            " AND json_extract(s.attrs, '$.run') = ? AND NOT EXISTS (SELECT 1 FROM k_edges e JOIN k_nodes a"
            " ON a.id = e.src WHERE e.type = 'occupies' AND e.dst = s.id AND a.state = 'open') ORDER BY s.id",
            (run,)).fetchone()
        return r[0] if r else None

    def free_tickets(self, run: str) -> list[str]:
        return [r[0] for r in self.g.db.execute(
            "SELECT t.id FROM k_nodes t WHERE t.type = 'ticket' AND t.author = 'user'"
            " AND json_extract(t.attrs, '$.run') = ? AND NOT EXISTS (SELECT 1 FROM k_edges e"
            " WHERE e.type = 'consumes' AND e.dst = t.id) ORDER BY t.id", (run,))]

    def open_agent(self, run: str, *, role: str, goal: str, parent: str | None = None, provider: str | None = None,
                   model: str | None = None, key: str | None = None, mode: str = "fresh",
                   give: list[str] | None = None, context: str | None = None, handoff: str | None = None,
                   actor: str = "model", variant: str = "") -> str:
        """Open an agent scope, claiming a free slot and an unused ticket. The kernel's gates decide:
        no slot, no ticket, too deep, or no grant raise ScopeRefused with the reasons."""
        grant = self.grant(run)
        if mode not in ("fresh", "split", "clone", "root"):
            raise TeamError("mode: fresh, split or clone")
        prov = self._pick_provider(grant, provider, model)
        ctx = context or grant["context"]
        ho = handoff or grant["handoff"]
        if ctx not in CONTEXT_LEVELS or ho not in HANDOFF_LEVELS:
            raise TeamError(f"context: {'|'.join(CONTEXT_LEVELS)}; handoff: {'|'.join(HANDOFF_LEVELS)}")
        depth = 0 if parent is None else int(_attr(self.g.node(parent), "depth", 0)) + 1
        slot = self.free_slot(run)
        tickets = self.free_tickets(run)
        aid = f"{run}:a{self._seq(run, 'a')}"
        links = ([("occupies", slot)] if slot else []) + ([("consumes", tickets[0])] if tickets else [])
        with self.g.tx():
            scopes.open_scope(self.g, aid, "agent", actor=actor, parent_id=parent or run, content=goal.strip(),
                              links=links, attrs={
                                  "run": run, "role": role, "depth": depth, "parent": parent, "mode": mode,
                                  "variant": variant, "provider": prov["provider"], "model": prov["model"],
                                  "key": key or prov.get("key"), "context": ctx, "handoff": ho, "status": "ready",
                                  "steps": 0, "usage": {}, "created_at": _now(),
                                  "transcript": f"transcripts/{aid.rsplit(':', 1)[1]}.jsonl"})
            if parent:
                self.g.link(parent, "spawned", aid, actor=K, attrs={"mode": mode})
                if mode == "clone":
                    for e in self.g.edges(src=parent, type_="holds"):
                        self.g.link(aid, "holds", e["dst"], actor=K, attrs=e["attrs"])
            for nid in give or []:
                self.hold(aid, nid, actor=K)
            if self.g.node(run)["attrs"].get("phase") == "approved":
                self.g.update_node(run, actor=K, attrs={"phase": "running", "started": _now()})
        return aid

    def _pick_provider(self, grant: dict[str, Any], provider: str | None, model: str | None) -> dict[str, Any]:
        allowed = grant["providers"]
        for p in allowed:
            if (provider is None or p["provider"] == provider) and (model is None or p["model"] == model):
                return p
        names = ", ".join(f"{p['provider']}/{p['model']}" for p in allowed)
        raise TeamError(f"{provider or '*'}/{model or '*'} is not in the grant; allowed: {names}")

    def queue_spawn(self, run: str, parent: str, spec: dict[str, Any], *, actor: str = "model") -> str:
        """A spawn while no slot is free: kept until one frees (the scheduler starts it)."""
        queued = len(self._nodes("spawn_request", run, "queued"))
        if queued >= len(self.free_tickets(run)):
            raise TeamError("no ticket left for another spawn: the grant's number of spawns is used up")
        rid = f"{run}:q{self._seq(run, 'q')}"
        self.g.put_node(rid, "spawn_request", actor=actor, state="queued",
                        attrs={"run": run, "parent": parent, "spec": spec, "queued_at": _now()})
        return rid

    def queued(self, run: str) -> list[dict[str, Any]]:
        return self._nodes("spawn_request", run, "queued")

    def mark_request(self, rid: str, state: str, **attrs: Any) -> None:
        self.g.update_node(rid, actor=K, state=state, attrs=attrs)

    def update_agent(self, aid: str, *, expect: int | None = None, **attrs: Any) -> dict[str, Any]:
        return self.g.update_node(aid, actor=K, expect=expect, attrs=attrs)

    def add_usage(self, aid: str, usage: dict[str, int]) -> dict[str, int]:
        n = self.g.node(aid)
        cur = dict(_attr(n, "usage", {}))
        for k, v in usage.items():
            if isinstance(v, (int, float)):
                cur[k] = cur.get(k, 0) + int(v)
        self.g.update_node(aid, actor=K, attrs={"usage": cur, "steps": int(_attr(n, "steps", 0)) + 1})
        return cur

    def run_usage(self, run: str) -> dict[str, int]:
        tot: dict[str, int] = {}
        for a in self.agents(run):
            for k, v in _attr(a, "usage", {}).items():
                tot[k] = tot.get(k, 0) + int(v)
        return tot

    def lease(self, aid: str, owner: str, ttl: float = 120.0) -> bool:
        """Take or renew the agent's lease (compare-and-swap); False if another runner holds it."""
        n = self.g.node(aid)
        held, until = _attr(n, "lease_owner"), float(_attr(n, "lease_until", 0) or 0)
        if held and held != owner and until > time.time():
            return False
        try:
            self.g.update_node(aid, actor=K, expect=n["version"],
                               attrs={"lease_owner": owner, "lease_until": time.time() + ttl})
        except KernelError:
            return False
        return True

    def release(self, aid: str, owner: str) -> None:
        n = self.g.node(aid)
        if _attr(n, "lease_owner") == owner:
            self.g.update_node(aid, actor=K, attrs={"lease_owner": None, "lease_until": None})

    def finish(self, aid: str, outcome: str, text: str, refs: list[str] | None = None, *,
               actor: str = "model") -> tuple[str, list[Any]]:
        """Write the exit packet (to the parent, or to the user for the root) and close the agent.
        If the gates refuse, nothing is written: the refusal says what is missing."""
        n = self.g.node(aid)
        run, parent = _attr(n, "run"), _attr(n, "parent")
        with self.g.tx():
            p = self._packet(run, frm=aid, to=parent, kind="exit", text=text, refs=refs or [], actor=actor,
                             audience=None if parent else "user", outcome=outcome)
            warnings = self._close(aid, actor)
            self.g.update_node(aid, actor=K, attrs={"status": "done" if outcome != "failed" else "failed",
                                                    "outcome": outcome, "ended": _now(),
                                                    "lease_owner": None, "lease_until": None})
        return p, warnings

    def cancel_agent(self, aid: str, why: str, *, actor: str) -> None:
        """Close an agent and its open descendants, deepest first, each with an exit packet saying it
        was cancelled (and its unread packets marked read, so nothing holds it open)."""
        with self.g.tx():
            for c in scopes.children(self.g, aid):
                if c["type"] == "agent" and c["state"] == "open":
                    self.cancel_agent(c["id"], why, actor=actor)
            n = self.g.node(aid)
            if n["state"] != "open":
                return
            for p in self.inbox(aid):
                self.g.update_node(p["id"], actor=K, state="read")
            q = self._nodes("spawn_request", _attr(n, "run"), "queued")
            for r in q:
                if _attr(r, "parent") == aid:
                    self.mark_request(r["id"], "dropped", why=f"parent cancelled: {why}")
            parent = _attr(n, "parent")
            self._packet(_attr(n, "run"), frm=aid, to=parent, kind="exit", text=f"cancelled: {why}", refs=[],
                         actor=K, audience=None if parent else "user", outcome="cancelled")
            self._close(aid, actor)
            self.g.update_node(aid, actor=K, attrs={"status": "cancelled", "outcome": "cancelled", "ended": _now(),
                                                    "lease_owner": None, "lease_until": None})

    def children(self, aid: str) -> list[dict[str, Any]]:
        return [self.g.node(e["dst"]) for e in self.g.edges(src=aid, type_="spawned")]

    def tree(self, run: str) -> list[dict[str, Any]]:
        """The agents as a nested list: {id, role, status, provider, model, steps, usage, children}."""

        def walk(scope: str) -> list[dict[str, Any]]:
            out = []
            for c in scopes.children(self.g, scope):
                if c["type"] != "agent":
                    continue
                n = self.g.node(c["id"])
                out.append({"id": n["id"], "role": _attr(n, "role"), "state": n["state"],
                            "status": _attr(n, "status"), "provider": _attr(n, "provider"),
                            "model": _attr(n, "model"), "steps": _attr(n, "steps", 0), "usage": _attr(n, "usage", {}),
                            "goal": n["content"][:200], "children": walk(n["id"])})
            return out

        return walk(run)

    # ── knowledge ────────────────────────────────────────────────────────

    def note(self, run: str, by: str, text: str, *, kind: str = "finding", refs: list[str] | None = None,
             pin: bool = False, post: bool = False, actor: str = "model", title: str = "") -> str:
        """Record a note (or find the identical one already in the run), put it in the author's
        working set, and optionally share it on the run's board."""
        if kind not in NOTE_KINDS:
            raise TeamError(f"note kind: {'|'.join(NOTE_KINDS)}")
        if not text.strip():
            raise TeamError("an empty note")
        sha = _sha(text)
        r = self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'note' AND json_extract(attrs, '$.run') = ?"
            " AND json_extract(attrs, '$.sha') = ?", (run, sha)).fetchone()
        with self.g.tx():
            if r:
                nid = r[0]
            else:
                nid = f"{run}:n{self._seq(run, 'n')}"
                a = self.g.node(by) if by != run else None
                self.g.put_node(nid, "note", actor=actor, state="proposed", content=text.strip(), attrs={
                    "run": run, "by": by, "kind": kind, "sha": sha, "title": title or _title(text),
                    "provider": _attr(a, "provider") if a else None, "model": _attr(a, "model") if a else None,
                    "at": _now()})
                for ref in refs or []:
                    if self.g.get_node(ref) is not None:
                        self.g.link(nid, "derived_from", ref, actor=actor)
            if by != run:
                self.hold(by, nid, pin=pin, actor=K)
            if post:
                self.g.link(nid, "posted", run, actor=actor)
        return nid

    def hold(self, aid: str, nid: str, *, pin: bool = False, actor: str = K) -> None:
        if self.g.node(nid)["type"] not in ("note", "artifact"):
            raise TeamError(f"{nid} is not a note or artifact")
        if self._run_of(nid) != self._run_of(aid):
            raise TeamError(f"{nid} belongs to another run")
        old = [e for e in self.g.edges(src=aid, type_="holds", dst=nid)]
        keep_pin = bool(old and old[0]["attrs"].get("pin"))
        self.g.link(aid, "holds", nid, actor=actor, attrs={"pin": pin or keep_pin, "at": _now()})

    def unhold(self, aid: str, nid: str) -> None:
        self.g.unlink(aid, "holds", nid, actor=K)

    def pin(self, aid: str, nid: str, pin: bool = True) -> None:
        self.g.link(aid, "holds", nid, actor=K, attrs={"pin": pin, "at": _now()})

    def held(self, aid: str) -> list[tuple[dict[str, Any], bool]]:
        out = []
        for e in self.g.edges(src=aid, type_="holds"):
            n = self.g.get_node(e["dst"])
            if n is not None and n["state"] not in ("retired", "superseded"):
                out.append((n, bool(e["attrs"].get("pin"))))
        out.sort(key=lambda x: x[0]["id"])
        return out

    def post(self, nid: str, *, actor: str = "model") -> None:
        self.g.link(nid, "posted", self._run_of(nid), actor=actor)

    def board(self, run: str) -> list[dict[str, Any]]:
        return [self.g.node(e["src"]) for e in self.g.edges(dst=run, type_="posted")
                if self.g.node(e["src"])["state"] not in ("retired", "superseded")]

    def verify(self, nid: str, by: str, verdict: str, evidence: str, *, actor: str = "model") -> dict[str, Any]:
        if verdict not in ("verified", "disputed"):
            raise TeamError("verdict: verified or disputed")
        n = self.g.node(nid)
        if n["type"] != "note":
            raise TeamError(f"{nid} is not a note")
        if verdict == "verified" and _attr(n, "by") == by:
            raise TeamError(f"{nid} was written by {by}: another agent must verify it")
        return self.g.update_node(nid, actor=actor, state=verdict,
                                  attrs={"verified_by": by, "evidence": evidence, "verified_at": _now()})

    def retire(self, nid: str, why: str, *, actor: str = "model", superseded_by: str | None = None) -> None:
        self.g.update_node(nid, actor=actor, state="superseded" if superseded_by else "retired",
                           attrs={"retired_why": why, "superseded_by": superseded_by})

    def recall(self, run: str, query: str, *, agent: str | None = None, limit: int = 8,
               include_retired: bool = False) -> list[dict[str, Any]]:
        """Notes of the run ranked by how many query words they contain (title counts double);
        held notes of `agent` first among equals."""
        words = [w for w in re.findall(r"\w{2,}", query.lower())]
        held = {n["id"] for n, _ in self.held(agent)} if agent else set()
        scored = []
        for n in self._nodes("note", run):
            if not include_retired and n["state"] in ("retired", "superseded"):
                continue
            text, title = n["content"].lower(), str(_attr(n, "title", "")).lower()
            score = sum(text.count(w) + 2 * title.count(w) for w in words) if words else 1
            if score:
                scored.append((-score, n["id"] not in held, n["id"], n))
        scored.sort(key=lambda x: x[:3])
        return [x[3] for x in scored[:limit]]

    # ── messages ─────────────────────────────────────────────────────────

    def _packet(self, run: str, *, frm: str, to: str | None, kind: str, text: str, refs: list[str], actor: str,
                audience: str | None = None, outcome: str | None = None, handoff: str | None = None) -> str:
        pid = f"{run}:p{self._seq(run, 'p')}"
        self.g.put_node(pid, "packet", actor=actor, state="sent", content=text, attrs={
            "run": run, "from": frm, "kind": kind, "audience": audience, "outcome": outcome,
            "handoff": handoff, "at": _now()})
        if to:
            self.g.link(pid, "to", to, actor=actor)
        for ref in refs:
            n = self.g.get_node(ref)
            if n is None or n["type"] not in ("note", "artifact"):
                raise TeamError(f"{ref} is not a note or artifact of this run")
            self.g.link(pid, "carries", ref, actor=actor)
        return pid

    def send(self, frm: str, to: str, text: str, refs: list[str] | None = None, *, handoff: str = "refs",
             actor: str = "model") -> str:
        run = self._run_of(frm)
        if self._run_of(to) != run:
            raise TeamError(f"{to} is in another run")
        if self.g.node(to)["type"] != "agent":
            raise TeamError(f"{to} is not an agent")
        with self.g.tx():
            return self._packet(run, frm=frm, to=to, kind="message", text=text, refs=refs or [], actor=actor,
                                handoff=handoff)

    def inbox(self, aid: str, *, unread: bool = True) -> list[dict[str, Any]]:
        out = []
        for e in self.g.edges(dst=aid, type_="to"):
            p = self.g.node(e["src"])
            if p["type"] == "packet" and (not unread or p["state"] == "sent"):
                out.append(p)
        out.sort(key=lambda p: p["created"])
        return out

    def read(self, aid: str, pid: str) -> dict[str, Any]:
        """Mark a packet read and put the notes it carries in the reader's working set."""
        p = self.g.node(pid)
        if not any(e["dst"] == aid for e in self.g.edges(src=pid, type_="to")):
            raise TeamError(f"{pid} is not addressed to {aid}")
        with self.g.tx():
            for e in self.g.edges(src=pid, type_="carries"):
                self.hold(aid, e["dst"], actor=K)
            self.g.update_node(pid, actor=K, state="read")
        return p

    def carried(self, pid: str) -> list[dict[str, Any]]:
        return [self.g.node(e["dst"]) for e in self.g.edges(src=pid, type_="carries")]

    # ── artifacts ────────────────────────────────────────────────────────

    def artifact(self, run: str, by: str, path: str, sha256: str, size: int, *, actor: str = "model") -> str:
        fid = f"{run}:f{self._seq(run, 'f')}"
        with self.g.tx():
            self.g.put_node(fid, "artifact", actor=actor, content=path, attrs={
                "run": run, "by": by, "path": path, "sha256": sha256, "size": size, "at": _now()})
            self.hold(by, fid, actor=K)
        return fid

    # ── retention ────────────────────────────────────────────────────────

    def retain(self, run: str, level: str | None = None) -> dict[str, int]:
        """After a run: keep what the retention level keeps live, retire (or, for purge, delete)
        the rest. Returns counts."""
        try:
            level = level or self.grant(run)["retention"]
        except TeamError:
            level = level or "verified"
        exits = {p["id"] for p in self._nodes("packet", run) if _attr(p, "kind") == "exit"}
        carried = {e["dst"] for p in exits for e in self.g.edges(src=p, type_="carries")}
        pinned = {r[0] for r in self.g.db.execute(
            "SELECT e.dst FROM k_edges e JOIN k_nodes n ON n.id = e.dst WHERE e.type = 'holds'"
            " AND json_extract(e.attrs, '$.pin') = 1 AND json_extract(n.attrs, '$.run') = ?", (run,))}
        counts = {"kept": 0, "retired": 0, "deleted": 0}
        with self.g.tx():
            for n in self._nodes("note", run):
                if n["state"] in ("retired", "superseded"):
                    continue
                keep = (level == "all" or n["id"] in carried
                        or (level == "verified" and (n["state"] == "verified" or n["id"] in pinned)))
                if keep:
                    counts["kept"] += 1
                elif level == "purge":
                    self.g.delete_node(n["id"], actor=K)
                    counts["deleted"] += 1
                else:
                    self.g.update_node(n["id"], actor=K, state="retired", attrs={"retired_why": f"retention {level}"})
                    counts["retired"] += 1
            self.g.update_node(run, actor=K, attrs={"retention": {"level": level, **counts}})
        return counts


def _title(text: str) -> str:
    line = text.strip().splitlines()[0]
    return line[:80]


def render_note(n: dict[str, Any], *, full: bool = True) -> str:
    a = n["attrs"]
    head = f"[{n['id']}] ({a.get('kind')}, {n['state']}, by {a.get('by', '?').rsplit(':', 1)[-1]})"
    return f"{head} {n['content'] if full else a.get('title', '')}"


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, indent=1, default=str)


__all__ = ["CONTAINS", "Team", "TeamError", "render_note"]
