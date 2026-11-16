"""The public board's JSON API, /board/api/v1 (docs/board.md). Behind the site sign-in as the agents' API
is (nginx asks the sign-in for a token for the audience `refhandbook`); writes need the pages' header and
origin. The board itself is board.py; what a share copies is read from, and taken into, each person's own
store here — a preset through the agents' Presets, a layer through their capability records.

    GET    /                          {me: {uid, admin}, shares, notices, kinds, limits}: what the viewer
                                      sees, and what the board takes (the page's fields read it)
    GET    /mine                      what the viewer could share: their presets and layers (a layer whose
                                      parents are not all the server's shared ones cannot travel: why)
    GET    /shares/{id}               one share with its copy (a preset's blocks, a layer's script)
    POST   /shares                    {kind, name, title, about}: share (again: a new version) one's own
    DELETE /shares/{id}               its author, or an administrator
    POST   /shares/{id}/import        {as}: take it into one's own store, under that name
    POST   /shares/{id}/hide          {why}: an administrator; its author sees why
    POST   /shares/{id}/show          an administrator
    POST   /notices                   {title, body, pinned}: an administrator
    PATCH  /notices/{id}              {title?, body?, pinned?}: an administrator
    DELETE /notices/{id}              an administrator
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
from starlette.requests import Request

from portal.api import ApiError, answer, bad, body, endpoint, unauthorized
from portal.i18n import t

from .agents import flows
from .agents import keys as K
from .agents.capkinds import PIN_RE, SYS
from .agents.presets import Presets
from .agents.team import TeamError
from .agents.workspace import Workspace
from .board import ABOUT_MAX, KINDS, NOTICE_MAX, TITLE_MAX, Board, BoardError
from .kernel.capabilities import CapError
from .store import Handbook

PREFIX = "/board/api/v1"


# ── what a share copies: out of the author's store, into the taker's ─────────

def preset_copy(ps: Presets, name: str) -> tuple[str, dict[str, Any]]:
    """A preset as it travels: its flow with each block's key reduced to its provider (keys are the person's
    own and never leave their store), the run's limits without the sandbox policy's grant, the input."""
    p = ps.get(name)
    a = p["attrs"]
    flow = {**a["flow"], "steps": [{**{k: v for k, v in s.items() if k != "key"}, "provider": s["key"].split("/", 1)[0]}
                                   for s in a["flow"]["steps"]]}
    return a["title"], {"goal": p["content"], "flow": flow, "limits": flows.limits(a["grant"])}


def preset_take(ps: Presets, keys: list[K.KeyInfo], name: str, copy: dict[str, Any], policies: list[str], default: str) -> str:
    """The copy saved as the taker's preset `name`: each block on the taker's key of its provider (the first one
    they registered); the limits as given, the sandbox policy theirs when they hold one of that name."""
    mine: dict[str, str] = {}
    for k in keys:
        mine.setdefault(k.provider, f"{k.provider}/{k.label}")
    steps = copy["flow"]["steps"]
    need = sorted({s["provider"] for s in steps} - set(mine))
    if need:
        raise BoardError(t("이 프리셋을 쓰려면 {providers} 의 API 키가 필요합니다 — 에이전트의 API 키에서 먼저 등록하세요.",
                           providers=", ".join(need)), 409)
    flow = {**copy["flow"], "steps": [{**{k: v for k, v in s.items() if k != "provider"}, "key": mine[s["provider"]]} for s in steps]}
    limits = dict(copy.get("limits") or {})
    if limits.get("policy") not in policies:
        limits["policy"] = default
    try:
        flow = flows.check(flow, set(mine.values()))
        ps.save(name, str(copy.get("goal", "")), limits, title=str(copy.get("title", "")), flow=flow)
    except TeamError as e:
        raise BoardError(str(e)) from e
    return name


def layer_copy(ws: Workspace, name: str) -> tuple[str, dict[str, Any]]:
    """A layer as it travels: its build script, its parents (only the server's shared layers: a person's own
    layer is in their store alone), its env and what it is for. Built again by whoever takes it."""
    try:
        _, ver, _ = ws.caps.in_force("layer", name)
    except CapError as e:
        raise BoardError(t("그런 레이어가 없습니다: {name}", name=name), 404) from e
    spec = ver["spec"]
    own = [p for p in spec.get("parents") or [] if not p.startswith(SYS)]
    if own:
        raise BoardError(t("이 레이어는 내 레이어 위에 쌓여 있어 공유할 수 없습니다: {parents} — 서버의 공유 레이어(sys:) 위의 레이어만 공유됩니다.",
                           parents=", ".join(own)))
    return spec.get("description") or name, {"script": ver["body"] or "", "parents": list(spec.get("parents") or []),
                                             "env": dict(spec.get("env") or {}), "description": spec.get("description", "")}


def layer_take(ws: Workspace, name: str, copy: dict[str, Any]) -> str:
    """The copy as the taker's layer `name`, built under their default policy (what their sandbox already holds:
    a build that needs more waits for them as any widening does)."""
    if ws.caps.find("layer", name):
        raise BoardError(t("이미 있는 레이어 이름입니다: {name}", name=name), 409)
    parents = [p.split("@", 1)[0] for p in copy.get("parents") or [] if PIN_RE.match(p)]
    try:
        ws.caps.add("layer", name, spec={"policy": ws.DEFAULT, "parents": parents, "env": copy.get("env") or {},
                                         "description": copy.get("description", "")}, body=str(copy.get("script", "")), actor="user")
    except CapError as e:
        raise BoardError(str(e)) from e
    return name


def install(m: Any, *, stores: Callable[[str], Handbook], who: Callable[[Request], str | None],
            is_admin: Callable[[str], bool], data_dir: Path, public_url: str, lock: Any) -> None:
    """Register the board's routes on the MCP server `m` (remote.build)."""
    from urllib.parse import urlparse

    origin = "{0.scheme}://{0.netloc}".format(urlparse(public_url))
    api = endpoint(origin=origin)
    board = Board(data_dir / "board.db")

    def route(path: str, methods: list[str]) -> Callable[..., Any]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            async def wrapped(request: Request) -> Any:
                try:
                    return await fn(request)
                except BoardError as e:
                    raise ApiError(e.status, {400: "invalid", 403: "forbidden", 404: "not_found", 409: "conflict"}.get(e.status, "invalid"),
                                   str(e)) from e
            m.custom_route(PREFIX + path, methods=methods)(api(wrapped))
            return fn
        return deco

    def user(request: Request) -> tuple[str, bool]:
        uid = who(request)
        if uid is None:
            raise unauthorized()
        return uid, is_admin(uid)

    async def locked(fn: Callable[[], Any]) -> Any:
        def run() -> Any:
            with lock:
                return fn()
        return await anyio.to_thread.run_sync(run)

    def space(uid: str) -> tuple[Workspace, Presets]:
        ws = Workspace(stores(uid))
        return ws, Presets(ws.g)

    @route("/", ["GET"])
    async def everything(request: Request) -> Any:
        uid, admin = user(request)
        kind = request.query_params.get("kind") or None
        return {"me": {"uid": uid, "admin": admin}, "kinds": list(KINDS),
                "limits": {"title": TITLE_MAX, "about": ABOUT_MAX, "notice": NOTICE_MAX},
                "shares": [s.json() for s in board.shares(uid, admin, kind)], "notices": [n.json() for n in board.notices()]}

    @route("/mine", ["GET"])
    async def mine(request: Request) -> Any:
        uid, _ = user(request)

        def get() -> Any:
            ws, ps = space(uid)
            layers = []
            for rec in ws.caps.list("layer", states=("active",)):
                name = rec["attrs"]["name"]
                try:
                    layer_copy(ws, name)
                    why = ""
                except BoardError as e:
                    why = str(e)
                layers.append({"name": name, "title": rec.get("content") or name, "why": why})
            return {"preset": [{"name": p["attrs"]["name"], "title": p["attrs"]["title"], "why": ""} for p in ps.list()], "layer": layers}
        return await locked(get)

    @route("/shares/{sid}", ["GET"])
    async def one(request: Request) -> Any:
        uid, admin = user(request)
        return board.share(request.path_params["sid"], uid, admin).json(payload=True)

    @route("/shares", ["POST"])
    async def share(request: Request) -> Any:
        uid, _ = user(request)
        d = await body(request)
        kind, name = str(d.get("kind", "")), str(d.get("name", ""))
        if kind not in KINDS:
            raise bad(t("공유할 수 있는 것은 {kinds} 입니다.", kinds=", ".join(KINDS)))

        def act() -> Any:
            ws, ps = space(uid)
            try:
                title, copy = preset_copy(ps, name) if kind == "preset" else layer_copy(ws, name)
            except TeamError as e:
                raise BoardError(str(e), 404) from e
            if kind == "preset":
                copy["title"] = title
            return board.put(kind, name, uid, str(d.get("title") or title), str(d.get("about", "")), copy).json()
        return answer(await locked(act), 201)

    @route("/shares/{sid}", ["DELETE"])
    async def unshare(request: Request) -> Any:
        uid, admin = user(request)
        board.remove(request.path_params["sid"], uid, admin)
        return {"deleted": request.path_params["sid"]}

    @route("/shares/{sid}/import", ["POST"])
    async def take(request: Request) -> Any:
        uid, admin = user(request)
        d = await body(request)
        s = board.share(request.path_params["sid"], uid, admin)
        name = str(d.get("as") or s.name).strip().lower()

        def act() -> Any:
            ws, ps = space(uid)
            if s.kind == "preset":
                if any(p["attrs"]["name"] == name for p in ps.list()):
                    raise BoardError(t("이미 있는 프리셋 이름입니다: {name}", name=name), 409)
                got = preset_take(ps, K.KeyStore.for_web(data_dir).list(uid), name, s.payload, ws.policies(), ws.DEFAULT)
            else:
                got = layer_take(ws, name, s.payload)
            board.taken(s.id)
            return {"kind": s.kind, "name": got}
        return answer(await locked(act), 201)

    @route("/shares/{sid}/hide", ["POST"])
    async def hide(request: Request) -> Any:
        uid, admin = user(request)
        d = await body(request)
        return board.hide(request.path_params["sid"], uid, str(d.get("why", "")), admin).json()

    @route("/shares/{sid}/show", ["POST"])
    async def show(request: Request) -> Any:
        uid, admin = user(request)
        return board.show(request.path_params["sid"], uid, admin).json()

    @route("/notices", ["POST"])
    async def post(request: Request) -> Any:
        uid, admin = user(request)
        d = await body(request)
        return answer(board.post(uid, admin, d.get("title", ""), d.get("body", ""), bool(d.get("pinned"))).json(), 201)

    @route("/notices/{nid}", ["PATCH"])
    async def edit(request: Request) -> Any:
        _, admin = user(request)
        d = await body(request)
        return board.edit(request.path_params["nid"], admin, title=d.get("title"), body=d.get("body"), pinned=d.get("pinned")).json()

    @route("/notices/{nid}", ["DELETE"])
    async def unpost(request: Request) -> Any:
        _, admin = user(request)
        board.unpost(request.path_params["nid"], admin)
        return {"deleted": request.path_params["nid"]}
