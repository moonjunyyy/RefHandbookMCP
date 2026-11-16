"""The model's quick memo (memo_api): keyed and overwritten, expiring, stale once a source has changed, and
never more than a note."""

import asyncio

import pytest

from refhandbook import entry_api, memo_api, research_api, server
from refhandbook.store import HandbookError

from .test_entry_graph import _id, g  # noqa: F401 (g is a fixture)
from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(memo_api, "NOW", lambda: now[0])
    return now


def _session(rs, *rows):
    t = Turn(rs)
    t.begin()
    for sec, content, status in rows:
        t.add(sec, content, "user", status, evidence="given")
    t.end(idle="test")


def test_a_memo_is_written_read_listed_and_rewritten_under_its_key(rs, g, clock):
    assert memo_api.memo().startswith("no memo")
    text = "the working copy is /work/geo\nbranch topic/x"
    assert memo_api.memo("write", "geo/where", text) == (
        f"memo geo/where: written ({len(text)} characters; kept 14 d; no source named, so it cannot read stale)")
    n = g.get_node("memo:geo/where")
    assert n["type"] == "memo" and n["author"] == "model" and n["content"] == text
    clock[0] += 3 * 3600
    assert memo_api.memo("read", "geo/where") == (
        "memo geo/where · written 3 h ago · expires in 13 d\n"
        "no source named: nothing says whether it still holds.\n\n" + text)
    assert memo_api.memo().splitlines() == [
        "1 memo (a cache: any of them can be read again from its sources)",
        "  geo/where · 3 h old · 13 d left · fresh · the working copy is /work/geo"]
    assert memo_api.memo("write", "geo/where", "moved to /work/geo2").startswith("memo geo/where: rewritten (")
    assert memo_api.memo("read", "geo/where").endswith("\n\nmoved to /work/geo2")
    assert g.db.execute("SELECT count(*) FROM k_nodes WHERE type = 'memo'").fetchone()[0] == 1


def test_a_memo_reads_stale_once_its_ledger_holds_something_else_and_fresh_again_when_rewritten(rs, g):
    _session(rs, ("E", "the object", "established"))
    memo_api.memo("write", "geo/live", "E1 is the only live row", about=["geo"])
    assert "fresh: its sources are as they were." in memo_api.memo("read", "geo/live")
    assert [e["dst"] for e in g.edges(src="memo:geo/live", type_="about")] == ["geo"]
    assert "memo:geo/live" in entry_api.refs("geo", direction="in")  # the ledger's reverse refs list the memo
    _session(rs, ("U", "what does it carry?", "answered"))  # a session and a directive: what the ledger holds is as it was
    assert "fresh" in memo_api.memo("read", "geo/live")
    _session(rs, ("E", "a second object", "established"))
    assert ("STALE: geo changed since this was written. Read it again, then rewrite the memo or drop it."
            in memo_api.memo("read", "geo/live"))
    assert "· STALE (geo changed) · E1 is the only live row" in memo_api.memo()
    memo_api.memo("write", "geo/live", "E1 and E2 are live", about=["geo"])
    assert "fresh" in memo_api.memo("read", "geo/live")


def test_a_card_and_an_entry_are_sources_too(rs, g):
    rs.hb.save_entry(title="Disk full", condition="ENOSPC", items=[{"text": "df -h"}])
    eid = _id(entry_api.entry_node("topic"))
    memo_api.memo("write", "ops", "see the disk card", about=["card:disk-full", eid])
    assert "fresh" in memo_api.memo("read", "ops")
    rs.hb.save_entry(id="disk-full", objective="space again")
    assert "STALE: card:disk-full changed since" in memo_api.memo("read", "ops")
    assert [e["dst"] for e in g.edges(src="memo:ops", type_="about")] == sorted(["card:disk-full", eid])  # kept when the cards are drawn again
    memo_api.memo("write", "ops", "see the disk card, as it is now", about=[eid])
    assert [e["dst"] for e in g.edges(src="memo:ops", type_="about")] == [eid]
    entry_api.ref(eid, "card:disk-full")
    assert f"STALE: {eid} changed since" in memo_api.memo("read", "ops")


def test_a_memo_expires_and_one_is_dropped_on_request(rs, g, clock):
    memo_api.memo("write", "short", "for a day", ttl_days=1)
    memo_api.memo("write", "long", "for two weeks")
    clock[0] += 2 * 86400
    listed = memo_api.memo()
    assert "long · 2 d old · 12 d left" in listed and "short" not in listed and g.get_node("memo:short") is None
    with pytest.raises(HandbookError, match=r"no memo 'short' \(it may have expired\)"):
        memo_api.memo("read", "short")
    assert memo_api.memo("drop", "long") == "memo long: dropped" and memo_api.memo().startswith("no memo")


def test_a_long_text_an_unknown_source_and_a_bad_key_are_refused(rs, g):
    for kw, why in (({"key": "k", "text": "x" * 4001}, "a memo holds at most 4000"),
                    ({"key": "k", "text": "x", "about": ["n:nothing"]}, "no node 'n:nothing' to be about"),
                    ({"key": "has space", "text": "x"}, "bad memo key"),
                    ({"key": "k", "text": "  "}, "a memo needs text")):
        with pytest.raises(HandbookError, match=why):
            memo_api.memo("write", **kw)
    assert memo_api.memo().startswith("no memo")


def test_a_store_from_before_the_memo_gets_its_vocabulary(rs, g):
    m = research_api.R().k
    with m.g.tx():
        m.g.db.execute("DELETE FROM k_types WHERE name IN ('memo', 'about')")
        m.set_meta("package:entry", "the-digest-of-an-older-vocabulary")
    with pytest.raises(Exception, match="memo"):
        memo_api.memo("write", "k", "note")
    m.upgrade_packages()
    assert memo_api.memo("write", "k", "note").startswith("memo k: written")


def test_only_a_write_and_a_drop_of_the_tool_show_the_loops_state(rs, monkeypatch):
    research_api.bind(rs.hb)
    monkeypatch.setattr(server, "_handbook", rs.hb)

    def call(**arguments):
        return asyncio.run(server.make().call_tool("memo", arguments)).content[0].text

    assert call(action="write", key="k", text="note").splitlines()[-1].startswith("LOOP  ")
    assert "LOOP  " not in call(action="read", key="k") and "LOOP  " not in call()
    assert call(action="drop", key="k").splitlines()[-1].startswith("LOOP  ")
