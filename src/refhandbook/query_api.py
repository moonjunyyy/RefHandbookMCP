"""The compact read: one SELECT over the graph.

The reading tools open one node or list one node's links (entry_api). A question about many nodes at once
(which rows of a ledger are unfinished and not yet routed to, what two entries share, the state of every row
by id) took one call per node. `query` answers it in one call, and its language is not a new one: SQLite's
SELECT, over five tables that lay the store out for reading.

Nothing is stored for those tables: each is a WITH clause put in front of the query. The query changes
nothing and reads nothing else. An authorizer allows SELECT, reads of the store's tables named in READABLE
and the functions in FUNCTIONS, and denies everything else: the other tables of the store (sessions, keys,
tokens, the ledger tables), PRAGMA, ATTACH, and every write. A store in a file is read through a second
connection opened read-only.

No MCP import here, so the server and its CLI run the same code (as entry_api)."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Annotated
from urllib.parse import quote

from pydantic import Field

from . import research_api
from .store import HandbookError

SECONDS = 5.0  # a query that runs longer is stopped
CHARS = 60_000  # and a result longer than this is cut at a row
_HEAD = "substr({0}, 1, min(80, CASE instr({0}, char(10)) WHEN 0 THEN 80 ELSE instr({0}, char(10)) - 1 END))"
_IN_LEDGER = ("FROM main.k_nodes n JOIN main.k_edges e ON e.dst = n.id AND e.type = 'contains' "
              "JOIN main.k_nodes l ON l.id = e.src AND l.type = 'ledger'")

# name -> (columns, what it holds, the SELECT it stands for). `main.` keeps a table of ours from shadowing a
# stored one of the same name.
TABLES: dict[str, tuple[str, str, str]] = {
    "nodes": ("nid, type, state, name, head, content, author, origin, updated",
              "every node: a ledger row, a card (card:<id>), an entry, a tag (tag:<name>), a ledger …; "
              "head is the first line of content, name a row's <ledger>/<id>",
              "SELECT id, type, state, coalesce(json_extract(attrs, '$.xref'), ''), " + _HEAD.format("content")
              + ", content, author, origin, updated FROM main.k_nodes"),
    "links": ("src, type, dst, label, bookmark, clock",
              "every link: ref (an entry routes to a node, by label), tagged, contains (a ledger holds a row), "
              "dep_ref (a row rests on another), a card relation …; clock orders them by when they were made",
              "SELECT src, type, dst, coalesce(json_extract(attrs, '$.label'), ''), "
              "coalesce(json_extract(attrs, '$.bookmark'), 0), clock FROM main.k_edges"),
    "rows": ("ledger, id, sec, status, finished, origin, head, content, evidence, dep, nid, updated",
             "the rows of the ledgers; finished is 1 for done, dropped, superseded, refuted and history",
             "SELECT e.src, json_extract(n.attrs, '$.rid'), json_extract(n.attrs, '$.sec'), n.state, "
             "EXISTS (SELECT 1 FROM main.k_state_class c WHERE c.type = n.type AND c.state = n.state "
             "AND c.class = 'finished'), n.origin, " + _HEAD.format("n.content") + ", n.content, "
             "json_extract(n.attrs, '$.evidence'), json_extract(n.attrs, '$.dep'), n.id, n.updated "
             + _IN_LEDGER + " WHERE n.type IN (SELECT type FROM main.k_type_class WHERE class = 'row')"),
    "verdicts": ("ledger, claim, config, verdict, nid",
                 "the verdict of a claim (its id) under a configuration",
                 "SELECT e.src, json_extract(n.attrs, '$.claim'), json_extract(n.attrs, '$.config'), n.state, n.id "
                 + _IN_LEDGER + " WHERE n.type = 'verdict'"),
    "cards": ("id, kind, title, rev, condition, objective, body, updated, nid",
              "the handbook cards; nid is the card's node (card:<id>)",
              "SELECT id, kind, title, revision, condition, objective, body, updated_at, 'card:' || id FROM main.entries"),
}
PRELUDE = ", ".join(f"{name}({cols}) AS ({select})" for name, (cols, _what, select) in TABLES.items())
READABLE = {"k_nodes", "k_edges", "k_types", "k_type_class", "k_state_class", "entries"}
FUNCTIONS = frozenset("""-> ->> abs avg char coalesce concat concat_ws count date datetime dense_rank first_value
    format glob group_concat hex ifnull iif instr json_array_length json_extract json_type julianday lag last_value
    lead length like lower ltrim max min nullif printf quote rank replace round row_number rtrim sign strftime
    string_agg substr substring sum time total trim typeof unicode unixepoch upper""".split())
_LEAD = re.compile(r"\s*(with\s+recursive|with|select)\b", re.I)
HINT = ("query takes one SELECT (WITH … SELECT too) over " + ", ".join(TABLES)
        + "; it changes nothing and reads nothing else. query('tables') lists their columns.")


def _authorizer(db: sqlite3.Connection):  # noqa: ANN202
    """SELECT, the readable tables and the listed functions; nothing else. A table read with no column named
    (count(*)) is reported by its bare name, a table of the query's own (a WITH clause) included: such a
    name is allowed unless the store has a table called that."""
    stored = {r[0] for r in db.execute("SELECT name FROM sqlite_master UNION SELECT name FROM sqlite_temp_master")}
    stored |= {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}

    def allow(action: int, a: str | None, b: str | None, _db: str | None, _inner: str | None) -> int:
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and (a in READABLE or (b == "" and a not in stored)):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (b or "").lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return allow


def _connection(hb: object) -> sqlite3.Connection:
    """The connection a query runs on. A store in a file gets a second connection, opened read-only and kept
    with the store; an in-memory store has only its own. Either carries the authorizer for the length of a
    query."""
    if hb.path == ":memory:":  # type: ignore[attr-defined]
        return hb.db  # type: ignore[attr-defined]
    db = getattr(hb, "_query_db", None)
    if db is None:
        db = sqlite3.connect(f"file:{quote(hb.path)}?mode=ro", uri=True, check_same_thread=False, timeout=5)  # type: ignore[attr-defined]
        hb._query_db = db  # type: ignore[attr-defined]
    return db


def _cell(value: object, width: int) -> str:
    if value is None:
        return ""
    s = str(value).replace("\t", " ").replace("\r", "").replace("\n", " ⏎ ")
    return s if len(s) <= width else s[: width - 1] + "…"


def tables() -> str:
    return "\n".join(f"{name}({cols})\n    {what}" for name, (cols, what, _select) in TABLES.items())


def query(
    q: Annotated[str, Field(description="One SELECT, in SQLite's syntax; 'tables' lists the tables and their columns.")],
    limit: Annotated[int, Field(ge=1, le=1000, description="How many rows to return at most.")] = 100,
    width: Annotated[int, Field(ge=10, le=4000, description="Where a cell is cut, in characters.")] = 120,
) -> str:
    """Read the graph with one SELECT (SQLite syntax: JOIN, GROUP BY, WITH RECURSIVE). Reading only: it can
    change nothing. Use it for a question about many nodes at once; open_node reads one node whole. Tables:
    rows(ledger, id, sec, status, finished, origin, head, content, evidence, dep, nid, updated): ledger rows; finished = 1 for done, dropped, superseded, refuted, history
    nodes(nid, type, state, name, head, content, author, origin, updated): every node (row, card, entry, tag, ledger …)
    links(src, type, dst, label, bookmark, clock): every link (ref, tagged, contains, dep_ref, card relations …)
    verdicts(ledger, claim, config, verdict, nid) · cards(id, kind, title, rev, condition, objective, body, updated, nid)
    Example, the unfinished rows of a ledger that no entry routes to:
    SELECT id, status, nid, head FROM rows WHERE ledger = 'geo' AND NOT finished AND nid NOT IN (SELECT dst FROM links WHERE type = 'ref')
    The result is tab-separated under a header line, cells cut at `width`, rows at `limit`."""
    if q.strip().lower() in ("", "tables", "help"):
        return tables()
    m = _LEAD.match(q)
    if m is None:
        raise HandbookError("query: " + HINT)
    lead = m.group(1).lower()
    sql = (f"WITH {PRELUDE} {q}" if lead == "select"
           else ("WITH RECURSIVE " if "recursive" in lead else "WITH ") + PRELUDE + ", " + q[m.end():])
    r = research_api.R()
    r.k  # the graph is attached (and current) before it is read
    db = _connection(r.hb)
    deadline = time.monotonic() + SECONDS
    db.set_authorizer(_authorizer(db))
    db.set_progress_handler(lambda: time.monotonic() > deadline, 2000)
    try:
        cur = db.execute(sql)
        cols = [d[0] for d in cur.description]
        got = cur.fetchmany(limit + 1)
        cur.close()
    except (sqlite3.Error, sqlite3.Warning) as e:
        if "interrupt" in str(e).lower():
            raise HandbookError(f"query: stopped after {SECONDS:g} s. Narrow it (a WHERE on ledger, a bound on a "
                                "recursion).") from e
        raise HandbookError(f"query: {e}. " + HINT) from e
    finally:
        db.set_progress_handler(None, 0)
        db.set_authorizer(None)
    lines, size = ["\t".join(cols)], 0
    for row in got[:limit]:
        line = "\t".join(_cell(v, width) for v in row)
        size += len(line) + 1
        if size > CHARS:
            break
        lines.append(line)
    shown = len(lines) - 1
    more = "; there are more: narrow the WHERE, select fewer columns, or page with LIMIT … OFFSET" if shown < len(got) else ""
    return "\n".join(lines + [f"{shown} row{'' if shown == 1 else 's'}{more}"])


READ_TOOLS = [query]
