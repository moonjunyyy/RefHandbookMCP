"""The compact read (query_api.query): one SELECT over the graph laid out as tables; it changes nothing and
reads nothing but those tables."""

import asyncio
import sqlite3

import pytest

from refhandbook import Handbook, entry_api, query_api, research, research_api, server
from refhandbook.store import HandbookError

from .test_entry_graph import _id, g  # noqa: F401 (g is a fixture)
from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


def _ledger(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "the object\nits second line", "user", "established", evidence="followed")
    t.add("E", "an old form of it", "user", "history", evidence="kept for the record")
    t.add("A", "the chart is smooth", "user", "on", evidence="given")
    t.end(idle="test")


def _rows(out: str) -> list[str]:
    return out.splitlines()[1:]


def test_the_rows_of_a_ledger_are_read_in_one_call(rs, g):
    _ledger(rs)
    out = query_api.query("SELECT id, sec, status, finished, head FROM rows WHERE ledger = 'geo' ORDER BY id")
    assert out.splitlines() == ["id\tsec\tstatus\tfinished\thead", "A1\tA\ton\t0\tthe chart is smooth",
                                "E1\tE\testablished\t0\tthe object", "E2\tE\thistory\t1\tan old form of it", "3 rows"]
    assert _rows(query_api.query("SELECT nid, name FROM rows r JOIN nodes USING (nid) WHERE r.id = 'E1'")) == [
        f"{rs._row('geo', 'E1')['nid']}\tgeo/E1", "1 row"]


def test_a_join_gives_what_an_entry_routes_to_and_what_no_entry_routes_to_yet(rs, g):
    _ledger(rs)
    eid, e1 = _id(entry_api.entry_node("the log chart")), rs._row("geo", "E1")["nid"]
    entry_api.ref(eid, e1, label="E1")
    entry_api.bookmark(eid, e1)
    entry_api.tag(eid, "charts")
    routed = query_api.query("SELECT r.id, l.label, l.bookmark FROM links l JOIN rows r ON r.nid = l.dst "
                             f"WHERE l.src = '{eid}' AND l.type = 'ref'")
    assert _rows(routed) == ["E1\tE1\t1", "1 row"]
    todo = query_api.query("SELECT id FROM rows WHERE ledger = 'geo' AND NOT finished "
                           "AND nid NOT IN (SELECT dst FROM links WHERE type = 'ref') ORDER BY id")
    assert _rows(todo) == ["A1", "1 row"]  # E1 is routed to, E2 is finished
    tagged = query_api.query("WITH t AS (SELECT src FROM links WHERE type = 'tagged' AND dst = 'tag:charts') "
                             "SELECT n.type, n.head FROM nodes n JOIN t ON t.src = n.nid")
    assert _rows(tagged) == ["entry\tthe log chart", "1 row"]
    reach = query_api.query("WITH RECURSIVE reach(nid) AS (SELECT '" + eid + "' UNION SELECT l.dst FROM links l "
                            "JOIN reach ON l.src = reach.nid WHERE l.type IN ('ref', 'tagged')) SELECT count(*) AS n FROM reach")
    assert _rows(reach) == ["3", "1 row"]  # the entry, the row it routes to, its tag


def test_cards_and_verdicts_are_tables_too(rs, g):
    rs.hb.save_entry(title="Disk full", condition="ENOSPC", items=[{"text": "df -h"}])
    assert _rows(query_api.query("SELECT id, kind, rev, nid FROM cards WHERE id = 'disk-full'")) == [
        "disk-full\tchecklist\t1\tcard:disk-full", "1 row"]
    assert _rows(query_api.query("SELECT type, head FROM nodes WHERE nid = 'card:disk-full'")) == ["card\tDisk full", "1 row"]
    assert _rows(query_api.query("SELECT count(*) AS n FROM verdicts")) == ["0", "1 row"]
    listed = query_api.query("tables")
    assert all(f"{name}(" in listed for name in query_api.TABLES) and "finished is 1 for done" in listed


@pytest.mark.parametrize("q, why", [
    ("DELETE FROM k_nodes", "one SELECT"),
    ("PRAGMA table_info(k_nodes)", "one SELECT"),
    ("SELECT * FROM rows; DELETE FROM k_nodes", "one statement"),
    ("SELECT * FROM k_sessions", "prohibited"),
    ("SELECT * FROM rl_rows", "prohibited"),
    ("SELECT count(*) FROM k_sessions", "prohibited|not authorized"),
    ("SELECT name FROM sqlite_master", "prohibited"),
    ("WITH x AS (SELECT 1) INSERT INTO k_meta VALUES ('a', 'b')", "not authorized"),
    ("SELECT load_extension('x')", "not authorized"),
])
def test_nothing_is_changed_and_nothing_else_is_read(rs, g, q, why):
    before = g.db.execute("SELECT count(*) FROM k_nodes").fetchone()[0]
    with pytest.raises(HandbookError, match=why):
        query_api.query(q)
    assert g.db.execute("SELECT count(*) FROM k_nodes").fetchone()[0] == before
    entry_api.entry_node("the store's own connection writes as before")  # the authorizer went with the query


def test_rows_and_cells_are_cut_and_the_result_says_so(rs, g):
    _ledger(rs)
    out = query_api.query("SELECT id, content FROM rows WHERE ledger = 'geo' ORDER BY id", limit=2, width=12).splitlines()
    assert out[1] == "A1\tthe chart i…" and out[-1].startswith("2 rows; there are more")
    assert _rows(query_api.query("SELECT content FROM rows WHERE id = 'E1'"))[0] == "the object ⏎ its second line"


def test_a_query_that_runs_away_is_stopped(rs, g, monkeypatch):
    monkeypatch.setattr(query_api, "SECONDS", 0.2)
    with pytest.raises(HandbookError, match="stopped after 0.2 s"):
        query_api.query("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT count(*) FROM n")


def test_a_store_in_a_file_is_read_through_a_read_only_connection_that_sees_each_write(tmp_path):
    hb = Handbook(tmp_path / "handbook.db")
    research.ensure_cards(hb)
    research_api.bind(hb)
    research_api.R().init("geo", "vector EL of the proxy Lagrangian")
    count = "SELECT count(*) AS n FROM nodes WHERE type = 'entry'"
    assert _rows(query_api.query(count)) == ["0", "1 row"]
    assert hb._query_db is not hb.db
    entry_api.entry_node("made after the reading connection was opened")
    assert _rows(query_api.query(count)) == ["1", "1 row"]
    with pytest.raises(sqlite3.Error):
        hb._query_db.execute("DELETE FROM k_nodes")
    with pytest.raises(HandbookError, match="prohibited"):
        query_api.query("SELECT * FROM k_sessions")
    hb._query_db.close()
    hb.close()


def test_the_tool_is_a_read(rs, monkeypatch):
    research_api.bind(rs.hb)
    monkeypatch.setattr(server, "_handbook", rs.hb)
    s = server.make()
    tools = {t.name: t for t in asyncio.run(s.list_tools())}
    assert tools["query"].annotations.read_only_hint is True
    out = asyncio.run(s.call_tool("query", {"q": "SELECT count(*) AS n FROM rows"})).content[0].text
    assert out.splitlines() == ["n", "0", "1 row"]  # and no LOOP line: a read
