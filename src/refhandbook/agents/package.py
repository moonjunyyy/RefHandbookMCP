"""The agents vocabulary and gates as a kernel package (docs/agents.md §3).

Like kernel/packages/research.py this is rows, not logic: scope and node types, edge types, and
Datalog rules. The rule language has no aggregates, so the limits on agents are nodes the user
writes: a `slot` is one unit of concurrency (reusable), a `ticket` one spawn (consumed for good).
Opening an agent scope claims one of each in the same transaction, and the `pre` rules refuse the
open if either is missing, taken, forged (not written by the user) or from another run.

Ids, for a run R (`run:<hex>`): grant `R:grant`, slots `R:slot:<i>`, tickets `R:ticket:<i>`,
agents `R:a<n>`, notes `R:n<n>`, packets `R:p<n>`, artifacts `R:f<n>`. Every node of a run
carries attr `run`. A run is never contained in a research ledger: a ledger's re-projection drops
what it contains. The ledger, if any, is named in the run's attrs.
"""

from __future__ import annotations

from ..kernel.graph import Graph

PKG = "agents"
VERSION = "1"

NOTE_STATES = {"proposed": ["live"], "verified": ["live", "citable"], "disputed": ["live"],
               "retired": ["finished"], "superseded": ["finished"]}
PACKET_STATES = {"sent": ["unread"], "read": []}


def _r(id: str, phase: str, body: str, message: str = "", applies_to: str = "*", severity: str = "block") -> dict:
    return dict(id=id, phase=phase, body=body, message=message, applies_to=applies_to, severity=severity, pkg=PKG)


RULES = [
    # ── vocabulary ───────────────────────────────────────────────────────
    _r("ag_has_slot", "derive", "ag_has_slot(A) :- edge(A, occupies, _)."),
    _r("ag_has_ticket", "derive", "ag_has_ticket(A) :- edge(A, consumes, _)."),
    _r("ag_grant", "derive", "ag_grant(R, G) :- edge(R, governed_by, G), node(G, grant, _), author(G, user)."),
    _r("ag_has_exit", "derive",
       'ag_has_exit(A) :- node(P, packet, _), attr(P, from, A), attr(P, kind, "exit").'),
    _r("ag_has_result", "derive",
       'ag_has_result(R) :- node(P, packet, _), attr(P, run, R), attr(P, audience, "user").'),

    # ── opening an agent: its slot, its ticket, its depth ────────────────
    _r("ag_pre_no_slot", "pre", "ag_pre_no_slot(A) :- node(A, agent, _), A = Self, not ag_has_slot(A).",
       "{A}: no free slot (the grant's concurrency is used up); wait for an agent to finish", "agent"),
    _r("ag_pre_slot_busy", "pre",
       "ag_pre_slot_busy(S, B) :- edge(Self, occupies, S), edge(B, occupies, S), B != Self, node(B, agent, open).",
       "slot {S} is held by {B}, which is still open", "agent"),
    _r("ag_pre_slot_forged", "pre",
       "ag_pre_slot_forged(S) :- edge(Self, occupies, S), author(S, W), W != user.",
       "slot {S} was not written by the user: only the approval page makes slots", "agent"),
    _r("ag_pre_slot_kind", "pre",
       "ag_pre_slot_kind(S) :- edge(Self, occupies, S), not node(S, slot, _).",
       "{S} is not a slot", "agent"),
    _r("ag_pre_slot_foreign", "pre",
       "ag_pre_slot_foreign(S) :- edge(Self, occupies, S), attr(S, run, R1), attr(Self, run, R2), R1 != R2.",
       "slot {S} belongs to another run", "agent"),
    _r("ag_pre_no_ticket", "pre", "ag_pre_no_ticket(A) :- node(A, agent, _), A = Self, not ag_has_ticket(A).",
       "{A}: no ticket left (the grant's number of spawns is used up)", "agent"),
    _r("ag_pre_ticket_used", "pre",
       "ag_pre_ticket_used(T, B) :- edge(Self, consumes, T), edge(B, consumes, T), B != Self.",
       "ticket {T} was already used by {B}", "agent"),
    _r("ag_pre_ticket_forged", "pre",
       "ag_pre_ticket_forged(T) :- edge(Self, consumes, T), author(T, W), W != user.",
       "ticket {T} was not written by the user", "agent"),
    _r("ag_pre_ticket_kind", "pre",
       "ag_pre_ticket_kind(T) :- edge(Self, consumes, T), not node(T, ticket, _).",
       "{T} is not a ticket", "agent"),
    _r("ag_pre_ticket_foreign", "pre",
       "ag_pre_ticket_foreign(T) :- edge(Self, consumes, T), attr(T, run, R1), attr(Self, run, R2), R1 != R2.",
       "ticket {T} belongs to another run", "agent"),
    _r("ag_pre_ungoverned", "pre",
       "ag_pre_ungoverned(R) :- attr(Self, run, R), not ag_grant(R, _).",
       "run {R} has no grant from the user: approve it first", "agent"),
    _r("ag_pre_too_deep", "pre",
       "ag_pre_too_deep(D, M) :- attr(Self, depth, D), attr(Self, run, R), ag_grant(R, G), attr(G, max_depth, M), D > M.",
       "depth {D} exceeds the grant's max_depth {M}", "agent"),
    _r("ag_pre_run_closed", "pre",
       "ag_pre_run_closed(R) :- attr(Self, run, R), node(R, run, closed).",
       "run {R} is closed", "agent"),

    # ── finishing an agent ───────────────────────────────────────────────
    _r("ag_close_no_exit", "close", "ag_close_no_exit(A) :- node(A, agent, _), A = Self, not ag_has_exit(A).",
       "{A} has no exit packet: finish() with an outcome and what it returns", "agent"),
    _r("ag_close_unread", "close",
       "ag_close_unread(P, C) :- edge(P, to, Self), node(P, packet, sent), attr(P, from, C), edge(Self, spawned, C).",
       "packet {P} from child {C} is unread: read your children's results before finishing", "agent"),

    # ── closing a run ────────────────────────────────────────────────────
    _r("ag_close_no_result", "close", "ag_close_no_result(R) :- node(R, run, _), R = Self, not ag_has_result(R).",
       "run {R} has no result for the user", "run"),
    _r("ag_c_self_verified", "check",
       "ag_c_self_verified(N, A) :- node(N, note, verified), attr(N, run, Self), attr(N, by, A), attr(N, verified_by, A).",
       "note {N} was verified by its own author {A}: another agent must verify it", "run"),
    _r("ag_close_self_verified", "close",
       "ag_close_self_verified(N, A) :- node(N, note, verified), attr(N, run, Self), attr(N, by, A), attr(N, verified_by, A).",
       "note {N} was verified by its own author {A}: another agent must verify it", "run"),
]


