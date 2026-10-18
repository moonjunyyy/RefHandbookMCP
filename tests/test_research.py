import json
import re

import pytest

from refhandbook import Handbook, render, research
from refhandbook.research import Research, ResearchError


def tok(out: str) -> str:
    return re.findall(r"TOKEN (\w+)", out)[-1]


@pytest.fixture
def rs():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    r = Research(hb)
    r.init("geo", "vector EL of the proxy Lagrangian")
    return r


class Turn:
    """Drive one ledger the way the cards say: begin, writes with the newest token, end."""

    def __init__(self, r: Research, ledger: str = "geo"):
        self.r, self.L, self.T = r, ledger, None

    def begin(self, n):
        out = self.r.begin(self.L, n)
        self.T = tok(out)
        return out

    def __getattr__(self, name):
        fn = getattr(self.r, name)

        def call(*args, **kw):
            out = fn(self.L, self.T, *args, **kw)
            self.T = tok(out)
            return out

        return call

    def end(self, n, **kw):
        return self.r.end(self.L, self.T, n, **kw)


# ── cards ──────────────────────────────────────────────────────────────

def test_pages_load_as_clean_cards():
    hb = Handbook(":memory:")
    assert research.ensure_cards(hb).startswith("loaded")
    assert research.ensure_cards(hb) == "research cards up to date"
    ids = hb._column("SELECT id FROM entries WHERE id LIKE 'rs-%'")
    assert {"rs-n1", "rs-ex", "rs-n4", "rs-rf", "rs-x5", "rs-vf", "rs-dom-ml", "rs-ref-ledger"} <= set(ids)
    assert [f for f in hb.audit() if f["entry"].startswith("rs-")] == []


def test_card_numbers_match_page_step_references():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    card = render.card(hb.get_entry("rs-n1"), [])
    # memory items are unnumbered, so "N1 step 4" in any page is the LOOP step on the card
    assert "\n  1. **BEGIN.**" in card and "\n  4. **LOOP.**" in card and "\n  7. **END.**" in card
    assert "CAUTION: The device owns the turn" in card
    assert card.count("## END\n") + card.count("## END ") >= 3  # every exit ends the card


def test_lookup_finds_research_cards_by_symptom():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    assert hb.lookup("what if without this assumption")[0]["id"] == "rs-ex"
    assert hb.lookup("REFUSED stale token")[0]["id"] == "rs-x7"


# ── gate and turn ──────────────────────────────────────────────────────

def test_writes_need_an_open_turn_and_the_newest_token(rs):
    with pytest.raises(ResearchError, match="no turn is open"):
        rs.add("geo", "x", "U", "q", "user", "active")
    t = Turn(rs)
    t.begin(1)
    old = t.T
    t.add("U", "derive", "user", "active")
    with pytest.raises(ResearchError, match="stale or missing token"):
        rs.add("geo", old, "A", "p", "user", "on")
    with pytest.raises(ResearchError, match="not allowed"):
        t.add("A", "p", "user", "active")
    with pytest.raises(ResearchError, match="research_push"):
        t.add("K", "plan", "user", "queued")


def test_another_session_writing_is_detected(rs):
    a, b = Turn(rs), Turn(rs)
    a.begin(1)
    b.begin(1)  # same turn re-read by a second session: allowed, both hold the same token
    b.add("U", "from the other session", "user", "active")
    with pytest.raises(ResearchError, match="another session"):
        a.add("U", "from the first session", "user", "active")
    assert "WARNING" not in a.begin(1)  # re-reading syncs the first session (b's write was through the device)


def test_end_requires_a_directive_a_continuation_and_no_running_plan(rs):
    t = Turn(rs)
    t.begin(1)
    with pytest.raises(ResearchError, match="NO DIRECTIVE"):
        t.end(1)
    t.add("U", "derive", "user", "active")
    t.push("dispatch U1", "N3", "U1", on="U1")
    out = t.next()
    assert "CARD [rs-n3]" in out and "Research N3" in out
    with pytest.raises(ResearchError, match="returned no object"):
        t.done("K1", "a")
    with pytest.raises(ResearchError, match="still running"):
        t.end(1)
    t.push("formalize", "FM", "K1", exit="a", on="U1")
    t.done("K1", "a")
    t.drop("K2", "test")
    with pytest.raises(ResearchError, match="NO CONTINUATION"):
        t.end(1)
    t.push("await the user", "USER", "U1")
    t.set("U1", "status", "done")
    out = t.end(1)
    assert out.startswith("RECEIPT") and out.splitlines()[-1].startswith("NEXT:")
    with pytest.raises(ResearchError, match="already closed"):
        rs.begin("geo", 1)
    assert "K-AWAITING USER K3" in rs.begin("geo", 2)


