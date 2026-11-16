"""The graph's JSON API (refhandbook/graph_api.py, /handbook/api/v1): the entry graph as nodes and links, read-only,
behind the site sign-in, each person their own store. The overview holds what joins the topics and counts the rest."""

from __future__ import annotations

import pytest

from refhandbook import research, server
from refhandbook.kernel import runtime

from .test_remote import BASE, FakeAccounts, built, cfg, client, key, site_token  # noqa: F401 — fixtures
from .test_research import Turn

G = "/handbook/api/v1"


@pytest.fixture
def accounts():
    return FakeAccounts({"moon", "kim"}, admins=set())


def get(c, path, uid="moon", **params):
    return c.get(G + path, params=params, headers={"X-Auth-Token": site_token(c.key, uid), "Origin": BASE})


def _two_topics(uid="moon"):
    """Two ledgers, each an entry: geo routes to its two rows, a card and the other entry; num routes to its row and
    to geo's first row; a row of each carries the tag charts."""
    hb = server._user_store(uid)
    g = runtime.attach(hb).g
    r = research.Research(hb)
    for ledger, question, rows in (("geo", "the log chart", [("the object", ""), ("its chart", "E1")]),
                                   ("num", "the natural numbers", [("the count", "")])):
        r.init(ledger, question)
        t = Turn(r, ledger)
        t.begin()
        for content, dep in rows:
            t.add("E", content, "user", "established", evidence="given", dep=dep)
        t.end(idle="test")
    e1, e2, n1 = r._row("geo", "E1")["nid"], r._row("geo", "E2")["nid"], r._row("num", "E1")["nid"]
    hb.save_entry(title="Geo: where things are", kind="reference", condition="picked up again", body="notes")
    for node, title in (("n:geo", "the log chart"), ("n:num", "the natural numbers")):
        g.put_node(node, "entry", actor="model", content=title)
    for tag in ("charts", "structure:entry-1"):
        g.put_node("tag:" + tag, "tag", actor="model", content=tag)
    for src, dst, label in (("n:geo", "geo", ""), ("n:geo", e1, "E1"), ("n:geo", e2, "E2"), ("n:geo", "card:geo-where-things-are", ""),
                            ("n:geo", "n:num", ""), ("n:num", "num", ""), ("n:num", n1, "E1"), ("n:num", e1, "the object")):
        g.link(src, "ref", dst, actor="model", attrs={"label": label} if label else {})
    for src, tag in (("n:geo", "structure:entry-1"), ("n:num", "structure:entry-1"), (e2, "charts"), (n1, "charts")):
        g.link(src, "tagged", "tag:" + tag, actor="model")
    return e1, e2, n1


def test_the_graph_is_behind_the_sign_in_and_each_person_reads_their_own(client):
    _two_topics()
    for path in ("/graph", "/graph/entry?id=n:geo", "/node?id=n:geo"):
        assert client.get(G + path).status_code == 401
    assert get(client, "/graph", uid="kim").json() == {"nodes": [], "links": []}
    assert get(client, "/node", uid="kim", id="n:geo").status_code == 404


def test_the_overview_holds_the_topics_and_what_joins_them_and_counts_the_rest(client):
    e1, e2, n1 = _two_topics()
    seen = get(client, "/graph").json()
    nodes = {n["id"]: n for n in seen["nodes"]}
    assert set(nodes) == {"n:geo", "n:num", "card:geo-where-things-are", "tag:charts", e1}  # not e2, n1: one topic's own
    assert (nodes["n:geo"]["type"], nodes["n:geo"]["title"], nodes["n:geo"]["n"], nodes["n:geo"]["ledger"]) == ("entry", "the log chart", 2, "geo")
    assert (nodes["n:num"]["n"], nodes["n:num"]["ledger"]) == (2, "num")
    assert nodes[e1]["type"] == "row" and nodes[e1]["kind"] == "object" and nodes[e1]["shared"] is True
    assert nodes["card:geo-where-things-are"]["title"] == "Geo: where things are" and nodes["tag:charts"]["type"] == "tag"
    assert {(x["s"], x["t"], x["kind"]) for x in seen["links"]} == {
        ("n:geo", "n:num", "route"), ("n:geo", "card:geo-where-things-are", "card"), ("n:geo", e1, "shared"),
        ("n:num", e1, "shared"), ("n:geo", "tag:charts", "tag"), ("n:num", "tag:charts", "tag")}  # the structure mark joins nothing


def test_an_entry_opens_into_its_rows_their_basis_links_and_their_tags(client):
    e1, e2, n1 = _two_topics()
    seen = get(client, "/graph/entry", id="n:geo").json()
    nodes = {n["id"]: n for n in seen["nodes"]}
    assert seen["id"] == "n:geo" and set(nodes) == {e1, e2, "tag:charts"}
    assert (nodes[e2]["type"], nodes[e2]["kind"], nodes[e2]["state"], nodes[e2]["label"]) == ("row", "object", "established", "E2")
    assert nodes[e2]["title"] == "E2 · its chart" and nodes[e1]["mark"] is False
    assert {(x["s"], x["t"], x["kind"]) for x in seen["links"]} == {(e2, e1, "basis"), (e2, "tag:charts", "tag")}
    assert get(client, "/graph/entry", id=e1).status_code == 404  # a row is not an entry
    assert get(client, "/graph/entry", id="n:nothing").status_code == 404


def test_a_node_says_what_it_is_and_nothing_is_written(client):
    e1, _e2, _n1 = _two_topics()
    g = runtime.attach(server._user_store("moon")).g
    before = g.db.execute("SELECT COUNT(*), COALESCE(SUM(version), 0) FROM k_nodes").fetchone()[:]
    one = get(client, "/node", id=e1).json()
    assert (one["type"], one["state"], one["name"], one["content"], one["cut"]) == ("object", "established", "geo/E1", "the object", False)
    assert one["in"]["ref"] == 2 and one["in"]["contains"] == 1 and one["in"]["dep_ref"] == 1  # two entries, its ledger, the row that rests on it
    assert get(client, "/node", id="n:nothing").status_code == 404
    get(client, "/graph")
    get(client, "/graph/entry", id="n:geo")
    assert g.db.execute("SELECT COUNT(*), COALESCE(SUM(version), 0) FROM k_nodes").fetchone()[:] == before
