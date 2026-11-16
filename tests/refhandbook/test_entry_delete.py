"""Deleting an entry node or a tag (entry_api.delete_node): refused while it has links unless forced, only
entry nodes and tags, only the writer's own, and logged."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from refhandbook import entry_api, research_api, server
from refhandbook.entry_api import EntryError
from refhandbook.kernel.graph import Forbidden

from .test_entry_graph import _card, _id, _row, g  # noqa: F401 (g is a fixture)
from .test_research import rs  # noqa: F401 (rs is a fixture)


def test_an_empty_entry_is_deleted_and_the_log_says_what_it_was(rs, g):
    eid = _id(entry_api.entry_node("made twice by mistake"))
    assert entry_api.delete_node(eid) == f"deleted entry {eid}: made twice by mistake"
    assert g.get_node(eid) is None
    (event,) = g.db.execute("SELECT actor, ref, meta FROM k_log WHERE event = 'node.delete'").fetchall()
    assert event[0] == "model" and event[1] == eid
    assert json.loads(event[2]) == {"type": "entry", "title": "made twice by mistake", "links_out": {}, "links_in": {}}
    with pytest.raises(EntryError, match="no node"):
        entry_api.delete_node(eid)


def test_an_entry_with_links_is_refused_with_their_counts_and_force_deletes_it_with_them(rs, g):
    row, card = _row(rs), _card(rs)
    eid = _id(entry_api.entry_node("the log chart"))
    other = _id(entry_api.entry_node("a neighbouring topic"))
    entry_api.ref(eid, row, label="E1")
    entry_api.ref(eid, card)
    entry_api.ref(eid, "geo")  # the entry stands for the ledger
    entry_api.tag(eid, "structure:entry-1")
    entry_api.ref(other, eid)
    with pytest.raises(EntryError) as e:
        entry_api.delete_node(eid)
    assert "still has links (out: ref 3, tagged 1; in: ref 1)" in str(e.value) and "Nothing was deleted" in str(e.value)
    assert g.get_node(eid) is not None and len(g.edges(src=eid)) == 4
    out = entry_api.delete_node(eid, force=True)
    assert out.splitlines() == [f"deleted entry {eid}: the log chart (with 5 links)",
                                "ledger geo is no longer routed to by this entry"]
    assert g.get_node(eid) is None and not g.edges(src=eid) and not g.edges(dst=eid)
    for kept in (row, card, "geo", "tag:structure:entry-1", other):  # what it reached stays
        assert g.get_node(kept) is not None
    assert rs._row("geo", "E1")["nid"] == row  # the ledger is as it was


def test_a_tag_is_deleted_once_nothing_carries_it(rs, g):
    eid = _id(entry_api.entry_node("topic"))
    entry_api.tag(eid, "Fourier")
    with pytest.raises(EntryError, match=r"tag tag:fourier still has links \(in: tagged 1\)"):
        entry_api.delete_node("tag:fourier")
    entry_api.tag(eid, "Fourier", remove=True)
    assert entry_api.delete_node("tag:fourier") == "deleted tag tag:fourier: Fourier"
    assert g.get_node("tag:fourier") is None and g.get_node(eid) is not None


def test_rows_cards_and_ledgers_are_not_deleted_here_and_neither_is_another_writers_node(rs, g):
    row, card = _row(rs), _card(rs)
    for node, where in ((row, "a ledger row is closed in its ledger, by its status"), (card, "delete_entry"), ("geo", "research_ledger_delete")):
        with pytest.raises(EntryError, match=where):
            entry_api.delete_node(node, force=True)
        assert g.get_node(node) is not None
    g.put_node("n:users", "entry", actor="user", content="the user's own topic")
    with pytest.raises(Forbidden, match="written by user"):
        entry_api.delete_node("n:users")
    assert g.get_node("n:users") is not None


def test_the_tool_is_registered_as_a_delete_and_its_refusal_reaches_the_caller(rs, monkeypatch):
    research_api.bind(rs.hb)
    monkeypatch.setattr(server, "_handbook", rs.hb)
    eid = _id(entry_api.entry_node("topic"))
    entry_api.tag(eid, "kept")
    s = server.make()
    tools = {t.name: t for t in asyncio.run(s.list_tools())}
    assert tools["delete_node"].annotations.destructive_hint is True
    with pytest.raises(ToolError, match=r"still has links \(out: tagged 1\)"):
        asyncio.run(s.call_tool("delete_node", {"node": eid}))
    done = asyncio.run(s.call_tool("delete_node", {"node": eid, "force": True})).content[0].text
    assert done.startswith(f"deleted entry {eid}: topic (with 1 link)") and "LOOP  " in done.splitlines()[-1]
