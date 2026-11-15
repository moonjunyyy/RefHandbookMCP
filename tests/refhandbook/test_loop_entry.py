"""Entering the loop and staying in it: the message's own objects come first, a tool that works
outside a session shows the loop's state, lookup reaches the procedure cards from the words a
situation is told in, and a card names the entry its work is entered through."""

import asyncio

from refhandbook import Handbook, entry_api, research, research_api, server
from refhandbook.store import stems

from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


# 1 ── the message's own objects before the older queue ─────────────────────

def test_next_takes_the_sessions_own_objects_before_the_older_queue(rs):  # noqa: F811
    t = Turn(rs)
    t.begin(1)
    t.add("U", "first question", "user", "active")
    assert t.push("explore the premises", "EX", "U1") == "K1"  # left queued by session 1
    t.carry("U1", "continues next message")
    t.end()
    t.begin(2)
    t.add("U", "second question", "user", "active")
    assert t.push("dispatch U2", "N3", "U2") == "K2"
    assert t.next().startswith("RUN K2:")  # the message's own object, not the oldest of the ledger
    assert t.push("verify it", "VF", "K2", exit="a") == "K3"  # what a card pushes is this session's too
    t.done("K2", "a")
    assert t.next().startswith("RUN K3:")
    t.push("await the user", "USER", "K3", exit="a")
    t.done("K3", "a")
    assert t.next().startswith("RUN K1:")  # then the queue the earlier session left


# 2 ── lookup reaches the procedure cards from the words a situation is told in ──

def test_a_hangul_query_word_is_also_searched_by_its_stem():
    assert stems("정정했다") == ["정정했다", "정정"] and stems("정정") == ["정정"] and stems("corrected") == ["corrected"]
    hb = Handbook(":memory:")
    hb.save_entry(title="Correction", condition="the user corrected something", triggers=["정정"], items=[{"text": "x"}])
    assert [c["id"] for c in hb.lookup("사용자가 정정했다")] == ["correction"]  # 정정했다 → 정정
    assert [c["id"] for c in hb.lookup("정정을 받았다")] == ["correction"]
    assert hb.lookup("교정했다") == []


def test_the_procedure_cards_are_found_from_a_situation_told_in_korean():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)

    def top(situation):
        return [c["id"] for c in hb.lookup(situation, limit=3)]

    assert "rs-x6" in top("사용자가 정정했다: 그게 아니라고 한다")
    assert "rs-x3" in top("같은 정정이 반복된다")
    assert "rs-rf" in top("전에 하기로 했다는데 이 대화에는 없다")
    assert "rs-x8" in top("그런 말은 없다고 말하려 한다")
    assert "rs-rv" in top("절차가 놓쳤다, 절차 개선")
    assert "rs-n1" in top("메시지마다 세션을 연다")


# 3 ── a card names the entry its work is entered through ────────────────────

def _call(name, **arguments):
    return asyncio.run(server.make().call_tool(name, arguments)).content[0].text


def test_a_card_shows_the_entry_that_routes_to_it(rs, monkeypatch):  # noqa: F811
    research_api.bind(rs.hb)
    monkeypatch.setattr(server, "_handbook", rs.hb)
    rs.hb.save_entry(title="Geo: where things are", kind="reference", condition="the geo project is picked up again",
                     body="notes")
    eid = entry_api.entry_node("the geo project").split()[1].rstrip(":")
    entry_api.ref(eid, "card:geo-where-things-are")
    assert "ENTRY      the geo project (no ledger)." in _call("open_entry", id="geo-where-things-are")
    entry_api.ref(eid, "geo")  # the entry stands for the ledger (the mark of a reconstructed ledger)
    out = _call("open_entry", id="geo-where-things-are")
    assert "ENTRY      the geo project — ledger geo." in out and 'research_begin(ledger="geo") first' in out
    assert out.index("ENTRY ") < out.index("CONDITION ")  # read before the card is used
    assert "    entry: the geo project — ledger geo" in _call("lookup", situation="geo project picked up again")
    rs.hb.save_entry(title="Loose card", condition="nothing routes here", items=[{"text": "x"}])
    assert "ENTRY " not in _call("open_entry", id="loose-card")
