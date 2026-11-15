"""Entering the loop and staying in it: the message's own objects come first, a tool that works
outside a session shows the loop's state, lookup reaches the procedure cards from the words a
situation is told in, and a card names the entry its work is entered through."""

from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


# 1 ── the message's own objects before the older queue ─────────────────────

def test_next_takes_the_sessions_own_objects_before_the_older_queue(rs):  # noqa: F811
    t = Turn(rs)
    t.begin(1)
    t.add("U", "first question", "user", "active")
    assert t.push("explore the premises", "EX", "U1") == "K1"  # left queued by session 1
    t.carry("U1", "continues next message")
    t.end()
    t.begin(2)
    t.add("U", "second question", "user", "active")
    assert t.push("dispatch U2", "N3", "U2") == "K2"
    assert t.next().startswith("RUN K2:")  # the message's own object, not the oldest of the ledger
    assert t.push("verify it", "VF", "K2", exit="a") == "K3"  # what a card pushes is this session's too
    t.done("K2", "a")
    assert t.next().startswith("RUN K3:")
    t.push("await the user", "USER", "K3", exit="a")
    t.done("K3", "a")
    assert t.next().startswith("RUN K1:")  # then the queue the earlier session left