# ── exploration (request 1) ────────────────────────────────────────────

def seed_claim(t):
    t.add("U", "derive the EL", "user", "active")
    t.add("A", "U in C2", "user", "on")                       # A1
    t.add("A", "U smooth", "user", "off", grp="reg")          # A2
    t.add("A", "U Lipschitz", "model", "proposed", evidence="closure: the user gave C2 only", grp="reg")  # A3
    t.add("E", "E_p = 2(A' grad U + U' H q')", "entailed(A1)", "established", evidence="computed", dep="A1")
    t.add("H", "the lambda term drops out", "entailed(E1)", "open", dep="E1")


def test_configurations_verdict_cells_and_boundary(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed (sympy 2x2)")
    assert rs._row("geo", "H1")["status"] == "true"  # the claim follows its main verdict
    t.config("no_c2", "main -A1", "drop C2")
    out = t.config("lip", "main -A1 +A3", "Lipschitz instead")
    assert "explores model premise(s) A3" in out
    with pytest.raises(ResearchError, match="alternatives"):
        t.config("both", "main +A2 +A3")
    with pytest.raises(ResearchError, match="'main' is the user's line"):
        t.config("main", "A1")
    t.verdict("H1", "no_c2", "false", "cex: |x| has no second derivative")
    t.verdict("H1", "lip", "undecided", "tried: weak derivative only")
    with pytest.raises(ResearchError, match="cex"):
        t.verdict("H1", "lip", "false", "computed")
    m = rs.matrix("geo")
    assert "| H1 the lambda term drops out | true | false | undecided |" in m.replace("| lip | no_c2", "| no_c2 | lip") or "A1 decides it" in m
    assert "H1: A1 decides it" in m
    with pytest.raises(ResearchError, match="already has verdicts"):
        t.config("no_c2", "main -A1 +A2")


def test_model_premise_cannot_enter_the_main_line_but_taint_is_allowed_in_exploration(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.add("E", "object built on the Lipschitz premise", "model", "proposed",
          evidence="closure: needs A3", dep="A3")          # model on model: fine
    assert rs.check("geo")[0] == []
    t.add("E", "main-line object", "entailed(A1)", "established", evidence="followed", dep="E2")
    errors = rs.check("geo")[0]
    assert any("rests on model-origin E2" in e for e in errors)
    t.set("E3", "dep", "E1")
    t.set("A3", "status", "on")
    assert any("model premise is on the main line" in e for e in rs.check("geo")[0])


def test_switching_a_main_premise_stales_only_main_verdict_cells(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    t.config("smooth", "main +A2", "add smoothness")
    t.verdict("H1", "smooth", "true", "computed")
    out = t.set("A1", "status", "off")
    assert "PENDING A1" in out and "H1@main" in out
    assert "H1@smooth" not in out  # the exploration cell keeps its own premises
    t.dispose("H1@main", "A1", "RECHECK")
    v = {r["config"]: r["verdict"] for r in rs.db.execute("SELECT * FROM rl_verdicts WHERE claim = 'H1'")}
    assert v == {"main": "stale", "smooth": "true"}
    assert rs._row("geo", "H1")["status"].startswith("stale")


def test_rechecking_a_claim_stales_all_its_cells(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    t.config("smooth", "main +A2", "add smoothness")
    t.verdict("H1", "smooth", "true", "computed")
    t.add("E", "corrected equation", "entailed(A1)", "established", evidence="computed", dep="A1")
    out = t.set("E1", "status", "superseded")
    assert "PENDING E1: H1" in out
    out = t.dispose("H1", "E1", "RECHECK")
    assert "2 verdict cell(s) marked stale" in out
    assert "STALE     H1@smooth" in rs.begin("geo", 1)


# ── provenance checks carried over ─────────────────────────────────────

def test_evidence_rules(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "q", "user", "active")
    t.add("T", "a theorem", "user", "on", evidence="sourced: a textbook")
    assert any("without a locator" in e for e in rs.check("geo")[0])
    t.set("T1", "evidence", "sourced: https://arxiv.org/abs/0000.00000")
    t.add("A", "agreed last time", "user", "on", evidence="pointer: memory:/areas/x.md")
    t.add("H", "uses it", "entailed(A1)", "open", dep="A1")
    assert any("only a pointer" in e for e in rs.check("geo")[0])
    t.set("A1", "evidence", "recalled from an earlier chat")
    assert any("recall is not evidence" in e for e in rs.check("geo")[0])


# ── documents (requests 2 and 3) ───────────────────────────────────────

DOC_V1 = """# The proxy Lagrangian

## The equation
<!-- sec:s1 basis: E1 -->
The Euler–Lagrange equation in vector form is $E_p = 2(\\dot A\\nabla_p U + \\dot U H_{pq}\\dot q)$,
checked by symbolic computation.

## The linear term
<!-- sec:s2 basis: H1 -->
The term $\\lambda \\dot U$ drops out of the interior equations.
"""


def test_source_documents_are_read_only(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "here are my notes", "user", "active")
    t.doc_register("notes.md", "source", "L = (grad U . p')^2\n")
    assert rs.doc_check("geo", "D1", "L = (grad U . p')^2\n") == "D1 source unchanged"
    assert "differs from the registered original" in rs.doc_check("geo", "D1", "L = edited\n")


def test_reader_lint_flags_ledger_artefacts_but_not_mathematics(rs):
    leaks = rs.lint("## A\nresult [E2; A4] holds ⟵ basis: E2\nTOKEN abc and `computed`\n")
    kinds = " ".join(leaks)
    assert "bracketed ledger ids" in kinds and "basis tag" in kinds and "device output" in kinds
    assert "status vocabulary" in kinds and "section marker" in kinds
    assert rs.lint("## A\n<!-- sec:s1 basis: E2 -->\nThe commutator $[A1, A2]$ vanishes on a K3 surface.\n") == []


def test_document_changes_go_through_a_committed_plan(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    t.doc_register("summary.md", "deliverable", "")
    draft = rs.doc_plan("geo", None, "D1", "# The proxy Lagrangian\n")
    assert "rows not in the document" in draft and "E1" in draft and "H1" in draft
    with pytest.raises(ResearchError, match="no committed plan"):
        t.doc_sync("D1", DOC_V1)
    with pytest.raises(ResearchError, match="plan incomplete"):
        t.doc_plan("D1", "# The proxy Lagrangian\n", items=[{"sec": "new:eq", "op": "add", "rows": ["E1"]}])
    t.doc_plan("D1", "# The proxy Lagrangian\n", items=[
        {"sec": "new:eq", "op": "add", "rows": ["E1"]},
        {"sec": "new:lin", "op": "add", "rows": ["H1"]},
        {"op": "omit", "rows": ["A1", "A2", "A3", "U1"], "why": "premises appear inside the sections"},
    ])
    with pytest.raises(ResearchError, match="DOC-PLAN"):
        t.end(1)
    t.doc_sync("D1", DOC_V1)
    # turn 2: a correction changes E1; the document must be re-planned, then rewritten whole
    t.push("await", "USER", "U1")
    t.set("U1", "status", "done")
    t.end(1)
    t.begin(2)
    t.add("U", "the sign in E1 is wrong", "user", "done")
    t.add("E", "E_p = -2(A' grad U + U' H q')", "entailed(A1)", "established", evidence="computed", dep="A1")
    out = t.set("E1", "status", "superseded")
    for hit in re.findall(r"(H1(?:@main)?|E\d)", out.split("PENDING E1:")[1].split("—")[0]):
        t.dispose(hit, "E1", "RECHECK")
    draft = rs.doc_plan("geo", None, "D1", DOC_V1)
    assert "affected sections: s1 s2" in draft and "citing replaced/stale rows: s1 s2" in draft
    with pytest.raises(ResearchError, match="keep is not allowed"):
        t.doc_plan("D1", DOC_V1, items=[{"sec": "s1", "op": "rewrite"}, {"sec": "s2", "op": "keep", "why": "x"},
                                        {"sec": "new:x", "op": "add", "rows": ["E2"]}])
    t.doc_plan("D1", DOC_V1, items=[{"sec": "s1", "op": "rewrite", "why": "E1 superseded by E2", "rows": ["E2"]},
                                    {"sec": "s2", "op": "retire", "why": "H1 must be rechecked"}])
    appended = DOC_V1.replace("checked by symbolic computation.", "checked by symbolic computation.\nCorrection: [E2] flips the sign.")
    with pytest.raises(ResearchError, match="bracketed ledger ids"):
        t.doc_sync("D1", appended)
    v2 = """# The proxy Lagrangian

## The equation
<!-- sec:s1 basis: E2 -->
The Euler–Lagrange equation in vector form is $E_p = -2(\\dot A\\nabla_p U + \\dot U H_{pq}\\dot q)$,
checked by symbolic computation.
"""
    out = t.doc_sync("D1", v2)
    assert "synced at turn 2" in out


def test_unplanned_edit_is_refused(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.doc_register("summary.md", "deliverable", DOC_V1)
    edited = DOC_V1.replace("drops out", "vanishes")
    draft = rs.doc_plan("geo", None, "D1", edited)
    assert "edited since the last sync without a plan: s2" in draft
    t.doc_plan("D1", edited, items=[{"op": "omit", "rows": ["A1", "A2", "A3", "U1"], "why": "context"}])
    with pytest.raises(ResearchError, match="changed without a plan item"):
        t.doc_sync("D1", edited)


# ── export / import ────────────────────────────────────────────────────

def test_export_import_moves_a_ledger_between_stores(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    data = json.loads(json.dumps(rs.export("geo"), default=str))
    other = Research(Handbook(":memory:"))
    assert "imported ledger 'geo'" in other.import_(data)
    assert other.matrix("geo") == rs.matrix("geo")
    assert "TOKEN" in other.begin("geo", 1)


# ── surfaces: MCP tools, CLI fallback, skill index ─────────────────────

def test_research_tools_over_mcp(monkeypatch):
    import asyncio

    from refhandbook import research_api, server

    hb = Handbook(":memory:")
    monkeypatch.setattr(server, "_handbook", hb)
    research_api.bind(hb)

    async def call(name, **arguments):
        result = await server.mcp.call_tool(name, arguments)
        return result.content[0].text

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert {"research_begin", "research_end", "research_push", "research_next", "research_explore", "research_doc"} <= set(tools)
    assert tools["research_show"].annotations.read_only_hint is True
    assert tools["research_add"].annotations.idempotent_hint is False
    assert "created ledger" in asyncio.run(call("research_ledgers", action="init", ledger="t", question="q"))
    out = asyncio.run(call("research_begin", ledger="t", turn=1))
    assert out.startswith("TOKEN") and "N1: BEGIN ✓" in out
    token = tok(out)
    out = asyncio.run(call("research_add", ledger="t", token=token, sec="U", content="derive", origin="user", status="active"))
    out = asyncio.run(call("research_push", ledger="t", token=tok(out), do="explore", page="EX", frm="U1"))
    out = asyncio.run(call("research_next", ledger="t", token=tok(out)))
    assert "CARD [rs-ex]" in out and "Explore conditions" in out
    with pytest.raises(Exception, match="returned no object"):
        asyncio.run(call("research_done", ledger="t", token=tok(out), kid="K1", exit="a"))
    # cards are reachable through the handbook tools too
    assert "[rs-ex]" in asyncio.run(call("lookup", situation="what if we drop this assumption", scope="research"))
    assert "rs-" not in asyncio.run(call("lookup", situation="what if we drop this assumption"))  # default: handbook only


def test_cli_fallback_runs_the_same_tools(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "research.py"
    db = str(tmp_path / "r.db")

    def run(*args):
        p = subprocess.run([sys.executable, "-I", str(script), "--db", db, *args], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    assert run("research", "research_ledgers", '{"action": "init", "ledger": "c", "question": "q"}')[0] == 0
    code, out = run("research", "research_begin", '{"ledger": "c", "turn": 1}')
    assert code == 0 and out.startswith("TOKEN")
    code, out = run("research", "research_add", json.dumps({"ledger": "c", "token": "wrong", "sec": "U", "content": "x",
                                                           "origin": "user", "status": "active"}))
    assert code == 2 and "stale or missing token" in out
    code, out = run("show", "rs-n4")
    assert code == 0 and "Research N4 — Documents" in out


def test_skill_index_is_generated_from_the_pages():
    from pathlib import Path

    skill = (Path(__file__).resolve().parents[1] / "skills" / "research" / "SKILL.md").read_text()
    assert research.sync_skill_index(skill) == skill, "run: refhandbook research-index --write skills/research/SKILL.md"


def test_tool_calls_written_in_cards_and_skill_match_the_tools():
    import inspect
    from pathlib import Path

    from refhandbook import research_api

    root = Path(__file__).resolve().parents[1]
    sigs = {n: set(inspect.signature(f).parameters) for n, f in research_api.TOOLS.items()}
    files = list((root / "src" / "refhandbook" / "research_pages").glob("*.md")) + [root / "skills" / "research" / "SKILL.md"]
    for f in files:
        text = f.read_text()
        for name in re.findall(r"`(research_\w+)", text):
            assert name in sigs, f"{f.name}: unknown tool {name}"
        for name, args in re.findall(r"(research_\w+)\(([^)]*)\)", text):
            for kw in re.findall(r"(\w+)\s*=", args):
                assert kw in sigs[name], f"{f.name}: {name} has no argument {kw!r}"


# ── regressions from the independent review ───────────────────────────

def test_merge_into_section_is_planned_by_the_merge(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    t.doc_register("summary.md", "deliverable", DOC_V1)
    t.doc_plan("D1", DOC_V1, items=[{"sec": "s1", "op": "merge", "into": "s2", "why": "one passage"},
                                    {"op": "omit", "rows": ["A1", "A2", "A3", "U1"], "why": "context"}])
    merged = DOC_V1.split("## The equation")[0] + """## The linear term
<!-- sec:s2 basis: E1 H1 -->
The vector equation, checked by symbolic computation, loses the term $\\lambda \\dot U$.
"""
    assert "synced" in t.doc_sync("D1", merged)


def test_changes_later_in_the_sync_turn_still_reach_the_document(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.verdict("H1", "main", "true", "computed")
    t.doc_register("summary.md", "deliverable", DOC_V1)
    t.add("E", "a later object", "entailed(A1)", "established", evidence="computed", dep="A1")
    draft = rs.doc_plan("geo", None, "D1", DOC_V1)
    assert "E2" in draft.split("rows not in the document:")[1].splitlines()[0]


def test_claim_premises_come_from_the_configuration(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.add("H", "holds with fewer premises", "entailed(A1)", "open", dep="A1 A2")
    t.config("lean", "main -A1", "minimal set")
    t.verdict("H2", "lean", "true", "computed")
    assert not [e for e in rs.check("geo")[0] if "H2@lean" in e]
    t.add("T", "an external theorem", "user", "proposed", evidence="sourced: https://example.org/t")
    t.set("H2", "dep", "A1 T1")
    assert any("rests on T1" in e for e in rs.check("geo")[0])


def test_rechecking_a_main_premise_opens_the_main_cells(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.add("S", "U: P×Q → R", "user", "confirmed")
    t.set("A1", "dep", "S1")
    t.verdict("H1", "main", "true", "computed")
    out = t.set("S1", "status", "superseded")
    assert "A1" in out
    out = t.dispose("A1", "S1", "RECHECK")
    assert "H1@main" in out


def test_plan_objects_are_not_propagation_hits(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)
    t.push("verify H1", "VF", "U1", on="H1")
    t.next()
    t.verdict("H1", "main", "true", "computed")
    out = t.verdict("H1", "main", "false", "cex: a counterexample")
    assert "K1" not in out


def test_unverified_recall_is_allowed(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "q", "user", "active")
    t.add("T", "a remembered identity", "user", "proposed", evidence="[unverified] recall of a textbook identity")
    assert not [e for e in rs.check("geo")[0] if "recall" in e]


def test_cli_show_loads_cards_on_a_fresh_database(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "research.py"
    p = subprocess.run([sys.executable, "-I", str(script), "--db", str(tmp_path / "f.db"), "show", "rs-n1"],
                       capture_output=True, text=True)
    assert p.returncode == 0 and "Research N1" in p.stdout
