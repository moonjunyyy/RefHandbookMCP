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
    return hb


def turn(n, ledger="geo"):
    out = research_api.research_begin(ledger, n)
    return out, tok(out)


def close(n, t, ledger="geo"):
    research_api.research_end(ledger, n, t, idle="a test turn")


def test_review_falls_due_every_seven_turns_and_a_review_resets_it(api):
    for n in range(1, 7):
        out, t = turn(n)
        assert "REVIEW" not in out
        close(n, t)
    out, t = turn(7)
    assert "REVIEW    7 turns since the last review: open card rs-rv" in out
    out = research_api.research_review("geo", token=t, why="no gap: no refusals, carries or drops in turns 1-7")
    assert out.startswith("REVIEW recorded at turn 7")
    out, t = turn(7)  # re-read
    assert "REVIEW" not in out.split("N1:")[0]
    close(7, t)


def test_refusals_of_the_work_bring_it_forward_and_protocol_refusals_do_not(api):
    out, t = turn(1)
    t = tok(research_api.research_add("geo", t, "H", "a claim", "model", "proposed", evidence="closure: x"))
    with pytest.raises(ResearchError, match="stale or missing token"):
        research_api.research_add("geo", "nope", "H", "x", "user", "open")  # protocol: not a signal
    for _ in range(3):
        with pytest.raises(ResearchError, match="not allowed in H"):
            research_api.research_set("geo", t, "H1", "status", "settled")  # the work: a signal each
    log = [m for (m,) in api.db.execute("SELECT msg FROM rl_log WHERE ledger = 'geo' ORDER BY seq")]
    assert sum(m.startswith("refused: status 'settled' not allowed in H") for m in log) == 3
    assert not any("token" in m for m in log)
    out, t = turn(1)
    assert "REVIEW    3 or more signals since the last review" in out
    research_api.research_review("geo", token=t, why="the H statuses were misread: a reading, not a rule gap")
    assert "REVIEW" not in turn(1)[0].split("N1:")[0]


def test_a_proposal_warns_until_the_user_approves_it(api, capsys):
    out, t = turn(1)
    t = tok(research_api.research_add("geo", t, "H", "the lambda term drops out", "user", "open"))
    out = research_api.research_review("geo", token=t, why="claims phrased as 'drops' hid a sign", rules=[RULE])
    assert "PROPOSED rv_says_drops [check]: 1 finding(s) on geo now" in out and "H1: says 'drops'" in out
    check = research_api.research_check("geo")
    assert "WARN  H1: says 'drops'" in check and "ERROR" not in check  # a proposal never blocks
    assert "rv_says_drops [check, block once approved]" in research_api.research_review("geo", action="proposals")
    g = research_api.R().k.g
    with pytest.raises(Forbidden, match="only the user approves"):
        g.approve("rule", "rv_says_drops", actor="model")
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_says_drops"]) == 0
    assert "rule rv_says_drops approved" in capsys.readouterr().out
    assert "ERROR H1: says 'drops'" in research_api.research_check("geo")
    assert research_api.research_review("geo", action="proposals") == "No open proposals."


def test_a_proposal_must_be_whole_and_parse(api):
    out, t = turn(1)
    with pytest.raises(ResearchError, match="needs its finding"):
        research_api.research_review("geo", token=t, why=" ")
    with pytest.raises(ResearchError, match="needs body"):
        research_api.research_review("geo", token=t, why="x", rules=[{"id": "rv_x", "phase": "check"}])
    with pytest.raises(KernelError):
        research_api.research_review("geo", token=t, why="x", rules=[dict(RULE, body="rv_says_drops(R) :- nonsense")])
    # each refused attempt rolled back whole: no review recorded, no rule left behind
    assert research_api.R().k.g.get_rule("rv_x") is None
    assert not api.db.execute("SELECT 1 FROM rl_log WHERE msg LIKE 'review:%'").fetchone()


def test_a_package_rule_the_user_retired_stays_retired_across_upgrades(api, monkeypatch, capsys):
    out, t = turn(1)
    research_api.research_review("geo", token=t, why="accreting fires on quoted history",
                                 rules=[dict(RULE, id="rv_accreting", replaces="rs_w_accreting",
                                             body=RULE["body"].replace("rv_says_drops", "rv_accreting"))])
    assert cli.main(["--db", str(api.path), "approve", "rule", "rv_accreting", "--retire", "rs_w_accreting"]) == 0
    m = research_api.R().k
    monkeypatch.setattr(rs_pkg, "RULES", [dict(r, message=r["message"] + " (v2)") for r in rs_pkg.RULES])
    m.upgrade_packages()
    assert m.g.get_rule("rs_w_accreting")["state"] == "retired"
    assert m.g.get_rule("rs_c_recall")["message"].endswith("(v2)")


def test_tools_keep_their_signatures_through_the_signal_wrapper():
    params = inspect.signature(research_api.research_add).parameters
    assert list(params)[:3] == ["ledger", "token", "sec"]
    assert research_api.research_add.__doc__.startswith("Add a row.")
    assert research_api.TOOLS["research_review"] is research_api.research_review


def test_the_server_offers_research_review():
    from refhandbook import server

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert {"ledger", "action", "token", "why", "rules"} <= set(tools["research_review"].input_schema["properties"])


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
