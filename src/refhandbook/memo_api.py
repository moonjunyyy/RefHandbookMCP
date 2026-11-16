"""The model's quick memo: short notes of its own, kept the way a cache is.

A reading that took many calls to work out (which rows of a ledger are live, where a project's working copies
are, how far a long job got) was either worked out again by the next conversation, or parked where it does
not belong: in a card (a procedure, kept current, found by everyone) or in a ledger row (a statement with a
basis). A memo is neither. It has a key and is overwritten without asking; it expires; it names the nodes it
was read from and reads STALE once one of them has changed; and nothing rests on it, because whatever it says
can be read again from those sources. A store's memos are shared by every conversation of its user.

A memo is a node (type memo, id memo:<key>) with `about` links to its sources, so the reading tools reach it
like anything else: the reverse refs of a ledger list the memos about it. What a source looked like when the
memo was written is kept with the memo (attrs.seen), and compared when the memo is read.

No MCP import here, so the server and its CLI run the same code (as entry_api)."""

from __future__ import annotations

import re
import time
from typing import Annotated, Any, Literal

from pydantic import Field

from . import research_api
from .kernel.graph import Graph
from .store import HandbookError

ACTOR = "model"
MAX_CHARS = 4000  # a memo is short: something longer is a file, a card or a document
DEFAULT_DAYS, MAX_DAYS = 14.0, 90.0
KEY_RE = re.compile(r"^[\w.:/+-]{1,80}$")
NOW = time.time  # the wall clock a memo's age and expiry are counted on
# a ledger as a source is its knowledge: the rows other than directives, criteria, plan objects and parked
# byproducts, which every session adds to without changing what the ledger holds
PROCESS_ROWS = ("directive", "criterion", "plan", "parked")


def _g() -> Graph:
    return research_api.R().k.g


def _stamp(g: Graph, node: str) -> str:
    """What a source looks like now, as a text that differs once it has changed: a card's revision, the
    number and versions of a ledger's knowledge rows, an entry's routes, otherwise the node's version."""
    n = g.get_node(node)
    if n is None:
        return "gone"
    if n["type"] == "card":
        return f"rev {n['attrs'].get('revision')}"
    if n["type"] == "ledger":
        count, versions = g.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(m.version), 0) FROM k_edges e JOIN k_nodes m ON m.id = e.dst"
            " WHERE e.src = ? AND e.type = 'contains'"
            " AND m.type IN (SELECT type FROM k_type_class WHERE class = 'row')"
            f" AND m.type NOT IN ({', '.join('?' * len(PROCESS_ROWS))})", (node, *PROCESS_ROWS)).fetchone()
        return f"{count} rows, versions {versions}"
    if n["type"] == "entry":
        count, clock = g.db.execute("SELECT COUNT(*), COALESCE(MAX(clock), 0) FROM k_edges WHERE src = ? AND type = 'ref'",
                                    (node,)).fetchone()
        return f"v{n['version']}, {count} routes, last at {clock}"
    return f"v{n['version']}"


