"""The public board (refhandbook/board.py, board_api.py; docs/board.md): a share is a copy of one's own preset or
layer, never one's keys; taking it copies it into one's own store; the author changes and takes down their
own; an administrator hides (with the reason) and writes the notices; nothing else is posted."""

from __future__ import annotations

import pytest

from refhandbook import server
from refhandbook.agents.presets import Presets
from refhandbook.agents.workspace import Workspace
from refhandbook.board import ABOUT_MAX, NOTICE_MAX, TITLE_MAX, BoardError
from refhandbook.board_api import layer_copy

from .test_agents import keyed, pair  # noqa: F401 — fixtures
from .test_agents_api import api, call, grant  # noqa: F401 — fixtures and helpers
from .test_remote import BASE, FakeAccounts, built, cfg, client, key, site_token  # noqa: F401 — fixtures

B = "/board/api/v1"


@pytest.fixture
def accounts():
    return FakeAccounts({"moon", "kim", "root"}, admins={"root"})


def board(c, method, path, json=None, uid="moon", write_header=True):
    h = {"X-Auth-Token": site_token(c.key, uid), "Origin": BASE}
    if write_header:
        h["X-Requested-With"] = "fetch"
    return c.request(method, B + path, json=json, headers=h)


def test_the_board_is_behind_the_sign_in_and_its_writes_are_the_pages(api):
    assert api.get(B + "/").status_code == 401
    r = board(api, "GET", "/")
    assert r.status_code == 200 and r.json()["me"] == {"uid": "moon", "admin": False} and r.json()["kinds"] == ["preset", "layer"]
    assert r.json()["limits"] == {"title": TITLE_MAX, "about": ABOUT_MAX, "notice": NOTICE_MAX}  # the page's fields read the board's own
    assert board(api, "GET", "/", uid="root").json()["me"]["admin"] is True
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "x"}, write_header=False).status_code == 403


def test_a_preset_travels_without_its_keys_and_lands_on_the_takers_own(api):
    assert call(api, "PUT", "/presets/daily", {"goal": "report for {date}", "title": "아침 보고", "grant": grant()}).status_code == 200
    r = board(api, "POST", "/shares", {"kind": "preset", "name": "daily", "about": "매일 아침 보고서"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["title"] == "아침 보고" and s["author"] == "moon" and s["version"] == 1 and s["imports"] == 0
    copy = board(api, "GET", f"/shares/{s['id']}", uid="kim").json()["payload"]
    assert "anthropic/main" not in str(copy) and copy["flow"]["steps"][0]["provider"] == "anthropic"  # the key stays home
    assert "routes" not in copy["limits"]
    # a taker without a key of that provider is told which one to register
    r = board(api, "POST", f"/shares/{s['id']}/import", {"as": "daily"}, uid="kim")
    assert r.status_code == 409 and "anthropic" in r.json()["error"]["message"]
    assert call(api, "POST", "/keys", {"provider": "anthropic", "label": "kims", "secret": "sk-ant-api03-zyxwvutsrqponmlk"}, uid="kim").status_code == 201
    r = board(api, "POST", f"/shares/{s['id']}/import", {"as": "morning"}, uid="kim")
    assert r.status_code == 201 and r.json() == {"kind": "preset", "name": "morning"}
    taken = Presets(Workspace(server._user_store("kim")).g).get("morning")
    assert taken["attrs"]["flow"]["steps"][0]["key"] == "anthropic/kims" and taken["attrs"]["title"] == "아침 보고"
    assert board(api, "POST", f"/shares/{s['id']}/import", {"as": "morning"}, uid="kim").status_code == 409  # a name taken
    assert board(api, "GET", "/", uid="kim").json()["shares"][0]["imports"] == 1
    # shared again: the same share, a new version; another's preset cannot be shared by name
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "daily"}).json()["version"] == 2
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "daily"}, uid="kim").status_code == 404


