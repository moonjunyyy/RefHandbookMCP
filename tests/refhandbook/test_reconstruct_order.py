"""The order to reconstruct a ledger as an entry is a command of the instruction set: the instructions
name the structure and give the order, and the ledger list shows which ledgers it is about, with no
session of the research loop opened."""

from refhandbook import entry_api, research_api, server

from .test_research import rs  # noqa: F401 (rs is a fixture)


def test_the_instructions_give_the_order_as_a_command_of_their_own():
    text = server.INSTRUCTIONS
    assert f"Structure {entry_api.STRUCTURE}:" in text and "{structure}" not in text
    assert "This is an order, and it does not wait for the research loop" in text
    assert "NOT RECONSTRUCTED" in text and f"structure:{entry_api.STRUCTURE}" in text
    assert text.index("This is an order") < text.index("Program counter")  # before the loop is spoken of


def test_the_ledger_list_marks_what_is_not_an_entry_of_the_structure(rs):  # noqa: F811
    research_api.bind(rs.hb)
    research_api.research_ledgers(action="init", ledger="two", question="another question")
    g = research_api.R().k.g

    def lines():
        return {ln.split()[0]: ln for ln in research_api.research_ledgers(action="list").splitlines()}

    mark = f"NOT RECONSTRUCTED (structure {entry_api.STRUCTURE})"
    assert lines()["geo"].startswith(f"geo  {mark} · no open session") and mark in lines()["two"]
    entry = entry_api.entry_node("the proxy Lagrangian").split()[1].rstrip(":")
    entry_api.ref(entry, "geo")
    assert mark in lines()["geo"]  # routed to, and not yet tagged: its rows may still be unrouted
    entry_api.tag(entry, f"structure:{entry_api.STRUCTURE}")
    assert mark not in lines()["geo"] and mark in lines()["two"]
    assert entry_api.reconstructed(g, "geo") and not entry_api.reconstructed(g, "two")
