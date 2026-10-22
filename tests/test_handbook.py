import asyncio
import json
from importlib import resources

import pytest

from refhandbook import Handbook, HandbookError, render, server


@pytest.fixture
def hb():
    book = Handbook(":memory:")
    book.load(json.loads(resources.files("refhandbook").joinpath("seed.json").read_text()))
    return book


def ids(rows):
    return [r["id"] for r in rows]


def test_lookup_ranks_trigger_hits_first(hb):
    assert ids(hb.lookup("CONFLICT (content): could not apply abc123"))[0] == "rebase-conflict"
    assert ids(hb.lookup("ModuleNotFoundError after renovate PR"))[0] == "tests-fail-after-dependency-bump"
    assert hb.lookup("the of and") == []
    assert hb.lookup('"unbalanced (quote* AND') == []


def test_card_layout(hb):
    text = render.card(hb.get_entry("rebase-conflict"), hb.neighbors("rebase-conflict"))
    lines = text.splitlines()
    assert lines[0] == "# Rebase stops on a conflict"
    # memory items come before actions, steps are numbered across phases, the end is explicit
    assert text.index("MEMORY ITEMS") < text.index("ACTIONS") < text.index("DEFERRED ITEMS") < text.index("## END OF")
    assert "  1. Do not commit" in text and "  6. WHEN before pushing:" in text
    assert ">> GO TO [git-recovery-reference] Git recovery reference" in text
    assert "     CAUTION: During a rebase" in text


def test_step_goto_is_an_edge_and_inverses_read_from_both_sides(hb):
    out = {(n["label"], n["id"]) for n in hb.neighbors("rebase-conflict")}
    assert ("continues_to", "git-recovery-reference") in out
    assert ("escalates_to", "git-recovery-reference") in out
    assert ("mitigated_by", "pre-merge-checks") in out
    assert ("follows", "pre-merge-checks") in out
    back = {(n["label"], n["id"]) for n in hb.neighbors("git-recovery-reference")}
    assert ("continued_from", "rebase-conflict") in back


def test_relate_accepts_inverse_name_and_symmetric_types(hb):
    assert hb.relate("flaky-test-triage", "follows", "pre-merge-checks") == (
        "pre-merge-checks", "precedes", "flaky-test-triage",
    )  # fmt: skip
    hb.relate("git-recovery-reference", "see_also", "flaky-test-triage")
    assert ("see_also", "git-recovery-reference") in {(n["label"], n["id"]) for n in hb.neighbors("flaky-test-triage")}
    assert hb.unrelate("flaky-test-triage", "see_also", "git-recovery-reference")
    with pytest.raises(HandbookError, match="unknown relation type"):
        hb.relate("flaky-test-triage", "nonsense", "pre-merge-checks")
    with pytest.raises(HandbookError, match="derived"):
        hb.relate("flaky-test-triage", "continues_to", "pre-merge-checks")


def test_runtime_relation_type(hb):
    hb.define_relation_type("blocks", "blocked by")
    hb.relate("flaky-test-triage", "blocked_by", "rebase-conflict")
    assert ("blocks", "flaky-test-triage") in {(n["label"], n["id"]) for n in hb.neighbors("rebase-conflict")}
    with pytest.raises(HandbookError, match="collides"):
        hb.define_relation_type("follows", "leads")


def test_traverse_depth_and_filter(hb):
    start = "tests-fail-after-dependency-bump"
    assert set(ids(hb.traverse(start, depth=1))) == {"flaky-test-triage", "pre-merge-checks"}
    assert "git-recovery-reference" in ids(hb.traverse(start, depth=3))
    assert ids(hb.traverse(start, types=["continues_to"], depth=3)) == ["flaky-test-triage"]


def test_update_keeps_omitted_fields_and_bumps_revision(hb):
    before = hb.get_entry("flaky-test-triage")
    after = hb.save_entry(id="flaky-test-triage", objective="New objective.")
    assert after["revision"] == before["revision"] + 1
    assert after["items"] == before["items"] and after["triggers"] == before["triggers"]
    assert ids(hb.lookup("new objective"))[0] == "flaky-test-triage"


def test_delete_cascades(hb):
    hb.delete_entry("git-recovery-reference")
    assert hb.lookup("reflog") == []
    assert "git-recovery-reference" not in ids(hb.neighbors("pre-merge-checks"))
    # the step that pointed at it is now dangling, and audit says so
    assert any("does not exist" in f["message"] for f in hb.audit() if f["entry"] == "rebase-conflict")


