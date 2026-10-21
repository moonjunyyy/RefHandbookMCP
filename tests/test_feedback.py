"""Regressions for the field report on 0.4.x: card loading, ledger admin, large imports,
[unverified] propagation, begin/end volume, the standing @USER continuation, lookup scope."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from refhandbook import Handbook, research
from refhandbook.research import Research, ResearchError

from test_research import Turn


@pytest.fixture
def rs():
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    r = Research(hb)
    r.init("geo", "vector EL of the proxy Lagrangian")
    return r


def close_turn(t: Turn, n: int, u: str = "ok") -> str:
    """The cheapest legal turn: register the message, answer it, keep the continuation, close."""
    t.add("U", u, "user", "active")
    uid = t.r._rows(t.L, "U")[-1]["id"]
    t.push("await the user", "USER", uid)
    t.set(uid, "status", "answered")
    return t.end(n)


# 1 ── cards are there when a user store opens ───────────────────────────

def test_new_user_store_has_the_cards_before_any_research_call(tmp_path):
    from refhandbook.remote import UserStores

    hb = UserStores(tmp_path)("newbie")
    assert hb.exists("rs-n1")
    assert any(c["id"] == "rs-n1" for c in hb.lookup("turn loop every turn", scope="research"))


# 2 ── delete, rename, copy ──────────────────────────────────────────────

def test_rename_copy_delete(rs):
    t = Turn(rs)
    t.begin(1)
    close_turn(t, 1)
    out = rs.copy("geo", "geo-sandbox")
    assert "copied to ledger 'geo-sandbox'" in out
    assert rs.status("geo-sandbox")["last_closed"] == 1
    assert "renamed ledger 'geo-sandbox' → 'geo-try'" in rs.rename("geo-sandbox", "geo-try")
    assert "geo-sandbox" not in rs.ledgers() and "geo-try" in rs.ledgers()
    with pytest.raises(ResearchError, match="confirm='geo-try'"):
        rs.delete("geo-try", "yes")
    assert "deleted ledger 'geo-try'" in rs.delete("geo-try", "geo-try")
    assert "geo-try" not in rs.ledgers()
    left = {t: rs.db.execute(f"SELECT count(*) FROM {t} WHERE ledger = 'geo-try'").fetchone()[0]
            for t in Research.CHILD_TABLES}
    assert set(left.values()) == {0}
    # the original is untouched and still gated: a new turn opens on it
    assert rs.begin("geo").startswith("SESSION S2-")
    with pytest.raises(ResearchError, match="exists"):
        rs.rename("geo", "geo")


def test_rename_keeps_an_open_session_usable(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "q", "user", "active")
    msg = rs.rename("geo", "geo2")
    assert "open sessions keep their tokens" in msg
    t2 = Turn(rs, "geo2")
    t2.T = t.T  # the same token, on the new name
    t2.begin(1)
    t2.push("await", "USER", "U1")
    t2.set("U1", "status", "answered")
    assert t2.end(1).startswith("RECEIPT")


# 3 ── import: smaller exports, another name, dry run, files through the CLI ─

def test_export_without_log_import_as_and_dry_run(rs):
    t = Turn(rs)
    t.begin(1)
    close_turn(t, 1)
    full = rs.export("geo")
    lean = rs.export("geo", include_log=False)
    assert "rl_log" in full["tables"] and "rl_log" not in lean["tables"]
    assert len(json.dumps(lean)) < len(json.dumps(full))
    with pytest.raises(ResearchError, match="exists here"):
        rs.import_(lean)
    out = rs.import_(lean, as_ledger="geo-check", dry_run=True)
    assert out.startswith("DRY RUN") and "check: 0 errors" in out
    assert "geo-check" not in rs.ledgers()  # nothing stored
    out = rs.import_(lean, as_ledger="geo-check")
    assert out.startswith("imported ledger 'geo-check'")
    assert {r["id"] for r in rs._rows("geo-check")} == {r["id"] for r in rs._rows("geo")}
    with pytest.raises(ResearchError, match="export returned"):
        rs.import_({"nope": 1})


def test_cli_reads_arguments_from_a_file_and_data_from_a_file(tmp_path, rs):
    script = Path(__file__).resolve().parents[1] / "scripts" / "research.py"
    db = str(tmp_path / "r.db")
    t = Turn(rs)
    t.begin(1)
    close_turn(t, 1)
    big = tmp_path / "export.json"
    big.write_text(json.dumps(rs.export("geo"), default=str))
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"action": "import", "data_file": str(big), "to": "moved"}))
    p = subprocess.run([sys.executable, "-I", str(script), "--db", db, "research", "research_ledgers", f"@{args}"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "imported ledger 'moved'" in p.stdout
    p = subprocess.run([sys.executable, "-I", str(script), "--db", db, "research", "research_ledgers", "-"],
                       input='{"action": "list"}', capture_output=True, text=True)
    assert "moved" in p.stdout


# 5 ── [unverified] propagates only from the evidence's own leading token ──

def test_unverified_footnote_does_not_propagate(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "derive", "user", "active")
    t.add("E", "quoted step", "user", "established", evidence="followed · the cited lemma is [unverified] in the source")
    t.add("E", "result on it", "user", "established", evidence="computed", dep="E1")
    t.add("E", "raw step", "user", "established", evidence="[unverified] from memory of the paper")
    t.add("E", "result on raw", "user", "established", evidence="computed", dep="E3")
    _, warns = rs.check("geo")
    assert not any(w.startswith("E2:") and "unverified" in w for w in warns)
    assert any(w.startswith("E4:") and "unverified" in w for w in warns)
    assert research.unverified("[unverified] x") and research.unverified("unverified: y")
    assert not research.unverified("computed; see note [unverified]")


# 6 ── begin and end print what changed, not the whole ledger ─────────────

def test_begin_views_and_end_prints_only_changed_rows(rs):
    t = Turn(rs)
    t.begin(1)
    for i in range(30):
        t.add("E", f"old object {i}", "user", "established", evidence="computed")
    close_turn(t, 1)
    for n in (2, 3, 4, 5):
        t.begin(n)
        close_turn(t, n, f"msg {n}")
    t.begin(6)
    t.add("E", "fresh object", "user", "established", evidence="computed")
    out = t.begin(6, view="recent", recent=2)
    assert "fresh object" in out and "old object 3" not in out and "VIEW recent" in out
    assert "OBLIGATIONS" in out
    brief = t.begin(6, view="brief")
    assert "| id |" not in brief and "VIEW brief" in brief and "OBLIGATIONS" in brief
    assert "old object 3" in t.begin(6, view="full")
    receipt = close_turn(t, 6, "msg 6")
    assert receipt.startswith("RECEIPT") and "rows changed in this session" in receipt
    assert "old object 3" not in receipt and "msg 6" in receipt
    assert len(receipt) < len(rs.render("geo"))


# 7 ── one standing @USER continuation, re-armed each turn ───────────────

def test_standing_user_continuation_is_reused(rs):
    t = Turn(rs)
    t.begin(1)
    close_turn(t, 1)
    for n in range(2, 8):
        t.begin(n)
        close_turn(t, n, f"one word {n}")
    ks = rs._rows("geo", "K")
    assert len(ks) == 1, [k["id"] for k in ks]  # six one-word turns, still one K
    assert ks[0]["status"].startswith("blocked")
    # a card that ends by waiting on the user still closes through the same K
    t.begin(8)
    t.add("U", "derive", "user", "active")
    t.push("dispatch U8", "N3", "U8", on="U8")
    t.next()
    t.push("ask the user which reading", "USER", "K2", exit="a", on="U8")
    assert "K1" in rs._rows("geo", "K")[0]["id"] and len(rs._rows("geo", "K")) == 2
    t.done("K2", "a")
    t.set("U8", "status", "answered")
    assert t.end(8).startswith("RECEIPT")


# 9 ── lookup keeps the research cards apart ─────────────────────────────

def test_lookup_scope(rs):
    hb = rs.hb
    hb.save_entry(id="git-stuck", title="Rebase stuck", kind="checklist", condition="rebase conflict loop",
                  objective="get out of a stuck rebase", body="", triggers=["turn", "loop"], tags=["git"],
                  items=[{"phase": "action", "kind": "step", "text": "git rebase --abort"}])
    every = {c["id"] for c in hb.lookup("turn loop", limit=500, scope="all")}
    plain = {c["id"] for c in hb.lookup("turn loop", limit=500, scope="handbook")}
    cards = {c["id"] for c in hb.lookup("turn loop", limit=500, scope="research")}
    assert "git-stuck" in plain and not any(i.startswith("rs-") for i in plain)
    assert cards and all(i.startswith("rs-") for i in cards)
    assert plain | cards == every