def installed(g: Graph) -> bool:
    r = g.db.execute("SELECT value FROM k_meta WHERE key = 'pkg:agents'").fetchone()
    return bool(r and r[0] == VERSION)


def install(g: Graph, actor: str = "kernel") -> None:
    """Define the agents vocabulary and rules, once per VERSION (each definition logs and bumps the
    rules revision, so this is not done on every open)."""
    if installed(g):
        return
    with g.tx():
        g.define_type("run", "scope", actor=actor, pkg=PKG, binding="manual",
                      description="One goal for a team of agents; approved by the user through a grant.")
        g.define_type("agent", "scope", actor=actor, pkg=PKG, binding="manual",
                      description="One LLM loop. A child agent is contained in its parent; the root in the run.")
        g.define_type("grant", "node", actor=actor, pkg=PKG,
                      description="The user's approval of a run: providers, models, layers, limits, pruning.")
        g.define_type("slot", "node", actor=actor, pkg=PKG, description="One unit of a run's concurrency.")
        g.define_type("ticket", "node", actor=actor, pkg=PKG, description="One spawn, consumed when used.")
        g.define_type("note", "node", actor=actor, pkg=PKG, states=NOTE_STATES,
                      description="A unit of knowledge, written by an agent; shared by reference.")
        g.define_type("packet", "node", actor=actor, pkg=PKG, states=PACKET_STATES,
                      description="A message between agents (or to the user): a digest and the notes it carries.")
        g.define_type("artifact", "node", actor=actor, pkg=PKG, description="A file published from a workspace.")
        g.define_type("spawn_request", "node", actor=actor, pkg=PKG,
                      states={"queued": ["live"], "started": ["finished"], "dropped": ["finished"]},
                      description="A spawn waiting for a free slot.")
        for name, inverse, desc, auth in (
            ("governed_by", "governs", "The run is approved by the grant.", None),
            ("occupies", "occupied_by", "The agent holds the slot while it is open.", "kernel"),
            ("consumes", "consumed_by", "The agent used up the ticket.", "kernel"),
            ("spawned", "spawned_by", "The parent agent started the child (attrs.mode: fresh, split, clone).", None),
            ("holds", "held_by", "The note is in the agent's working set (attrs.pin).", None),
            ("posted", "posted_by", "The note is shared on the run's board.", None),
            ("carries", "carried_in", "The packet carries the note.", None),
            ("to", "receives", "The packet is addressed to the agent.", None),
            ("derived_from", "derives", "The note rests on the other note or artifact.", None),
        ):
            g.define_type(name, "edge", actor=actor, pkg=PKG, inverse=inverse, description=desc,
                          authority=auth)
        g.define_rules(RULES, actor=actor)
        g.db.execute("INSERT OR REPLACE INTO k_meta VALUES ('pkg:agents', ?)", (VERSION,))