def test_superseded_entries_sink_and_are_flagged(hb):
    hb.save_entry(
        title="Rebase conflict v2",
        condition="git rebase has paused on unmerged paths.",
        objective="Finish the rebase.",
        triggers=["CONFLICT (content)", "could not apply", "unmerged paths", "rebase in progress"],
        tags=["git"],
        items=["git status"],
    )
    hb.relate("rebase-conflict-v2", "supersedes", "rebase-conflict")
    rows = hb.lookup("CONFLICT (content) could not apply, unmerged paths")
    assert rows[0]["id"] == "rebase-conflict-v2"
    old = next(r for r in rows if r["id"] == "rebase-conflict")
    assert old["superseded_by"] == "rebase-conflict-v2"
    assert any("superseded" in f["message"] for f in hb.audit() if f["entry"] == "pre-merge-checks")


def test_audit(hb):
    assert hb.audit() == []
    hb.save_entry(title="Bare", items=[{"phase": "memory", "text": f"m{n}"} for n in range(7)])
    messages = " ".join(f["message"] for f in hb.audit() if f["entry"] == "bare")
    for expected in ("no condition", "no triggers", "no objective", "7 memory items", "orphan"):
        assert expected in messages


def test_item_validation(hb):
    with pytest.raises(HandbookError, match="unknown field"):
        hb.save_entry(title="X", items=[{"text": "a", "step": 1}])
    with pytest.raises(HandbookError, match="only a step"):
        hb.save_entry(title="X", items=[{"kind": "note", "text": "a", "goto": "y"}])
    assert not hb.exists("x")


def test_export_roundtrip(hb):
    data = hb.export()
    copy = Handbook(":memory:")
    copy.load(json.loads(json.dumps(data)))
    assert copy.export() == data | {"entries": [e | {"updated_at": c["updated_at"]} for e, c in zip(data["entries"], copy.export()["entries"])]}


def test_mcp_tools(hb, monkeypatch):
    monkeypatch.setattr(server, "_handbook", hb)

    async def call(name, **arguments):
        result = await server.mcp.call_tool(name, arguments)
        return result.content[0].text

    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} >= {"lookup", "open_entry", "save_entry", "relate", "traverse", "audit"}
    assert next(t for t in tools if t.name == "lookup").annotations.read_only_hint is True
    assert "[rebase-conflict]" in asyncio.run(call("lookup", situation="rebase in progress"))
    card = asyncio.run(call("save_entry", title="Disk full", condition="ENOSPC", items=[{"text": "df -h"}]))
    assert card.startswith("# Disk full")
    assert asyncio.run(call("relate", src="disk-full", type="see_also", dst="flaky-test-triage")) == (
        "[disk-full] see_also -> [flaky-test-triage]"
    )
    with pytest.raises(Exception, match="no entry with id"):
        asyncio.run(call("open_entry", id="nope"))


def test_a_card_holds_one_topic():
    """A procedure (one sequence of at most 10 steps), a set (one list or table) or an index; the
    model's writes of anything more are refused with the parts, and opening one says split first."""
    from refhandbook.store import decomposition

    hb = Handbook(":memory:")
    steps = [{"text": f"step {n}"} for n in range(11)]
    with pytest.raises(HandbookError, match=r"holds more than one topic: 11 steps"):
        hb.save_entry(title="Long", condition="c", items=steps, atomic=True)
    assert not hb.exists("long")  # nothing written
    sub = [{"kind": "note", "text": "Build"}, {"text": "a"}, {"kind": "note", "text": "Test"}, {"text": "b"}]
    with pytest.raises(HandbookError, match="2 sub-procedures"):
        hb.save_entry(title="Two", condition="c", items=sub, atomic=True)
    with pytest.raises(HandbookError, match="reference material inside a procedure"):
        hb.save_entry(title="Mixed", condition="c", body="| a | b |\n|---|---|\n| 1 | 2 |", items=[{"text": "x"}],
                      atomic=True)
    with pytest.raises(HandbookError, match="2 sets"):
        hb.save_entry(title="Ref", kind="reference", condition="c", body="**One.** x\n\n**Two.** y", atomic=True)
    hb.save_entry(title="Set", kind="reference", condition="c", body="**Codes.**\n\n| code | means |\n|---|---|\n| 1 | a |",
                  atomic=True)  # one labeled table: one set
    hb.save_entry(title="Seq", condition="c", items=steps[:10], atomic=True)
    hb.save_entry(title="Legacy", condition="c", items=steps)  # the user's own channel is not refused …
    assert any("holds more than one topic" in f["message"] for f in hb.audit() if f["entry"] == "legacy")  # … but audited
    assert decomposition(hb.get_entry("seq")) == []


def test_opening_a_compound_card_says_split_first(monkeypatch):
    import asyncio

    from refhandbook import server

    hb = Handbook(":memory:")
    monkeypatch.setattr(server, "_handbook", hb)
    hb.save_entry(title="Legacy", condition="c", items=[{"text": f"s{n}"} for n in range(12)])
    out = asyncio.run(server.mcp.call_tool("open_entry", {"id": "legacy"})).content[0].text
    assert out.startswith("SPLIT BEFORE USE") and "rs-split" in out
