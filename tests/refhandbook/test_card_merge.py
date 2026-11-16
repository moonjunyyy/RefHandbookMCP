"""Card revisions and merging (docs/handbook.md "Revisions and merging"): a save names the revision it was
written against; on an older one it is merged three ways, or refused as a conflict with the overlap marked."""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from refhandbook import research_api, server
from refhandbook.store import CardConflict, Handbook, HandbookError, merge3

from .test_research import rs  # noqa: F401 (rs is a fixture)

BODY = "line one\nline two\nline three\nline four\nline five"
STEPS = [{"text": "look"}, {"text": "decide"}, {"text": "act"}]


@pytest.fixture
def hb():
    h = Handbook(":memory:")
    h.save_entry(title="Disk full", condition="ENOSPC", objective="space again", body=BODY, tags=["ops"],
                 triggers=["ENOSPC"], items=STEPS)
    return h


def test_merge3_takes_each_sides_change_and_marks_only_an_overlap():
    base = list("abcdef")
    assert merge3(base, list("aXcdef"), list("abcdYf")) == [("ok", list("aXcdYf"))]
    assert merge3(base, list("abcdef"), list("abdef")) == [("ok", list("abdef"))]        # their deletion
    assert merge3(base, list("abc1def"), list("abcdef2")) == [("ok", list("abc1def2"))]  # two insertions
    assert merge3(base, list("aXcdef"), list("aXcdef")) == [("ok", list("aXcdef"))]      # the same change twice
    assert merge3(base, list("aXcdef"), list("aYcdef")) == [
        ("ok", ["a"]), ("conflict", ["X"], ["b"], ["Y"]), ("ok", list("cdef"))]
    assert merge3([], ["x"], []) == [("ok", ["x"])] and merge3(["x"], [], ["x"]) == []


def test_each_replaced_revision_is_kept_and_read_and_goes_with_its_card(hb):
    hb.save_entry(id="disk-full", objective="room on the disk")
    assert hb.revisions("disk-full") == [1]
    old = hb.get_revision("disk-full", 1)
    assert old["objective"] == "space again" and old["revision"] == 1
    assert [i["text"] for i in old["items"]] == ["look", "decide", "act"] and old["tags"] == ["ops"]
    assert hb.get_revision("disk-full", 2)["objective"] == "room on the disk"
    with pytest.raises(HandbookError, match=r"rev 7 of \[disk-full\] is not kept \(the card is at rev 2; kept: 1\)"):
        hb.get_revision("disk-full", 7)
    hb.delete_entry("disk-full")
    assert not hb.db.execute("SELECT 1 FROM entry_revisions").fetchall()


def test_a_save_on_the_current_revision_goes_in_as_it_is(hb):
    e = hb.save_entry(id="disk-full", base=1, objective="room on the disk")
    assert e["revision"] == 2 and e["objective"] == "room on the disk" and "merge" not in e


def test_two_saves_from_one_revision_that_do_not_overlap_are_both_kept(hb):
    hb.save_entry(id="disk-full", base=1, body=BODY.replace("line two", "line 2"), tags=["ops", "storage"],
                  items=[{"text": "look closely"}, *STEPS[1:]])  # another conversation's save
    e = hb.save_entry(id="disk-full", base=1, body=BODY.replace("line five", "line 5"), objective="room on the disk",
                      tags=["ops", "disk"], items=[*STEPS, {"text": "report"}])
    assert e["revision"] == 3
    assert e["body"] == "line one\nline 2\nline three\nline four\nline 5"
    assert e["tags"] == ["disk", "ops", "storage"] and e["objective"] == "room on the disk"
    assert [i["text"] for i in e["items"]] == ["look closely", "decide", "act", "report"]
    assert e["merge"].startswith("MERGED [disk-full]: written against rev 1, saved onto rev 2: ")
    assert "body (yours and rev 2's changes)" in e["merge"] and "objective (yours)" in e["merge"]
    assert hb.revisions("disk-full") == [1, 2]


