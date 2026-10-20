"""Sessions: who is working on a scope, and what they have seen.

A session is one participant's span of work on a scope: a chat conversation's exchange with a
research ledger, an agent's run on it, or anything else that writes to a scope. It replaces the
turn: there is no ledger-wide "open turn" that one caller holds and every other caller collides with.

    open(scope, role)   a token, stable for the whole session (not one per write). An idle session of
                        the same role (no use for ADOPT_IDLE seconds) is adopted instead of opening a
                        second one: a conversation that comes back picks up where it was left.
    claim(keys)         before a write: refuse it if another session changed one of these objects
                        after this session last read it (optimistic, per object), else record it.
                        Two sessions working on different objects never block each other.
    ack(keys)           reading an object (or the whole scope) moves what this session has seen.
    close()             the scope's close rules for this session (its role decides which apply).

Each session gets the scope's next number (`seq`): logs, recency ("the last 3 sessions") and
cadences ("a review every 7 sessions") count in sessions. The kernel knows no scope type by name.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from .graph import Graph, KernelError

ADOPT_IDLE = 1800.0
ROLES = ("chat", "agent")


class SessionError(KernelError):
    pass


class Conflict(SessionError):
    """Another session changed an object this one is about to write. Not a refusal of the work:
    re-read the objects named and redo the change."""


def _row(g: Graph, sid: str) -> dict[str, Any] | None:
    r = g.db.execute("SELECT * FROM k_sessions WHERE id = ?", (sid,)).fetchone()
    return dict(r) if r else None


def get(g: Graph, sid: str, scope: str | None = None) -> dict[str, Any]:
    s = _row(g, (sid or "").strip())
    if s is None or s["closed"] is not None or (scope is not None and s["scope"] != scope):
        where = f" on {scope!r}" if scope else ""
        raise SessionError(f"REFUSED: no open session {sid!r}{where}. research_begin opens one (or resumes "
                           "this conversation's): its first line is the session to pass to every call.")
    return s


def open_sessions(g: Graph, scope: str) -> list[dict[str, Any]]:
    return [dict(r) for r in g.db.execute("SELECT * FROM k_sessions WHERE scope = ? AND closed IS NULL ORDER BY seq",
                                          (scope,))]


def open(g: Graph, scope: str, role: str = "chat", *, label: str = "", floor: int = 0,  # noqa: A001
         adopt_idle: float = ADOPT_IDLE, now: float | None = None) -> tuple[dict[str, Any], bool]:
    """(session, adopted). `floor` is the scope's own count of sessions before this table existed."""
    if role not in ROLES:
        raise SessionError(f"role is one of {ROLES}")
    now = time.time() if now is None else now
    with g.tx():
        for s in open_sessions(g, scope):
            if s["role"] == role and now - s["active"] >= adopt_idle:
                g.db.execute("UPDATE k_sessions SET active = ?, seen = ? WHERE id = ?", (now, g.clock(), s["id"]))
                g.log("kernel", f"session {s['seq']} adopted ({role})", scope)
                return _row(g, s["id"]), True
        last = g.db.execute("SELECT max(seq) FROM k_sessions WHERE scope = ?", (scope,)).fetchone()[0] or 0
        seq = max(last, floor) + 1
        sid = f"S{seq}-{secrets.token_hex(3)}"
        g.db.execute("INSERT INTO k_sessions (id, scope, seq, role, label, opened, active, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (sid, scope, seq, role, label, now, now, g.clock()))
        g.log("kernel", f"session {seq} opened ({role})", scope)
        return _row(g, sid), False


def ack(g: Graph, sid: str, keys: list[str] | None = None) -> None:
    """The session has read these objects (None: the whole scope) as they are now."""
    with g.tx():
        now = g.clock()
        if keys is None:
            g.db.execute("UPDATE k_sessions SET seen = ?, active = ? WHERE id = ?", (now, time.time(), sid))
            g.db.execute("DELETE FROM k_seen WHERE session = ?", (sid,))
        else:
            g.db.executemany("INSERT OR REPLACE INTO k_seen VALUES (?, ?, ?)", [(sid, k, now) for k in keys])


def claim(g: Graph, s: dict[str, Any], keys: list[str] | tuple[str, ...]) -> None:
    """Refuse (Conflict) if another session wrote one of `keys` after this session last read it;
    otherwise record this write of them."""
    if not keys:
        return
    stale = []
    for k in dict.fromkeys(keys):
        w = g.db.execute("SELECT clock, session FROM k_writes WHERE scope = ? AND key = ?", (s["scope"], k)).fetchone()
        if w is None or w["session"] == s["id"]:
            continue
        seen = g.db.execute("SELECT clock FROM k_seen WHERE session = ? AND key = ?", (s["id"], k)).fetchone()
        if w["clock"] > max(s["seen"], seen[0] if seen else 0):
            other = g.db.execute("SELECT seq, role FROM k_sessions WHERE id = ?", (w["session"],)).fetchone()
            stale.append(f"{k} (session {other['seq'] if other else '?'}, {other['role'] if other else '?'})")
    if stale:
        raise Conflict(f"CONFLICT: changed by another session since this one read them: {', '.join(stale)}. "
                       "Read them again (research_show ids=… session=…), then redo the change. Nothing was written.")
    clock = g.tick()
    g.db.executemany("INSERT OR REPLACE INTO k_writes VALUES (?, ?, ?, ?)", [(s["scope"], k, clock, s["id"]) for k in keys])
    g.db.execute("UPDATE k_sessions SET active = ? WHERE id = ?", (time.time(), s["id"]))


def last_writer(g: Graph, scope: str, key: str) -> str | None:
    r = g.db.execute("SELECT session FROM k_writes WHERE scope = ? AND key = ?", (scope, key)).fetchone()
    return r[0] if r else None


def close(g: Graph, sid: str) -> None:
    with g.tx():
        g.db.execute("UPDATE k_sessions SET closed = ? WHERE id = ?", (time.time(), sid))
        g.db.execute("DELETE FROM k_seen WHERE session = ?", (sid,))


def forget_scope(g: Graph, scope: str) -> None:
    """A scope that is gone (deleted, renamed away) takes its sessions and write records with it."""
    with g.tx():
        sids = [r[0] for r in g.db.execute("SELECT id FROM k_sessions WHERE scope = ?", (scope,))]
        g.db.executemany("DELETE FROM k_seen WHERE session = ?", [(x,) for x in sids])
        g.db.execute("DELETE FROM k_sessions WHERE scope = ?", (scope,))
        g.db.execute("DELETE FROM k_writes WHERE scope = ?", (scope,))


def rescope(g: Graph, scope: str, to: str) -> None:
    """A scope renamed: its sessions (open ones keep their tokens) and write records follow it."""
    with g.tx():
        g.db.execute("UPDATE k_sessions SET scope = ? WHERE scope = ?", (to, scope))
        g.db.execute("UPDATE k_writes SET scope = ? WHERE scope = ?", (to, scope))