def test_a_layer_travels_as_its_script_and_is_built_by_its_taker(api):
    ws = Workspace(server._user_store("moon"))
    ws.caps.add("layer", "greeter", spec={"description": "a hello tool"}, body="mkdir -p /usr/local/bin\n", actor="user")
    mine = board(api, "GET", "/mine").json()
    assert [x["name"] for x in mine["layer"]] == ["greeter"] and mine["layer"][0]["why"] == ""
    s = board(api, "POST", "/shares", {"kind": "layer", "name": "greeter"}).json()
    assert s["title"] == "a hello tool"
    assert board(api, "GET", f"/shares/{s['id']}", uid="kim").json()["payload"]["script"] == "mkdir -p /usr/local/bin\n"
    r = board(api, "POST", f"/shares/{s['id']}/import", {"as": "hello"}, uid="kim")
    assert r.status_code == 201, r.text
    kim = Workspace(server._user_store("kim"))
    rec = kim.caps.get("layer", "hello")
    assert rec["author"] == "user" and kim.caps.in_force("layer", "hello")[1]["body"] == "mkdir -p /usr/local/bin\n"
    assert board(api, "POST", f"/shares/{s['id']}/import", {"as": "hello"}, uid="kim").status_code == 409


def test_a_layer_on_ones_own_layers_does_not_travel():
    class Caps:
        def in_force(self, kind, name):
            return {}, {"spec": {"parents": ["sys:python@3", "base@1"], "description": "d"}, "body": "x"}, "active"

    class WS:
        caps = Caps()

    with pytest.raises(BoardError, match="base@1"):
        layer_copy(WS(), "child")


def test_the_author_takes_down_an_administrator_hides_with_the_reason(api):
    call(api, "PUT", "/presets/daily", {"goal": "g", "grant": grant()})
    sid = board(api, "POST", "/shares", {"kind": "preset", "name": "daily"}).json()["id"]
    assert board(api, "POST", f"/shares/{sid}/hide", {"why": "x"}, uid="kim").status_code == 403
    assert board(api, "POST", f"/shares/{sid}/hide", {"why": ""}, uid="root").status_code == 400  # the reason is said
    r = board(api, "POST", f"/shares/{sid}/hide", {"why": "개인정보가 보입니다"}, uid="root")
    assert r.status_code == 200 and r.json()["hidden"]
    assert board(api, "GET", "/", uid="kim").json()["shares"] == []
    assert board(api, "GET", f"/shares/{sid}", uid="kim").status_code == 404
    assert board(api, "GET", "/").json()["shares"][0]["hidden_why"] == "개인정보가 보입니다"  # its author sees why
    assert board(api, "POST", f"/shares/{sid}/show", uid="root").json()["hidden"] is False
    assert board(api, "DELETE", f"/shares/{sid}", uid="kim").status_code == 403
    assert board(api, "DELETE", f"/shares/{sid}").json() == {"deleted": sid}
    assert board(api, "GET", "/").json()["shares"] == []


def test_the_notices_are_the_administrators(api):
    assert board(api, "POST", "/notices", {"title": "점검", "body": "토요일 밤"}, uid="kim").status_code == 403
    a = board(api, "POST", "/notices", {"title": "점검", "body": "토요일 밤\n\n두 시간"}, uid="root").json()
    b = board(api, "POST", "/notices", {"title": "새 기능", "body": "공개 보드", "pinned": True}, uid="root").json()
    assert a["body"] == "토요일 밤\n\n두 시간"  # a notice keeps its paragraphs
    assert [n["id"] for n in board(api, "GET", "/").json()["notices"]] == [b["id"], a["id"]]  # pinned first
    assert board(api, "PATCH", f"/notices/{a['id']}", {"pinned": True}, uid="root").json()["pinned"] is True
    assert board(api, "PATCH", f"/notices/{a['id']}", {"title": "x"}, uid="kim").status_code == 403
    assert board(api, "DELETE", f"/notices/{b['id']}", uid="root").json() == {"deleted": b["id"]}
    assert [n["title"] for n in board(api, "GET", "/", uid="kim").json()["notices"]] == ["점검"]


def test_what_is_shared_is_checked(api):
    call(api, "PUT", "/presets/daily", {"goal": "g", "grant": grant()})
    assert board(api, "POST", "/shares", {"kind": "notice", "name": "daily"}).status_code == 400
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "daily", "title": "x" * (TITLE_MAX + 1)}).status_code == 400
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "daily", "about": "x" * (ABOUT_MAX + 1)}).status_code == 400
    assert board(api, "POST", "/shares", {"kind": "preset", "name": "nope"}).status_code == 404
    assert board(api, "POST", "/notices", {"title": "", "body": "b"}, uid="root").status_code == 400
