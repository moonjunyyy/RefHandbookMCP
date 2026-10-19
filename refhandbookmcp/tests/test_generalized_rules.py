"""The rules generalized from the session feedback (proposals 1, 2, 5, 6, 7, 8): each test states the
general rule, then shows the case that exposed it."""

import pytest

from refhandbook.research import ResearchError

from test_research import DOC_V1, Turn, rs, seed_claim  # noqa: F401 (rs is a fixture)


@pytest.fixture
def t(rs):
    t = Turn(rs)
    t.begin(1)
    seed_claim(t)  # U1, A1 on, A2 off, A3 model-proposed, E1 on A1, H1 on E1
    return t


def synced(t):
    """D1 synced with DOC_V1 (sections s1 on E1, s2 on H1)."""
    t.doc_register("summary.md", "deliverable", "")
    t.doc_plan("D1", "# The proxy Lagrangian\n", items=[
        {"sec": "new:eq", "op": "add", "rows": ["E1"]}, {"sec": "new:lin", "op": "add", "rows": ["H1"]},
        {"op": "omit", "rows": ["A1", "A2", "A3", "U1"], "why": "inside the sections"}])
    t.doc_sync("D1", DOC_V1)


# 1 ── a link does not rest on its target ─────────────────────────────────

def test_a_link_to_a_replaced_row_is_neither_a_check_error_nor_a_pending_hit(t, rs):
    t.add("H", "an older form", "user", "open")                                   # H2
    t.add("H", "relates to the older form", "user", "open", dep="ref:H2 sup:H2")  # H3
    out = t.set("H2", "status", "superseded")
    assert "PENDING" not in out  # nothing rests on H2: H3 only relates to it
    assert not [e for e in rs.check("geo")[0] if e.startswith("H3")]


def test_a_basis_still_rests(t, rs):
    t.add("H", "an older form", "user", "open")                                   # H2
    t.add("H", "built on the older form", "user", "open", dep="iso:H2")           # H3
    out = t.set("H2", "status", "superseded")
    assert "PENDING H2: H3" in out


def test_a_user_row_may_link_to_a_model_row_but_not_rest_on_it(t, rs):
    t.add("H", "a model guess", "model", "proposed", evidence="closure: checked against A1")  # H2
    t.add("R", "the user's reading, compared with the guess", "user", "confirmed", dep="ref:H2")  # R1
    assert not [e for e in rs.check("geo")[0] if e.startswith("R1")]
    t.set("R1", "dep", "H2")
    assert "R1: rests on model-origin H2" in " ".join(rs.check("geo")[0])


def test_true_on_links_alone_is_not_proof(t, rs):
    t.add("H", "supported only", "user", "open", dep="sup:E1")  # H2
    t.verdict("H2", "main", "true", "computed")
    assert "H2@main: true on link edges only (sup/con/ref) — a link is evidence or reference, not proof" \
        in rs.check("geo")[0]


# 2 ── a judgment does not revive a finished row ──────────────────────────

def test_a_verdict_on_a_finished_row_is_recorded_beside_it(t, rs):
    t.set("H1", "status", "history")
    t.verdict("H1", "main", "true", "computed (backfill)")
    assert rs._row("geo", "H1")["status"] == "history"
    assert rs.db.execute("SELECT verdict FROM rl_verdicts WHERE claim = 'H1' AND config = 'main'").fetchone()[0] == "true"
    assert not [e for e in rs.check("geo")[0] if e.startswith("H1")]


def test_a_verdict_still_settles_a_live_or_stale_claim(t, rs):
    t.verdict("H1", "main", "true", "computed")
    assert rs._row("geo", "H1")["status"] == "true"


# 5 ── a missing document is not an empty one ─────────────────────────────

@pytest.mark.parametrize("call", ["plan", "check", "sync"])
def test_a_registered_document_needs_its_text(t, rs, call):
    synced(t)
    with pytest.raises(ResearchError, match="pass the document's current text"):
        if call == "plan":
            rs.doc_plan("geo", None, "D1", "")
        elif call == "check":
            rs.doc_check("geo", "D1", "")
        else:
            t.doc_sync("D1", "")


# 6 ── a document follows changes of content, not of the clock ─────────────

def test_rerecording_a_verdict_or_moving_a_directive_does_not_put_a_document_behind(t, rs):
    t.verdict("H1", "main", "true", "computed")
    synced(t)
    t.verdict("H1", "main", "true", "computed again (backfill)")  # same verdict
    t.set("U1", "status", "answered")                              # a process row
    t.set("E1", "evidence", "computed")                            # same value
    assert not [o for o in rs.obligation_items("geo") if o[0] == "doc_behind"]
    assert "changes since turn 1: none" in rs.doc_plan("geo", None, "D1", DOC_V1)


def test_a_flipped_verdict_does_put_it_behind(t, rs):
    t.verdict("H1", "main", "true", "computed")
    synced(t)
    t.verdict("H1", "main", "false", "cex: lambda = 1")
    assert [o for o in rs.obligation_items("geo") if o[0] == "doc_behind"]
    assert "affected sections: s2" in rs.doc_plan("geo", None, "D1", DOC_V1)


# 7 ── new rows into an existing section ──────────────────────────────────

def test_extend_brings_a_row_into_an_existing_section(t, rs):
    synced(t)
    t.add("E", "the same equation in components", "entailed(E1)", "established", evidence="computed", dep="E1")  # E2
    with pytest.raises(ResearchError, match="extend on s1 needs the rows"):
        t.doc_plan("D1", DOC_V1, items=[{"sec": "s1", "op": "extend"}])
    t.doc_plan("D1", DOC_V1, items=[{"sec": "s1", "op": "extend", "rows": ["E2"]}])
    with pytest.raises(ResearchError, match="extended with E2, but its basis does not cite them"):
        t.doc_sync("D1", DOC_V1.replace("checked by symbolic computation.", "checked symbolically."))
    t.doc_sync("D1", DOC_V1.replace("basis: E1 -->", "basis: E1 E2 -->")
               .replace("checked by symbolic computation.", "checked symbolically, also in components."))


# 8 ── a prose token that spells a ledger id ───────────────────────────────

def test_a_bare_ledger_id_in_prose_is_a_note_not_a_problem(t, rs):
    synced(t)
    text = DOC_V1.replace("drops out of the interior equations.", "drops out in region H1 and in region R9.")
    report = rs.doc_check("geo", "D1", text)
    assert report.startswith("D1: 0 problem(s), 1 note(s)")  # R9 is not a ledger id
    assert "note: line" in report and "H1 is also a ledger id" in report
