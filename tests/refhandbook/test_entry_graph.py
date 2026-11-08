"""Entry nodes and their refs (docs/entry-graph.md §8, stage 2, first slice): written by their writer,
kept when the ledger or the cards they reach are drawn again."""

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


def _row(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "the object", "user", "established", evidence="followed")
    t.end(idle="test")
    return rs._row("geo", "E1")["nid"]


def _card(rs):
    e = rs.hb.save_entry(title="A card an entry routes to", condition="when testing", objective="to be reached")
    return f"card:{e['id']}"


def test_an_entry_routes_to_a_row_and_a_card_and_each_write_is_its_writers(rs, g):
    row, card = _row(rs), _card(rs)
    eid = _id(entry_api.entry_node("the log chart", question="what does it carry?"))
    n = g.get_node(eid)
    assert n["type"] == "entry" and n["author"] == "model" and n["attrs"]["question"] == "what does it carry?"
    entry_api.ref(eid, row, label="E1")
    entry_api.ref(eid, card)
    refs = {e["dst"]: e for e in g.edges(src=eid, type_="ref")}
    assert set(refs) == {row, card} and {e["origin"] for e in refs.values()} == {"model"}
    assert refs[row]["attrs"] == {"label": "E1"}
    entry_api.unref(eid, card)
    assert [e["dst"] for e in g.edges(src=eid, type_="ref")] == [row]


def test_a_bookmark_and_a_new_label_keep_when_the_ref_was_made(rs, g):
    row = _row(rs)
    eid = _id(entry_api.entry_node("topic"))
    entry_api.ref(eid, row, label="E1")
    (before,) = g.edges(src=eid, type_="ref")
    entry_api.bookmark(eid, row)
    entry_api.ref(eid, row, label="the object")
    (after,) = g.edges(src=eid, type_="ref")
    assert after["attrs"] == {"label": "the object", "bookmark": True} and after["clock"] == before["clock"]
    entry_api.bookmark(eid, row, on=False)
    assert g.edges(src=eid, type_="ref")[0]["attrs"] == {"label": "the object"}


def test_a_tag_is_a_node_and_whatever_carries_it_is_its_reverse_refs(rs, g):
    row, card = _row(rs), _card(rs)
    entry_api.tag(row, "Log chart")
    entry_api.tag(card, "log  chart")
    assert "already" in entry_api.tag(row, "LOG CHART")
    t = g.get_node("tag:log-chart")
    assert t["type"] == "tag" and t["author"] == "model"
    assert {e["src"] for e in g.edges(dst="tag:log-chart", type_="tagged")} == {row, card}
    entry_api.tag(row, "log chart", remove=True)
    assert [e["src"] for e in g.edges(dst="tag:log-chart", type_="tagged")] == [card]


def test_refs_and_tags_survive_the_ledger_and_the_cards_being_drawn_again(rs, g):
    row, card = _row(rs), _card(rs)
    eid = _id(entry_api.entry_node("topic"))
    entry_api.ref(eid, row, label="E1")
    entry_api.ref(eid, card)
    entry_api.tag(row, "kept")
    before = {(e["src"], e["type"], e["dst"]): (e["origin"], e["clock"]) for e in g.edges(src=eid) + g.edges(src=row, type_="tagged")}
    t = Turn(rs)
    t.begin(2)
    t.add("E", "another object draws geo again", "user", "established", evidence="followed")
    t.end(idle="test")
    rs.hb.save_entry(id=card.split(":", 1)[1], body="changed, so the cards are drawn again")
    after = {(e["src"], e["type"], e["dst"]): (e["origin"], e["clock"]) for e in g.edges(src=eid) + g.edges(src=row, type_="tagged")}
    assert after == before and len(after) == 3


def test_what_an_entry_refuses(rs, g):
    row = _row(rs)
    eid = _id(entry_api.entry_node("topic"))
    with pytest.raises(EntryError, match="not an entry node"):
        entry_api.ref(row, eid)
    with pytest.raises(EntryError, match="no node"):
        entry_api.ref(eid, "n:nothing")
    with pytest.raises(EntryError, match="no ref"):
        entry_api.unref(eid, row)
    with pytest.raises(EntryError, match="make the ref first"):
        entry_api.bookmark(eid, row)
    with pytest.raises(EntryError, match="bad tag"):
        entry_api.tag(row, "   ")