def test_an_overlap_is_refused_with_the_place_marked_and_resolved_on_the_current_revision(hb):
    hb.save_entry(id="disk-full", base=1, body=BODY.replace("line two", "line 2"),
                  items=[{"text": "look closely"}, *STEPS[1:]])
    with pytest.raises(CardConflict) as c:
        hb.save_entry(id="disk-full", base=1, body=BODY.replace("line two", "LINE TWO").replace("line five", "line 5"),
                      condition="ENOSPC or EDQUOT", items=[{"text": "look twice"}, *STEPS[1:]])
    said = str(c.value)
    assert said.startswith("CONFLICT [disk-full]: this save was written against rev 1; the card is at rev 2, and "
                           "body, items changed on both sides. Nothing was written.")
    assert ("== body: CONFLICT ==\nline one\n<<<<<<< yours\nLINE TWO\n||||||| rev 1\nline two\n=======\nline 2\n"
            ">>>>>>> rev 2\nline three\nline four\nline 5") in said  # the rest of the body is already merged
    assert '<<<<<<< yours\n{"phase": "action", "kind": "step", "text": "look twice"}\n||||||| rev 1' in said
    assert "== condition: changed by you alone: send again as you sent it ==" in said
    assert "save_entry(id='disk-full', base=2, …)" in said
    now = hb.get_entry("disk-full")  # as the other save left it
    assert now["revision"] == 2 and "line 2" in now["body"] and now["condition"] == "ENOSPC"
    e = hb.save_entry(id="disk-full", base=2, body="line one\nLINE 2\nline three\nline four\nline 5",
                      condition="ENOSPC or EDQUOT", items=[{"text": "look closely, twice"}, *STEPS[1:]])
    assert e["revision"] == 3 and "merge" not in e and e["body"].splitlines()[1] == "LINE 2"


def test_text_that_still_carries_marks_is_refused(hb):
    with pytest.raises(HandbookError, match="still carries merge marks"):
        hb.save_entry(id="disk-full", base=1, body="line one\n<<<<<<< yours\nLINE TWO\n=======\nline 2\n>>>>>>> rev 2")
    assert hb.get_entry("disk-full")["revision"] == 1


def test_a_base_that_cannot_have_been_read_and_a_base_that_was_not_kept(hb):
    with pytest.raises(HandbookError, match="there is no rev 5 to have read"):
        hb.save_entry(id="disk-full", base=5, objective="x")
    with pytest.raises(HandbookError, match=r"\[no-such-card\] does not exist"):
        hb.save_entry(id="no-such-card", base=1, title="x")
    hb.save_entry(id="disk-full", objective="room on the disk")  # rev 2
    hb.db.execute("DELETE FROM entry_revisions")  # as in a store from before revisions were kept
    hb.db.commit()
    with pytest.raises(CardConflict, match="rev 1 was saved before revisions were kept") as c:
        hb.save_entry(id="disk-full", base=1, objective="space", condition="ENOSPC")
    assert "== objective: CONFLICT ==\n<<<<<<< yours\nspace\n=======\nroom on the disk\n>>>>>>> rev 2" in str(c.value)
    assert "condition" not in str(c.value).split("Resolve")[1]  # the same on both sides: nothing to settle


def test_a_save_without_a_base_replaces_what_is_stored_as_the_stores_own_writers_do(hb):
    hb.save_entry(id="disk-full", base=1, body="another conversation's body")
    e = hb.save_entry(id="disk-full", body="the research package's own text")
    assert e["revision"] == 3 and e["body"] == "the research package's own text" and hb.revisions("disk-full") == [1, 2]


def _call(name, **arguments):
    return asyncio.run(server.make().call_tool(name, arguments)).content[0].text


def test_the_tool_wants_a_base_to_update_and_merges_or_marks_a_save_on_an_older_one(rs, monkeypatch):  # noqa: F811
    research_api.bind(rs.hb)
    monkeypatch.setattr(server, "_handbook", rs.hb)
    assert "[disk-full] checklist · rev 1" in _call("save_entry", title="Disk full", condition="ENOSPC", body=BODY, items=STEPS)
    for again in ({"id": "disk-full", "objective": "x"}, {"title": "Disk full", "condition": "another card's"}):
        with pytest.raises(ToolError, match=r"REFUSED: \[disk-full\] exists, and an update names the revision"):
            _call("save_entry", **again)
    assert rs.hb.get_entry("disk-full")["revision"] == 1
    assert "· rev 2 ·" in _call("save_entry", id="disk-full", base=1, body=BODY.replace("line two", "line 2"))
    merged = _call("save_entry", id="disk-full", base=1, body=BODY.replace("line five", "line 5"))
    assert merged.startswith("MERGED [disk-full]: written against rev 1, saved onto rev 2: body (yours and rev 2's "
                             "changes).\n\n# Disk full")
    assert "line 2\nline three\nline four\nline 5" in merged and "· rev 3 ·" in merged
    with pytest.raises(ToolError) as c:
        _call("save_entry", id="disk-full", base=1, body=BODY.replace("line two", "LINE TWO"))
    assert "CONFLICT [disk-full]" in str(c.value)
    assert "<<<<<<< yours\nLINE TWO\n||||||| rev 1\nline two\n=======\nline 2\n>>>>>>> rev 3" in str(c.value)
    old = _call("open_entry", id="disk-full", rev=1)
    assert old.startswith("REVISION 1 of [disk-full], kept as the base of merges; the card in use is rev 3.")
    assert "line two" in old and "REVISION" not in _call("open_entry", id="disk-full", rev=3)
