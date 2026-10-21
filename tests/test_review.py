"""The review procedure: the rules judged against what happened, and changes to them proposed by the
model, tried as warnings, and adopted only through the user's channel."""

import asyncio
import inspect

import pytest

from refhandbook import Handbook, cli, render, research, research_api
from refhandbook.kernel import KernelError
from refhandbook.kernel.graph import Forbidden
from refhandbook.kernel.packages import research as rs_pkg
from refhandbook.research import ResearchError

from test_research import tok

RULE = {"id": "rv_says_drops", "phase": "check", "severity": "block", "message": "{R}: says 'drops'",
        "body": 'rv_says_drops(R) :- rs_row(Self, X, R, "H"), content(X, C), match(C, "drops").'}


@pytest.fixture
def api(tmp_path):
    hb = Handbook(tmp_path / "u.db")
    research_api.bind(hb)
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    _held.clear()
    return hb


def seen(rid):
    """The approval hash the proposals listing shows (what the user approves)."""
    from refhandbook.kernel import proposals

    return proposals.approval_sha(research_api.R().k.g, rid)[:12]


_held: dict[str, str] = {}  # ledger → the session this test holds open (a re-read resumes it)


def turn(n, ledger="geo"):
    out = research_api.research_begin(ledger, _held.get(ledger, ""))
    _held[ledger] = tok(out)
    assert _held[ledger].startswith(f"S{n}-"), (n, _held[ledger])
    return out, _held[ledger]


def close(n, t, ledger="geo"):
    research_api.research_end(ledger, t, idle="a test session")
    _held.pop(ledger, None)


def test_review_falls_due_every_seven_turns_and_a_review_resets_it(api):
    for n in range(1, 7):
        out, t = turn(n)
        assert "REVIEW" not in out
        close(n, t)
    out, t = turn(7)
    assert "REVIEW    7 sessions since the last review: open card rs-rv" in out
    out = research_api.research_review("geo", session=t, why="no gap: no refusals, carries or drops in turns 1-7")
    assert out.startswith("REVIEW recorded in session 7")
    out, t = turn(7)  # re-read
    assert "REVIEW" not in out.split("N1:")[0]
    close(7, t)


def test_refusals_of_the_work_bring_it_forward_and_protocol_refusals_do_not(api):
    out, t = turn(1)
    research_api.research_add("geo", t, "H", "a claim", "model", "proposed", evidence="closure: x")
    with pytest.raises(ResearchError, match="no open session"):
        research_api.research_add("geo", "nope", "H", "x", "user", "open")  # protocol: not a signal
    for _ in range(3):
        with pytest.raises(ResearchError, match="not allowed in H"):
            research_api.research_set("geo", t, "H1", "status", "settled")  # the work: a signal each
    log = [m for (m,) in api.db.execute("SELECT msg FROM rl_log WHERE ledger = 'geo' ORDER BY seq")]
    assert sum(m.startswith("refused: status 'settled' not allowed in H") for m in log) == 3
    assert not any("session" in m for m in log)
    out, t = turn(1)
    assert "REVIEW    3 or more signals since the last review" in out
    research_api.research_review("geo", session=t, why="the H statuses were misread: a reading, not a rule gap")
    assert "REVIEW" not in turn(1)[0].split("N1:")[0]


def test_a_proposal_warns_until_the_user_approves_it(api, capsys):
    out, t = turn(1)
    research_api.research_add("geo", t, "H", "the lambda term drops out", "user", "open")
    out = research_api.research_review("geo", session=t, why="claims phrased as 'drops' hid a sign", rules=[RULE])
    assert "PROPOSED rv_says_drops [check]: 1 finding(s) on geo now" in out and "H1: says 'drops'" in out
    check = research_api.research_check("geo")
    assert "WARN  H1: says 'drops'" in check and "ERROR" not in check  # a proposal never blocks
    assert "[check, block once approved]" in research_api.research_review("geo", action="proposals")
    g = research_api.R().k.g
    with pytest.raises(Forbidden, match="only the user approves"):
        g.approve("rule", "rv_says_drops", actor="model")
    sha = seen("rv_says_drops")
    assert f"rv_says_drops approval {sha}" in research_api.research_review("geo", action="proposals")
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_says_drops", "--seen", sha]) == 0
    assert "rule rv_says_drops approved" in capsys.readouterr().out
    assert "ERROR H1: says 'drops'" in research_api.research_check("geo")
    assert research_api.research_review("geo", action="proposals").endswith("No open proposals.")


def test_a_proposal_must_be_whole_and_parse(api):
    out, t = turn(1)
    with pytest.raises(ResearchError, match="needs its finding"):
        research_api.research_review("geo", session=t, why=" ")
    with pytest.raises(ResearchError, match="needs body"):
        research_api.research_review("geo", session=t, why="x", rules=[{"id": "rv_x", "phase": "check"}])
    with pytest.raises(KernelError):
        research_api.research_review("geo", session=t, why="x", rules=[dict(RULE, body="rv_says_drops(R) :- nonsense")])
    # each refused attempt rolled back whole: no review recorded, no rule left behind
    assert research_api.R().k.g.get_rule("rv_x") is None
    assert not api.db.execute("SELECT 1 FROM rl_log WHERE msg LIKE 'review:%'").fetchone()