def _ago(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= size:
            return f"{int(seconds // size)} {unit}"
    return "under a minute"


def _memos(g: Graph) -> list[dict[str, Any]]:
    ids = [r[0] for r in g.db.execute("SELECT id FROM k_nodes WHERE type = 'memo' ORDER BY updated DESC, id")]
    return [g.node(i) for i in ids]


def _sweep(g: Graph) -> None:
    """Expiry: a memo past its time is gone at the next call."""
    now = NOW()
    for n in _memos(g):
        if n["attrs"].get("expires", 0) <= now:
            g.delete_node(n["id"], actor="kernel")


def _changed(g: Graph, n: dict[str, Any]) -> list[str]:
    """The sources of a memo that no longer look as they did when it was written."""
    return [src for src, seen in (n["attrs"].get("seen") or {}).items() if _stamp(g, src) != seen]


def _state(g: Graph, n: dict[str, Any]) -> str:
    changed = _changed(g, n)
    return ("STALE (" + ", ".join(changed) + " changed)") if changed else "fresh"


def _node(g: Graph, key: str) -> dict[str, Any]:
    n = g.get_node("memo:" + key)
    if n is None:
        raise HandbookError(f"no memo {key!r} (it may have expired): memo() lists the ones there are")
    return n


def memo(
    action: Annotated[Literal["list", "read", "write", "drop"], Field(description="list: every memo, one line each; read / write / drop: one memo, by key.")] = "list",
    key: Annotated[str, Field(description="The memo's name, e.g. fourier-duality/live-rows: letters, digits and . _ : / + -")] = "",
    text: Annotated[str, Field(description="write: the note, short (it replaces the one under this key).")] = "",
    about: Annotated[list[str] | None, Field(description="write: the nodes it was read from (a ledger's id, an entry's or a row's nid, card:<id>); the memo reads STALE once one of them has changed.")] = None,
    ttl_days: Annotated[float, Field(gt=0, le=MAX_DAYS, description="write: how long it is kept.")] = DEFAULT_DAYS,
) -> str:
    """Your own quick notes, kept the way a cache is. Before working out again a reading that took many calls
    (which rows of a ledger are live, where a project's working copies are, how far a long job got), look
    here; after working one out, leave it here. A memo has a key and is overwritten without asking, it
    expires (ttl_days), and it names in `about` the nodes it was read from: once one of them has changed it
    reads STALE, and is read again from them and rewritten, or dropped. Nothing rests on a memo. It is never
    evidence; what the user said or decided is a ledger row, and a procedure is a card."""
    g = _g()
    with g.tx():
        _sweep(g)
        now = NOW()
        if action == "list":
            notes = _memos(g)
            if not notes:
                return "no memo. memo(action='write', key=…, text=…, about=[…]) leaves one."
            return "\n".join([f"{len(notes)} memo{'' if len(notes) == 1 else 's'} (a cache: any of them can be read "
                              "again from its sources)"]
                             + [f"  {n['attrs']['key']} · {_ago(now - n['attrs']['written'])} old · "
                                f"{_ago(n['attrs']['expires'] - now)} left · {_state(g, n)} · "
                                f"{(n['content'].strip().splitlines() or [''])[0][:80]}" for n in notes])
        if not KEY_RE.match(key):
            raise HandbookError(f"bad memo key {key!r}: 1–80 of letters, digits and . _ : / + -")
        if action == "read":
            n = _node(g, key)
            sources = list(n["attrs"].get("seen") or {})
            changed = _changed(g, n)
            head = (f"memo {key} · written {_ago(now - n['attrs']['written'])} ago · expires in "
                    f"{_ago(n['attrs']['expires'] - now)}" + (f" · about: {', '.join(sources)}" if sources else ""))
            state = (f"STALE: {', '.join(changed)} changed since this was written. Read "
                     f"{'it' if len(changed) == 1 else 'them'} again, then rewrite the memo or drop it."
                     if changed else "fresh: its sources are as they were." if sources
                     else "no source named: nothing says whether it still holds.")
            return f"{head}\n{state}\n\n{n['content']}"
        if action == "drop":
            _node(g, key)
            g.delete_node("memo:" + key, actor=ACTOR)
            return f"memo {key}: dropped"
        if not text.strip():
            raise HandbookError("a memo needs text")
        if len(text) > MAX_CHARS:
            raise HandbookError(f"REFUSED: {len(text)} characters; a memo holds at most {MAX_CHARS}. Something this "
                                "long is a file (files), a card or a document, with a memo pointing at it. Nothing "
                                "was written.")
        sources = list(dict.fromkeys(about or []))
        missing = [s for s in sources if g.get_node(s) is None]
        if missing:
            raise HandbookError(f"REFUSED: no node {', '.join(map(repr, missing))} to be about (a ledger's id, an "
                                "entry's or a row's nid, card:<id>). Nothing was written.")
        nid = "memo:" + key
        attrs = {"key": key, "written": now, "expires": now + ttl_days * 86400,
                 "seen": {s: _stamp(g, s) for s in sources}}
        old = g.get_node(nid)
        g.tick()
        if old is None:
            g.put_node(nid, "memo", actor=ACTOR, content=text, attrs=attrs)
        else:
            g.update_node(nid, actor=ACTOR, content=text, attrs=attrs, replace_attrs=True)
            for e in g.edges(src=nid, type_="about"):
                g.unlink(nid, "about", e["dst"], actor=ACTOR)
        for s in sources:
            g.link(nid, "about", s, actor=ACTOR)
    return (f"memo {key}: {'rewritten' if old else 'written'} ({len(text)} characters; kept {_ago(ttl_days * 86400)}"
            + (f"; about {', '.join(sources)}" if sources else "; no source named, so it cannot read stale") + ")")


WRITE_TOOLS = [memo]
