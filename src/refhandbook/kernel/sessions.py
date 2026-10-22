"""Sessions: who is working on a scope, and what they have seen.

A session is one participant's span of work on a scope: a chat conversation's exchange with a
research ledger, an agent's run on it, or anything else that writes to a scope. It replaces the
turn: there is no ledger-wide "open turn" that one caller holds and every other caller collides with.

    open(scope, role)   a token, stable for the whole session (not one per write). With a label (the
                        client's own id for its conversation), an open session of the same label and
                        role is resumed: only the participant that opened a session picks it up again.
    claim(keys)         before a write: refuse it if another session changed one of these objects
                        concurrently and this session has not read it since (optimistic, per
                        object), else record it. Two sessions on different objects never block each
                        other; what closed sessions wrote before this one opened is history.
    ack(keys)           reading an object (or the whole scope) moves what this session has seen:
                        what was shown to it, nothing more.
    close()             the scope's close rules for this session (its role decides which apply).

Each session gets the scope's next number (`seq`): logs, recency ("the last 3 sessions") and
cadences ("a review every 7 sessions") count in sessions. The kernel knows no scope type by name.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from .graph import Graph, KernelError

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
         now: float | None = None) -> tuple[dict[str, Any], bool]:
    """(session, resumed). `floor` is the scope's own count of sessions before this table existed."""
    if role not in ROLES:
        raise SessionError(f"role is one of {ROLES}")
    now = time.time() if now is None else now
    with g.tx():
        for s in open_sessions(g, scope) if label else []:
            if s["role"] == role and s["label"] == label:
                g.db.execute("UPDATE k_sessions SET active = ? WHERE id = ?", (now, s["id"]))
                g.log("kernel", f"session {s['seq']} resumed ({role}, {label})", scope)
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
        if keys is None:  # a read of the whole scope: the key '*'
            g.db.execute("UPDATE k_sessions SET active = ? WHERE id = ?", (time.time(), sid))
            g.db.execute("DELETE FROM k_seen WHERE session = ?", (sid,))
            g.db.execute("INSERT INTO k_seen VALUES (?, '*', ?)", (sid, now))
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
        seen = g.db.execute("SELECT max(clock) FROM k_seen WHERE session = ? AND key IN (?, '*')",
                            (s["id"], k)).fetchone()[0] or 0
        writer_open = g.db.execute("SELECT 1 FROM k_sessions WHERE id = ? AND closed IS NULL",
                                   (w["session"],)).fetchone() is not None
        concurrent = writer_open or w["clock"] > s["seen"]  # s["seen"]: the clock when this session opened
        if concurrent and w["clock"] > seen:
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