def test_a_package_rule_the_user_retired_stays_retired_across_upgrades(api, monkeypatch, capsys):
    out, t = turn(1)
    research_api.research_review("geo", session=t, why="accreting fires on quoted history",
                                 rules=[dict(RULE, id="rv_accreting", replaces="rs_w_accreting",
                                             body=RULE["body"].replace("rv_says_drops", "rv_accreting"))])
    assert "retires rs_w_accreting" in research_api.research_review("geo", action="proposals")
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_accreting", "--seen", seen("rv_accreting")]) == 0
    m = research_api.R().k
    monkeypatch.setattr(rs_pkg, "RULES", [dict(r, message=r["message"] + " (v2)") for r in rs_pkg.RULES])
    m.upgrade_packages()
    assert m.g.get_rule("rs_w_accreting")["state"] == "retired"
    assert m.g.get_rule("rs_c_recall")["message"].endswith("(v2)")


def test_tools_keep_their_signatures_through_the_signal_wrapper():
    params = inspect.signature(research_api.research_add).parameters
    assert list(params)[:3] == ["ledger", "session", "sec"]
    assert research_api.research_add.__doc__.startswith("Add a row.")
    assert research_api.TOOLS["research_review"] is research_api.research_review


def test_the_server_offers_research_review():
    from refhandbook import server

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert {"ledger", "action", "session", "why", "rules"} <= set(tools["research_review"].input_schema["properties"])


# ── what the independent review found: each test names the general rule ──

SLOW = {"id": "rv_slow", "phase": "check", "message": "{A}",
        "body": "rv_slow(A) :- node(A, _, _), node(B, _, _), node(C, _, _), node(D, _, _)."}


def test_a_costly_proposal_is_refused_and_a_stored_one_retires_itself(api, monkeypatch):
    """Everything the model writes is bounded: a proposal that would tax every call never stands."""
    from refhandbook.kernel import rules

    monkeypatch.setattr(rules, "PROPOSED_BUDGET", 0.2)
    out, t = turn(1)
    with pytest.raises(ResearchError, match="too costly to run on every ledger"):
        research_api.research_review("geo", session=t, why="x", rules=[SLOW])
    g = research_api.R().k.g
    assert g.get_rule("rv_slow") is None
    with g.tx():  # cheap where it was proposed, costly later: stored, then met on a large ledger
        g.define_rules([SLOW], actor="model")
    check = research_api.research_check("geo")
    assert "OVER BUDGET: proposed rule rv_slow took over 0.2 s" in check
    assert g.get_rule("rv_slow")["state"] == "retired"


def test_an_upgrade_never_makes_a_store_unopenable(api, monkeypatch):
    """A package upgrade is a change of rules like any other: checked as a whole, and deferred rather
    than forced when the store's own rules conflict."""
    m = research_api.R().k
    with m.g.tx():
        m.g.define_rule("my_prop", "check", "my_prop(H) :- rs_has_basis(H).", actor="model", applies_to="ledger",
                        message="{H}")
    changed = [dict(r, body=r["body"].replace("rs_has_basis(H)", "rs_has_basis(H, 1)").replace("rs_has_basis(X)",
                                                                                                 "rs_has_basis(X, 1)"))
               if "rs_has_basis" in r["body"] else r for r in rs_pkg.RULES]
    assert changed != rs_pkg.RULES
    monkeypatch.setattr(rs_pkg, "RULES", changed)
    m.upgrade_packages()  # the arity changed under the model's proposal: the proposal goes, the upgrade stands
    assert m.g.get_rule("my_prop")["state"] == "retired"
    assert m.meta("package:research") == rs_pkg.digest()
    events = [e for (e,) in api.db.execute("SELECT event FROM k_log WHERE event LIKE 'proposal my_prop retired%'")]
    assert events


def test_a_dropped_package_rule_still_in_use_stays(api, monkeypatch):
    m = research_api.R().k
    with m.g.tx():
        m.g.define_rule("mine", "check", "mine(H) :- rs_has_basis(H).", actor="user", applies_to="ledger", message="{H}")
    users = [r for r in rs_pkg.RULES if "rs_has_basis(" in r["body"] and r["id"] != "rs_has_basis"]
    monkeypatch.setattr(rs_pkg, "RULES", [r for r in rs_pkg.RULES if r["id"] != "rs_has_basis" and r not in users])
    m.upgrade_packages()
    assert m.g.get_rule("rs_has_basis")["state"] == "active"
    assert research_api.research_check("geo").startswith("check:")


