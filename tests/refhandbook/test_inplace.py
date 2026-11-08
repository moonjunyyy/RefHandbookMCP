"""A ledger's graph image is changed in place after each write (docs/entry-graph.md §8, stage 2, third
slice): what a redraw would make, applied as differences; unchanged nodes keep their history."""

import json

import pytest

from refhandbook import entry_api, research_api
from refhandbook.kernel import migrate

from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


@pytest.fixture
def g(rs):
    research_api.bind(rs.hb)
    return research_api.R().k.g


def _node(g, nid):
    return dict(g.db.execute("SELECT * FROM k_nodes WHERE id = ?", (nid,)).fetchone())


def test_a_row_that_stays_keeps_its_node_and_a_new_row_is_its_writers(rs, g):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "the first object", "user", "established", evidence="followed")
    t.end(idle="test")
    e1 = rs._row("geo", "E1")["nid"]
    before = _node(g, e1)
    t = Turn(rs)
    t.begin(2)
    t.add("E", "the second object", "user", "established", evidence="followed")
    t.end(idle="test")
    after = _node(g, e1)
    assert (after["version"], after["created"], after["updated"], after["author"]) == \
        (before["version"], before["created"], before["updated"], before["author"])
    e2 = _node(g, rs._row("geo", "E2")["nid"])
    assert e2["author"] == "model" and e2["created"] > before["created"]


def test_a_changed_row_is_changed_in_place(rs, g):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "an object", "user", "established", evidence="followed")
    t.end(idle="test")
    nid = rs._row("geo", "E1")["nid"]
    before = _node(g, nid)
    t = Turn(rs)
    t.begin(2)
    t.set("E1", "content", "the object, said better")
    t.end(idle="test")
    after = _node(g, nid)
    assert after["content"] == "the object, said better" and after["version"] == before["version"] + 1
    assert after["created"] == before["created"] and after["author"] == before["author"] and after["updated"] > before["updated"]


def test_the_image_in_place_is_the_image_a_redraw_makes(rs, g):
    t = Turn(rs)
    t.begin(1)
    t.add("A", "a premise", "user", "on")
    t.add("E", "an object", "user", "established", evidence="followed")
    t.add("H", "a claim on them", "model", "proposed", evidence="closure: U1", dep="A1 E1")
    t.end(idle="test")
    t = Turn(rs)
    t.begin(2)
    t.set("E1", "content", "the object, changed")
    t.dispose("H1", "E1", "UNAFFECTED", why="wording only")
    t.end(idle="test")
    keep = lambda nodes, edges: ({k: {f: (json.loads(v[f]) if f == "attrs" else v[f]) for f in migrate.NODE_FIELDS}  # noqa: E731
                                 for k, v in nodes.items()}, {k: (json.loads(v["attrs"]), v["origin"]) for k, v in edges.items()})
    now = keep(*migrate._image(g, "geo"))
    redraw = keep(*migrate._target(g, "geo", rs.export("geo", include_log=False), rs.db))
    for nodes in (now[0], redraw[0]):  # what the runtime derives onto the ledger node after a sync
        nodes["geo"]["attrs"] = {k: v for k, v in nodes["geo"]["attrs"].items() if not k.startswith("derived_")}
    assert now == redraw


def test_an_entrys_refs_and_tags_need_no_keeping_aside(rs, g):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "an object", "user", "established", evidence="followed")
    t.end(idle="test")
    nid = rs._row("geo", "E1")["nid"]
    eid = entry_api.entry_node("topic").split()[1].rstrip(":")
    entry_api.ref(eid, nid, label="E1")
    entry_api.tag(nid, "kept")
    edges = sorted((e["src"], e["type"], e["dst"], e["clock"]) for e in g.edges(src=eid) + g.edges(src=nid, type_="tagged"))
    t = Turn(rs)
    t.begin(2)
    t.set("E1", "content", "changed, so geo is written again")
    t.end(idle="test")
    assert sorted((e["src"], e["type"], e["dst"], e["clock"]) for e in g.edges(src=eid) + g.edges(src=nid, type_="tagged")) == edges
