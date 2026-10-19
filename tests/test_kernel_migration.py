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


def build(name, rows, *, turn=5, open_=1, configs=(), verdicts=(), docs=(), pending=(), marks=()):
    """Import a ledger made of raw legacy rows (the import seals it, so the harness compares it)."""
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    r = Research(hb)
    r.init("seed", "a ledger to copy the shape of")
    data = copy.deepcopy(r.export("seed"))
    data["ledger"].update(id=name, turn=turn, open=open_, last_closed=turn - 1, clock=9)
    t = data["tables"]
    t["rl_rows"] = [{"ledger": name, **x} for x in rows]
    t["rl_configs"] = [{"ledger": name, "name": n, "members": m, "spec": m, "purpose": "", "turn": 3} for n, m in configs]
    t["rl_verdicts"] = [{"ledger": name, **v} for v in verdicts]
    t["rl_docs"] = [{"ledger": name, **d} for d in docs]
    t["rl_pending"] = [{"ledger": name, "src": s_, "hit": h} for s_, h in pending]
    t["rl_turnmarks"] = [{"ledger": name, "turn": n, "kind": k, "ref": ref, "note": note} for n, k, ref, note in marks]
    t["rl_log"] = []
    r.import_(data)
    return r


@pytest.fixture
def everything():
    return build("everything", ROWS, configs=[("cfgx", "A1"), ("cfgy", "A1 A9")],
                 verdicts=[verdict("H2", "main", "true"), verdict("H3", "cfgx", "true"), verdict("H4", "cfgx", "true"),
                           verdict("H5", "main", "true"), verdict("H99", "main", "true"),
                           verdict("H1", "nocfg", "open"), verdict("H4", "main", "stale")],
                 docs=[doc("D1", "[]", 1), doc("D2", None, 1)],
                 pending=[("A1", "E2"), ("A1", "H2@main")],
                 marks=[(5, "touched", "E2", ""), (4, "carry", "U1", "later")])


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
    assert g.node("everything:r:E99")["type"] == "missing"
    assert [e["dst"] for e in g.edges(src="everything:r:E4", type_="dep_req")] == \
        ["everything:r:E99", "everything:r:T1", "everything:r:Z1"]
    assert g.node("everything:c:nocfg")["type"] == "missing"


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




# ── data shapes only an import can produce (review findings 9–12) ─────────

def test_any_word_before_a_colon_stays_a_dep_relation():
    # legacy edges() reads any `word:` as a relation; none of them may turn into structure
    r = build("odd_rels", [row("A1", "p", "on"), row("E1", "x", "established", evidence="followed",
                                                    dep="on:A9 member:A9 pending_hit:A1 2x:A1 dép:A1 A9 A9")])
    errors, _ = r.check("odd_rels")
    assert errors.count("E1: cites missing A9") == 4  # legacy repeats it per dep; the kernel reports it once
    g = fresh_graph()
    L = migrate.ledger_to_graph(g, r.export("odd_rels"))
    assert not g.edges(type_="pending_hit") and not g.edges(type_="on") and not g.edges(type_="member")
    assert {e["type"] for e in g.edges(src="odd_rels:r:E1")} == \
        {"dep_on", "dep_member", "dep_pending_hit", "dep_2x", "depx_" + "dép".encode().hex(), "dep_req"}
    assert migrate.ledger_from_graph(g, L)["tables"]["rl_pending"] == []


def test_kinds_have_separate_namespaces_and_an_imported_main_replaces_the_line():
    r = build("names", [row("A1", "p", "on"), row("A2", "q", "on"), row("H1", "c", "true", evidence="computed", dep="A1")],
              configs=[("c1", "A1 D1"), ("main", "A1")],
              verdicts=[verdict("H1", "main", "true"), verdict("H1", "c1", "true")],
              docs=[doc("D1", None, 0)])
    errors, _ = r.check("names")
    assert "configuration c1: member D1 missing" in errors  # the document D1 is not a row
    g = fresh_graph()
    L = migrate.ledger_to_graph(g, r.export("names"))
    assert g.node("names:c:main")["attrs"].get("synthetic") is None
    assert {e["dst"] for e in g.edges(src="names:c:main", type_="member")} == {"names:r:A1"}


@pytest.mark.parametrize("evidence", ["ſourced: a talk", "sourcedſ x", "İrecall of it", "MAP-free int", "  Sourced"])
def test_unicode_case_folding_matches_the_legacy_reading(evidence):
    # compare() runs on import: the kernel must agree with key()/.lower() exactly, whatever it says
    build("uni", [row("A1", "p", "on"), row("E1", "x", "established", evidence=evidence, dep="int:A1")])


def test_handbook_relation_names_live_in_their_own_namespace():
    hb = Handbook(":memory:")
    for name in ("next", "has-step", "member"):
        hb.define_relation_type(name, None, "")
    a = hb.save_entry(title="A", condition="c")["id"]
    b = hb.save_entry(title="B", condition="c", items=[{"text": "go", "goto": a}])["id"]
    hb.relate(a, "next", b)
    hb.relate(a, "has_step", b)  # legacy slugifies has-step to this structural name
    data = hb.export()
    g = fresh_graph()
    migrate.handbook_to_graph(g, data)
    back = migrate.handbook_from_graph(g)
    key = lambda r: (r["src"], r["type"], r["dst"])  # noqa: E731
    assert sorted(back["relations"], key=key) == sorted(data["relations"], key=key)
    assert sorted(back["relation_types"], key=lambda r: r["name"]) == \
        sorted(data["relation_types"], key=lambda r: r["name"])
