"""Reading (docs/entry-graph.md §3, stage 2, second slice): refs and open_node over every node."""

import re

import pytest

from refhandbook import entry_api, research_api
from refhandbook.entry_api import EntryError

from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


@pytest.fixture
def g(rs):
    research_api.bind(rs.hb)
    return research_api.R().k.g


def _id(out: str) -> str:
    return out.split()[1].rstrip(":")


def _rows(rs, n):
    t = Turn(rs)
    t.begin(1)
    for i in range(n):
        t.add("E", f"object number {i + 1}", "user", "established", evidence="followed")
    t.end(idle="test")
    return [rs._row("geo", f"E{i + 1}")["nid"] for i in range(n)]


def _listed(out: str) -> list[str]:
    return re.findall(r"^  (\S+)  ", out, re.M)


def _state(g):
    q = lambda s: g.db.execute(s).fetchone()  # noqa: E731
    return q("SELECT COUNT(*), MAX(clock) FROM k_edges"), q("SELECT COUNT(*), MAX(updated) FROM k_nodes"), q("SELECT COUNT(*) FROM k_log")


def test_an_entrys_refs_come_back_as_ids_and_titles_newest_first_and_page_by_cursor(rs, g):
    a, b, c = _rows(rs, 3)
    eid = _id(entry_api.entry_node("topic"))
    for nid, label in ((a, "E1"), (b, "E2"), (c, "E3")):
        entry_api.ref(eid, nid, label=label)
    out = entry_api.refs(eid, k=2)
    assert out.splitlines()[0].endswith("1-2 of 3") and _listed(out) == [c, b]
    assert f"  {c}  E3 · object number 3" in out and "ref (2)" in out and "next: cursor o:2" in out
    assert _listed(entry_api.refs(eid, k=2, cursor="o:2")) == [a]


def test_a_link_is_one_link_seen_from_both_ends_and_reading_changes_nothing(rs, g):
    (a,) = _rows(rs, 1)
    eid = _id(entry_api.entry_node("topic"))
    entry_api.ref(eid, a, label="E1")
    before = _state(g)
    assert eid in _listed(entry_api.refs(a, "in", types=["ref"]))
    assert a in _listed(entry_api.refs(eid, "out"))
    assert "ref_of" not in entry_api.refs(a, "in", types=["ref_of"]) and eid in _listed(entry_api.refs(a, "in", types=["ref_of"]))
    entry_api.open_node(a)
    entry_api.open_node(eid)
    entry_api.refs(eid, order="random")
    assert _state(g) == before


def test_bookmarks_come_first_for_the_entry_that_set_them_only(rs, g):
    a, b, c = _rows(rs, 3)
    one, two = _id(entry_api.entry_node("one")), _id(entry_api.entry_node("two"))
    for e in (one, two):
        for nid in (a, b, c):
            entry_api.ref(e, nid)
    entry_api.bookmark(one, a)
    assert _listed(entry_api.refs(one, order="bookmarked")) == [a, c, b]
    assert _listed(entry_api.refs(two, order="bookmarked")) == [c, b, a]
    assert f"  {a}  " in entry_api.refs(one, order="bookmarked") and " *" in entry_api.refs(one, order="bookmarked").splitlines()[2]


def test_random_is_repeatable_by_its_seed(rs, g):
    rows = _rows(rs, 6)
    eid = _id(entry_api.entry_node("topic"))
    for nid in rows:
        entry_api.ref(eid, nid)
    out = entry_api.refs(eid, order="random", k=6)
    seed = int(re.search(r"seed (\d+)", out).group(1))
    assert _listed(entry_api.refs(eid, order="random", k=6, seed=seed)) == _listed(out)
    assert sorted(_listed(out)) == sorted(rows)


def test_open_and_refs_reach_cards_ledger_rows_and_tags_alike(rs, g):
    (a,) = _rows(rs, 1)
    card = "card:" + rs.hb.save_entry(title="A card to read", condition="when testing", objective="to be read")["id"]
    entry_api.tag(a, "shared word")
    entry_api.tag(card, "shared word")
    assert set(_listed(entry_api.refs("tag:shared-word", "in"))) == {a, card}
    assert "A card to read" in entry_api.refs("tag:shared-word", "in")
    assert "geo/E1 · object number 1" in entry_api.refs("tag:shared-word", "in")
    opened = entry_api.open_node(a)
    assert opened.startswith("object") and "geo/E1 · object number 1" in opened and "tagged 1" in opened
    assert "contains 1" in opened  # the ledger reaches its row
    assert "card" in entry_api.open_node(card).splitlines()[0]
    with pytest.raises(EntryError, match="no node"):
        entry_api.open_node("n:nothing")
    with pytest.raises(EntryError, match="not an entry node"):
        entry_api.refs(a, entry=a)
