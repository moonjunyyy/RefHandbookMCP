"""Legacy stores on the kernel: round trips, and a ledger built to make every research rule fire,
so the differential comparison (conftest.compare) is not vacuous for any of them."""

import copy

import pytest

from conftest import compare, fresh_graph
from refhandbook import Handbook, research
from refhandbook.kernel import evaluate, findings, migrate
from refhandbook.kernel.packages.research import RULES
from refhandbook.research import Research

GATES = {r["id"] for r in RULES if r["phase"] != "derive"}


def row(rid, content, status, origin="user", evidence="", dep="", grp="", created=1, updated=1, clock=1):
    return {"id": rid, "sec": rid[0], "num": int(rid[1:]), "content": content, "origin": origin, "status": status,
            "evidence": evidence, "dep": dep, "grp": grp, "turn_created": created, "turn_updated": updated,
            "clock_updated": clock}


ROWS = [
    row("U1", "explain the gauge choice", "active"),
    row("A1", "the metric is flat", "on"),
    row("A2", "a model premise", "on", origin="model"),
    row("A3", "a premise with a bad status", "bogus"),
    row("A4", "an old premise", "superseded"),
    row("T1", "a known result", "on", evidence="pointer: see the paper"),
    row("Z1", "an isolated unknown", "isolated"),
    row("E1", "a model object", "proposed", origin="model", evidence="computed"),
    row("E2", "an accreting object", "established", evidence="computed; a; b; c", dep="int:A1", clock=3),
    row("E3", "a search with no calls", "established", evidence="tried x · not found: "),
    row("E4", "rests on odd things", "established", evidence="followed", dep="Z1 T1 E99"),
    row("E5", "rests on a model premise", "established", evidence="followed", dep="A2"),
    row("E6", "a model row on a superseded premise", "established", origin="model", evidence="computed", dep="A4"),
    row("E7", "a user row on a superseded premise", "established", evidence="computed", dep="A4"),
    row("H1", "an old open claim", "open"),
    row("H2", "supported only", "true", evidence="computed", dep="sup:E2"),
    row("H3", "rests on T1 and contradicts H4", "true", evidence="computed", dep="T1 con:H4"),
    row("H4", "the other side", "true", evidence="computed", dep="A1"),
    row("H5", "status disagrees with its verdict", "open", evidence="tried: x", dep="A1"),
    row("E8", "a source with no locator", "established", evidence="sourced: a talk"),
    row("E9", "remembered", "established", evidence="recall of a seminar"),
    row("E10", "a guess", "established", evidence="[unverified] guess"),
    row("E11", "built on the guess", "established", evidence="computed from E10", dep="E10"),
    row("K1", "run the check → @VF", "running", origin="entailed(U1)", evidence="from:U1 @VF", dep="U1"),
]


def verdict(claim, config, v, evidence="computed"):
    return {"claim": claim, "config": config, "verdict": v, "evidence": evidence, "turn": 4, "clock": 2}


def doc(did, plan, sync_clock):
    return {"id": did, "label": f"doc {did}", "role": "deliverable", "owner": "user", "sha": "", "sections": "{}",
            "sync_turn": 1, "plan": plan, "plan_turn": None, "turn": 1, "sync_clock": sync_clock}


@pytest.fixture
def everything():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    r = Research(hb)
    r.init("seed", "a ledger to copy the shape of")
    data = copy.deepcopy(r.export("seed"))
    data["ledger"].update(id="everything", turn=5, open=1, last_closed=4, clock=9)
    L = "everything"
    t = data["tables"]
    t["rl_rows"] = [{"ledger": L, **x} for x in ROWS]
    t["rl_configs"] = [{"ledger": L, "name": "cfgx", "members": "A1", "spec": "A1", "purpose": "", "turn": 3},
                       {"ledger": L, "name": "cfgy", "members": "A1 A9", "spec": "A1 A9", "purpose": "", "turn": 3}]
    t["rl_verdicts"] = [{"ledger": L, **v} for v in (
        verdict("H2", "main", "true"), verdict("H3", "cfgx", "true"), verdict("H4", "cfgx", "true"),
        verdict("H5", "main", "true"), verdict("H99", "main", "true"), verdict("H1", "nocfg", "open"),
        verdict("H4", "main", "stale"))]
    t["rl_docs"] = [{"ledger": L, **doc("D1", "[]", 1)}, {"ledger": L, **doc("D2", None, 1)}]
    t["rl_pending"] = [{"ledger": L, "src": "A1", "hit": "E2"}, {"ledger": L, "src": "A1", "hit": "H2@main"}]
    t["rl_turnmarks"] = [{"ledger": L, "turn": 5, "kind": "touched", "ref": "E2", "note": ""},
                         {"ledger": L, "turn": 4, "kind": "carry", "ref": "U1", "note": "later"}]
    t["rl_log"] = []
    r.import_(data)  # the harness compares here too (import seals the ledger)
    return r


def test_every_research_rule_fires_and_matches_the_legacy_result(everything):
    compare(everything, "everything")  # exact agreement: check messages, obligations, end blockers, round trip
    g = fresh_graph()
    L = migrate.ledger_to_graph(g, everything.export("everything"))
    fired = {f.rule for f in evaluate(g, "check", L, "ledger")}
    fired |= {f.rule for f in evaluate(g, "obligation", L, "ledger")}
    fired |= {f.rule for f in findings(g, migrate.ensure_turn(g, L, 5))}
    assert GATES - fired == set()


def test_references_to_nothing_become_missing_nodes_and_survive(everything):
    g = fresh_graph()
    L = migrate.ledger_to_graph(g, everything.export("everything"))
    assert g.node("everything:E99")["type"] == "missing"
    assert [e["dst"] for e in g.edges(src="everything:E4", type_="req")] == \
        ["everything:E99", "everything:T1", "everything:Z1"]
    assert g.node("everything:cfg:nocfg")["type"] == "missing"


def test_the_harness_catches_a_disagreement(everything, monkeypatch):
    check = Research.check

    def one_more(self, ledger):
        errors, warnings = check(self, ledger)
        return errors + ["E1: an error only the legacy code reports"], warnings

    monkeypatch.setattr(Research, "check", one_more)
    with pytest.raises(AssertionError, match="check errors differ"):
        compare(everything, "everything")


def test_handbook_round_trip_with_research_cards_and_a_dangling_goto():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    hb.save_entry(title="Probe", condition="c", objective="o", triggers=["x"], tags=["t"],
                  items=[{"text": "do", "response": "done"}, {"text": "go", "goto": "nowhere-yet", "ends": True}])
    data = hb.export()
    g = fresh_graph()
    n = migrate.handbook_to_graph(g, data)
    assert n == len(data["entries"])
    back = migrate.handbook_from_graph(g)
    key = lambda r: (r["src"], r["type"], r["dst"])  # noqa: E731
    assert sorted(back["relations"], key=key) == sorted(data["relations"], key=key)
    assert back["entries"] == data["entries"]
    assert sorted(back["relation_types"], key=lambda r: r["name"]) == \
        sorted(data["relation_types"], key=lambda r: r["name"])
    assert g.node("card:nowhere-yet")["type"] == "missing"
    steps = g.edges(src="card:rs-n1", type_="has_step")
    assert len(steps) == len(hb.get_entry("rs-n1")["items"])


def test_a_relation_type_may_not_shadow_a_package_edge():
    g = fresh_graph()
    with pytest.raises(Exception, match="collides"):
        migrate.handbook_to_graph(g, {"relation_types": [{"name": "member", "inverse": "x", "description": ""}]})
