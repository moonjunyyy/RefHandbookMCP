"""The rules generalized from the session feedback (proposals 1, 2, 5, 6, 7, 8): each test states the
general rule, then shows the case that exposed it."""

import pytest

from refhandbook.research import ResearchError

from .test_research import DOC_V1, Turn, rs, seed_claim  # noqa: F401 (rs is a fixture)


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


# 1 ── one relation: every dep edge is a basis; a row of another ledger is one too ──────

def test_every_ref_rests_on_its_target(t, rs):
    t.add("H", "an older form", "user", "open")                                   # H2
    t.add("H", "built on the older form", "user", "open", dep="ref:H2")           # H3
    t.add("H", "also built on it, bare", "user", "open", dep="H2")                # H4
    out = t.set("H2", "status", "superseded")
    assert "PENDING H2: H3 H4" in out
    assert [e for e in rs.check("geo")[0] if e.startswith("H3")] == ["H3: rests on H2 with status 'superseded' — mark H3 stale or re-derive"]


@pytest.mark.parametrize("word", ["sup", "req", "eq", "iso", "con", "int", "der", "spec", "on", "2x"])
def test_the_old_relation_words_are_refused_on_write(t, word):
    with pytest.raises(ResearchError, match="one relation — write ref:H1"):
        t.add("H", "a new row", "user", "open", dep=f"{word}:H1")


def test_the_old_relation_words_still_read_as_ref_in_stored_cells(t, rs):
    rs.db.execute("UPDATE rl_rows SET dep = 'sup:E1 iso:A1' WHERE ledger = 'geo' AND id = 'H1'")
    from refhandbook.research import edges
    assert edges(rs._row("geo", "H1")["dep"]) == [("ref", "E1"), ("ref", "A1")]
    out = t.set("E1", "status", "superseded")
    assert "PENDING E1: H1" in out  # read as ref: H1 rests on E1


def test_a_user_row_cannot_rest_on_a_model_row_by_any_spelling(t, rs):
    t.add("H", "a model guess", "model", "proposed", evidence="closure: checked against A1")  # H2
    t.add("R", "the user's reading, compared with the guess", "user", "confirmed", dep="ref:H2")  # R1
    assert "R1: rests on model-origin H2" in " ".join(rs.check("geo")[0])
    t.set("R1", "dep", "")  # the comparison belongs in the evidence cell, not the dep
    assert not [e for e in rs.check("geo")[0] if e.startswith("R1")]


def test_a_dep_edit_opens_nothing_downstream(t, rs):
    t.add("H", "rests on H1", "user", "open", dep="H1")   # H2
    out = t.set("H1", "dep", "E1 A1")                     # H1 now also names A1: what it says is unchanged
    assert "PENDING" not in out
    assert rs.db.execute("SELECT count(*) FROM rl_pending WHERE ledger = 'geo'").fetchone()[0] == 0


# 1b ── a row of another ledger of the store is cited as ref:<ledger>/<id> ──────────

@pytest.fixture
def kernel(rs):
    rs.init("kernel", "what the ledgers share")
    k = Turn(rs, "kernel")
    k.begin(1)
    k.add("U", "collect the shared objects", "user", "active")
    k.add("E", "the log chart theorem", "user", "established", evidence="followed")   # kernel E1
    k.add("E", "a model reading", "model", "proposed", evidence="closure: U1")        # kernel E2
    return k


def test_a_cross_ledger_ref_is_checked_at_write(t, rs, kernel):
    with pytest.raises(ResearchError, match="no ledger 'nowhere'"):
        t.add("H", "x", "user", "open", dep="ref:nowhere/E1")
    with pytest.raises(ResearchError, match="kernel has no row E9"):
        t.add("H", "x", "user", "open", dep="ref:kernel/E9")
    with pytest.raises(ResearchError, match="named E1, without the ledger"):
        t.add("H", "x", "user", "open", dep="ref:geo/E1")
    t.add("H", "rests on the kernel's theorem", "user", "open", dep="ref:kernel/E1")  # H2
    assert rs._row("geo", "H2")["dep"] == "ref:kernel/E1"


def test_a_cross_ledger_ref_is_a_basis_the_checks_follow(t, rs, kernel):
    t.add("H", "rests on a model row elsewhere", "user", "open", dep="ref:kernel/E2")  # H2
    assert "H2: rests on model-origin kernel/E2; a user row cannot" in " ".join(rs.check("geo")[0])
    t.set("H2", "dep", "ref:kernel/E1")
    assert not [e for e in rs.check("geo")[0] if e.startswith("H2")]
    kernel.set("E1", "status", "superseded")
    assert "H2: rests on kernel/E1 with status 'superseded'" in " ".join(rs.check("geo")[0])