def test_any_user_change_to_a_package_rule_survives_an_upgrade(api, monkeypatch):
    m = research_api.R().k
    spec = next(r for r in rs_pkg.RULES if r["id"] == "rs_w_unknown")
    with m.g.tx():  # severity only: what the rule says changed, so it is the user's now
        m.g.define_rule("rs_w_unknown", "check", spec["body"], actor="user", applies_to="ledger", severity="block",
                        message=spec["message"])
    monkeypatch.setattr(rs_pkg, "RULES", [dict(r, message=r["message"] + " (v2)") for r in rs_pkg.RULES])
    assert m.upgrade_packages() == ["rs_w_unknown"]
    assert m.g.get_rule("rs_w_unknown")["severity"] == "block"


def test_approval_names_the_version_seen_and_a_rejection_is_final(api, capsys):
    out, t = turn(1)
    research_api.research_review("geo", session=t, why="x", rules=[RULE])
    shown = seen("rv_says_drops")
    research_api.research_review("geo", session=t, why="revised", rules=[dict(RULE, message="{R}: other")])
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_says_drops", "--seen", shown]) == 1
    assert "not the version shown" in capsys.readouterr().err
    assert cli.main(["--db", str(api.path), "reject", "rv_says_drops"]) == 0
    out, t = turn(1)
    with pytest.raises(Forbidden, match="rejected by the user"):
        research_api.research_review("geo", session=t, why="again", rules=[RULE])


def test_signals_are_refusals_of_the_work_only(api):
    out, t = turn(1)
    research_api.research_add("geo", t, "H", "the error is unaffected by drift", "user", "open")
    research_api.research_set("geo", t, "H1", "content", "dispose: UNAFFECTED, dropped (x)")
    with pytest.raises(ResearchError):
        research_api.research_begin("geo", view="sideways")  # a usage error
    with pytest.raises(ResearchError):
        research_api.research_review("geo", session=t, why="")
    assert research_api.R().k.g.node("geo")["attrs"]["derived_signals"] == 0


def test_blob_pieces_are_stored_once(api):
    ref = research_api.research_blob(action="put", text="a" * 1000).split()[1]
    for _ in range(5):
        ref = research_api.research_blob(action="append", text="b" * 1000, ref=ref).split()[1]
    assert api.db.execute("SELECT count(*), sum(size) FROM k_blobs").fetchone()[:] == (1, 6000)


def test_the_cli_runs_as_a_module(api):
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "refhandbook.cli", "--db", str(api.path), "proposals"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "No open proposals." in out.stdout


# ── cards written for another version of the device ──────────────────────

def test_a_card_for_another_device_version_says_so():
    assert render.device_note(["ops", "device:0.7.0"], "0.8.0").startswith("DEVICE 0.7.0: written for that version")
    assert render.device_note(["device:0.8.0"], "0.8.0") == ""
    assert render.device_note(["ops"], "0.8.0") == ""
    hb = Handbook(":memory:")
    research.ensure_cards(hb)
    hb.save_entry(id="where-things-are", title="Where things are in the device", condition="finding a tool",
                  tags=["refhandbookmcp", "device:0.0.1"])
    assert "DEVICE 0.0.1: written for that version" in render.card(hb.get_entry("where-things-are"), [])
    assert "DEVICE 0.0.1" in render.candidates("where things are", hb.lookup("where things are"))


def test_what_an_approval_retires_is_data_bound_to_the_hash(api, capsys):
    """The model's prose cannot widen an approval: only the structured `replaces` retires, and the
    approval hash covers each rule it retires."""
    out, t = turn(1)
    g = research_api.R().k.g
    prose = dict(RULE, id="rv_prose", body=RULE["body"].replace("rv_says_drops", "rv_prose"))
    research_api.research_review("geo", session=t, why="tidy (replaces rs_w_accreting rs_c_recall)",
                                         rules=[prose])
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_prose", "--seen", seen("rv_prose")]) == 0
    assert g.get_rule("rs_w_accreting")["state"] == "active" and g.get_rule("rs_c_recall")["state"] == "active"
    real = dict(RULE, id="rv_real", replaces=["rs_w_accreting"], body=RULE["body"].replace("rv_says_drops", "rv_real"))
    research_api.research_review("geo", session=t, why="x", rules=[real])
    shown = seen("rv_real")
    with g.tx():  # the replaced rule changes after the user looked
        spec = g.get_rule("rs_w_accreting")
        g.define_rule("rs_w_accreting", "check", spec["body"], actor="user", applies_to="ledger", severity="block",
                      message=spec["message"])
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_real", "--seen", shown]) == 1
    assert "not the version shown" in capsys.readouterr().err
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_real", "--seen", seen("rv_real")]) == 0
    assert g.get_rule("rs_w_accreting")["state"] == "retired"
    with pytest.raises(KernelError, match="not an active rule"):
        research_api.research_review("geo", session=t, why="x", rules=[dict(real, id="rv_ghost", replaces="nope",
                                     body=RULE["body"].replace("rv_says_drops", "rv_ghost"))])
