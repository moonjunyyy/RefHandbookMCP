"""An obligation a rule of the store writes is shown at research_begin in the rule's own words: the
reconstruction obligation (MIGRATE) is such a rule, and a session is told of it."""

import pytest

from refhandbook import entry_api, research_api

from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)

CARD = "ledger-not-yet-reconstructed-as-an-entry-node-migrate-reconstruc"
# the two rules as the store holds them (cap kind=rule): proposals of the model
RECONSTRUCTED = {"id": "rs_reconstructed", "phase": "derive", "severity": "info", "applies_to": "*",
                 "message": "{L} is reconstructed at structure entry-1",
                 "body": 'rs_reconstructed(L) :- edge(E, ref, L), node(E, entry, _), edge(E, tagged, "tag:structure:entry-1").'}
MIGRATE = {"id": "rs_o_migrate", "phase": "obligation", "severity": "info", "applies_to": "ledger",
           "message": "MIGRATE {L}: {W}",
           "body": 'rs_o_migrate(L, W) :- node(Self, ledger, _), L = Self, not rs_reconstructed(Self), '
                   f'W = "not reconstructed at structure entry-1: open card {CARD} and reconstruct it before other work".'}


@pytest.fixture
def g(rs):  # noqa: F811
    research_api.bind(rs.hb)
    return research_api.R().k.g


def _obligations(out: str) -> list[str]:
    return out.split("OBLIGATIONS")[1].split("obligation(s).")[0].splitlines()[1:-1]


def test_a_store_rules_obligation_is_listed_in_its_own_words_before_and_after_approval(rs, g):  # noqa: F811
    t = Turn(rs)
    assert not [o for o in rs.obligation_items("geo") if o[0] == "rule"]  # no such rule: no such line
    t.begin(1)
    t.add("U", "a question", "user", "active")
    g.define_rules([RECONSTRUCTED, MIGRATE], actor="model")
    lines = _obligations(t.begin(1))
    assert lines[0] == f"  MIGRATE geo: not reconstructed at structure entry-1: open card {CARD} and reconstruct it before other work"
    assert lines[1].startswith("  DIRECTIVE U1")  # the ledger-level line first, the row-level ones after
    g.approve("rule", "rs_reconstructed", actor="user")
    g.approve("rule", "rs_o_migrate", actor="user")
    assert _obligations(t.begin(1))[0] == lines[0]  # the same line once the user has approved the rule


def test_the_line_goes_when_the_ledger_is_marked_and_never_stops_a_session_from_closing(rs, g):  # noqa: F811
    g.define_rules([RECONSTRUCTED, MIGRATE], actor="model")
    t = Turn(rs)
    assert "  MIGRATE geo:" in t.begin(1)
    assert t.end(idle="nothing asked").startswith("RECEIPT geo")  # told, not refused
    entry = entry_api.entry_node("the proxy Lagrangian", question="vector EL of the proxy Lagrangian").split()[1].rstrip(":")
    entry_api.ref(entry, "geo")
    assert "  MIGRATE geo:" in t.begin(2)  # routed to, not yet marked
    entry_api.tag(entry, "structure:entry-1")
    assert "MIGRATE" not in t.begin(2)
    assert t.end(idle="nothing asked").startswith("RECEIPT geo")


def test_the_session_loop_card_says_what_to_do_with_such_a_line(rs):  # noqa: F811
    card = "\n".join(i["text"] for i in rs.hb.get_entry("rs-n1")["items"])
    assert "a line a rule of the store wrote" in card and "before the message's own objects" in card