def test_a_change_elsewhere_opens_a_pending_hit_here(t, rs, kernel):
    t.add("H", "rests on the kernel's theorem", "user", "open", dep="ref:kernel/E1")  # H2
    out = kernel.set("E1", "status", "superseded")
    assert "PENDING in other ledgers: geo/H2" in out
    assert [tuple(r) for r in rs.db.execute("SELECT src, hit FROM rl_pending WHERE ledger = 'geo'")] == [("kernel/E1", "H2")]
    kernel.end()  # the kernel's session raised nothing in geo: it closes
    with pytest.raises(ResearchError, match="PENDING H2 \\(from kernel/E1\\)"):
        t.end(idle="x")  # geo's chat session answers for it
    t.dispose("H2", "kernel/E1", "RECHECK", "re-derive without it")
    assert rs._row("geo", "H2")["status"] == "stale(kernel/E1)"
    assert not [e for e in rs.check("geo")[0] if e.startswith("H2")]  # stale: its basis is not checked


def test_cross_ledger_edges_survive_the_projection_of_either_side(t, rs, kernel):
    t.add("H", "rests on the kernel's theorem", "user", "open", dep="ref:kernel/E1")  # H2
    g = rs.k.g
    assert [e["dst"] for e in g.edges(src="geo:r:H2", type_="dep_ref")] == ["kernel:r:E1"]
    kernel.add("H", "a new claim re-projects the kernel", "user", "open")
    assert [e["dst"] for e in g.edges(src="geo:r:H2", type_="dep_ref")] == ["kernel:r:E1"]
    assert g.node("kernel:r:E1")["attrs"]["xref"] == "kernel/E1"
    t.add("H", "a new claim re-projects geo", "user", "open")
    assert [e["dst"] for e in g.edges(src="geo:r:H2", type_="dep_ref")] == ["kernel:r:E1"]


def test_a_ref_into_a_ledger_that_is_gone_is_missing(t, rs, kernel):
    t.add("H", "rests on the kernel's theorem", "user", "open", dep="ref:kernel/E1")  # H2
    kernel.end()
    rs.delete("kernel", confirm="kernel")
    assert "H2: cites missing kernel/E1" in rs.check("geo")[0]


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
    assert "changes since session 1: none" in rs.doc_plan("geo", None, "D1", DOC_V1)


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


# 4 ── a long argument travels once: content-addressed blobs ──────────────

def test_a_document_is_sent_once_and_named_by_its_ref(rs, tmp_path):
    from refhandbook import Handbook, research_api

    hb = Handbook(tmp_path / "u.db")
    research_api.bind(hb)
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    out = research_api.research_begin("geo")
    tok = out.split()[1]
    ref = research_api.research_blob(action="put", text=DOC_V1).split()[1]
    out = research_api.research_doc("geo", "register", tok, label="summary.md", role="deliverable", ref=ref[:12])
    assert "D1 registered as deliverable" in out
    # read through the ref: the check sees the document's sections (whose rows this empty ledger lacks)
    assert "section s1: basis cites missing E1" in research_api.research_doc("geo", "check", doc="D1", ref=ref)
    with pytest.raises(ResearchError, match="text or ref, not both"):
        research_api.research_doc("geo", "check", doc="D1", text=DOC_V1, ref=ref)


def test_a_large_export_is_imported_in_pieces(tmp_path):
    import json

    from refhandbook import Handbook, research_api

    research_api.bind(Handbook(tmp_path / "u.db"))
    research_api.research_ledgers(action="init", ledger="geo", question="a question " * 200)
    data = research_api.research_ledgers(action="export", ledger="geo")
    pieces = [data[i:i + 500] for i in range(0, len(data), 500)]
    ref = research_api.research_blob(action="put", text=pieces[0]).split()[1]
    for p in pieces[1:]:
        ref = research_api.research_blob(action="append", text=p, ref=ref).split()[1]
    assert research_api.research_blob(action="info", ref=ref).endswith(f"{len(data.encode())} bytes")
    out = research_api.research_ledgers(action="import", ref=ref, to="geo-copy")
    assert "imported ledger 'geo-copy'" in out
    assert json.loads(research_api.research_ledgers(action="export", ledger="geo-copy"))["ledger"]["question"] \
        == json.loads(data)["ledger"]["question"]


def test_blob_refs_are_checked(tmp_path):
    from refhandbook import Handbook, research_api
    from refhandbook.kernel import KernelError

    research_api.bind(Handbook(tmp_path / "u.db"))
    with pytest.raises(KernelError, match="12–64 hex digits"):
        research_api.research_blob(action="info", ref="abc")
    with pytest.raises(KernelError, match="no blob"):
        research_api.research_blob(action="info", ref="0" * 64)


# 1c ── a directive's dep is where it works, not what it rests on ──────────────

def test_a_directive_rests_on_nothing_and_is_not_reopened(t, rs):
    t.add("H", "a model guess", "model", "proposed", evidence="closure: checked against A1")  # H2
    t.add("U", "explain H2", "user", "active", dep="H2 A1")                                   # U2: about H2
    assert not [e for e in rs.check("geo")[0] if e.startswith("U2")]  # a user row, but no basis check: it is about H2
    out = t.set("H2", "status", "superseded")
    assert "U2" not in out  # not reopened by its subject's change
    g = rs.k.g
    assert [e["dst"] for e in g.edges(src="geo:r:U2", type_="on")] == ["geo:r:A1", "geo:r:H2"]
    assert g.edges(src="geo:r:U2", type_="dep_ref") == []
