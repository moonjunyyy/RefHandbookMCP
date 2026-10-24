"""The agents' JSON API, /agents/api/v1 (docs/site.md "APIs and pages"; docs/agents.md §9).

Behind the site sign-in as the pages are: nginx asks the sign-in for a token for the audience
`refhandbook`, and every request is the user's it names. What this writes is written as `user`, as
the pages do. Approving a run the model asked for is not here: that stays on the server-rendered
approval page (`approve_url`), the user's channel with no script on it.

    GET    me                         who is signed in
    GET    options                    the vocabulary a form needs: roles, levels, efforts, policies,
                                      the grant's defaults, the models each provider suggests
    GET    keys                       the user's keys, each with its own models
    POST   keys                       {provider, label, secret, format?, base_url?}: checked, sealed
    DELETE keys/{provider}/{label}
    GET    runs                       newest first
    POST   runs                       {goal, title?, grant, save_as?}: started at once (the user's own)
    GET    runs/{run}                 phase, goal, grant, agents, usage, result, shared notes
    POST   runs/{run}/cancel
    GET    presets                    each with its schedules
    PUT    presets/{name}             {goal, title?, grant}
    DELETE presets/{name}
    POST   presets/{name}/run
    POST   presets/{name}/schedules   {cron}
    PATCH  schedules/{id}             {enabled}
    DELETE schedules/{id}
    POST   cron                       {cron}: the next five times it fires (for a form to show)
    GET    files?path=                the workspace, read only: a directory's entries or a file's text
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
from starlette.requests import Request

from portal.api import ApiError, answer, bad, body, endpoint, missing, unauthorized

from ..store import Handbook, HandbookError
from . import cron, crew
from . import providers as P
from . import keys as K
from .presets import Presets
from .team import (CONTEXT_LEVELS, DEFAULT_GRANT, EFFORTS, HANDOFF_LEVELS, MAX_ROUTES, RETENTION_LEVELS, ROLES,
                   Team, TeamError)
from .workspace import Workspace

PREFIX = "/agents/api/v1"


def _key(k: K.KeyInfo) -> dict[str, Any]:
    return {"ref": k.ref, "provider": k.provider, "label": k.label, "format": k.format, "base_url": k.base_url,
            "fingerprint": k.fingerprint, "status": k.status, "created": k.created, "last_used": k.last_used,
            "models": k.offered,
            "models_listed": bool(k.models)}


def _schedule(s: dict[str, Any]) -> dict[str, Any]:
    a = s["attrs"]
    return {"id": s["id"], "preset": a["preset"], "cron": a["cron"], "enabled": bool(a.get("enabled")),
            "next_at": a.get("next_at") if a.get("enabled") else None, "last_at": a.get("last_at"),
            "last_run": a.get("last_run"), "note": a.get("last_note", ""), "skipped": a.get("skipped", 0)}


def _preset(p: dict[str, Any], schedules: list[dict[str, Any]]) -> dict[str, Any]:
    a = p["attrs"]
    return {"name": a["name"], "title": a["title"], "goal": p["content"], "grant": a["grant"], "saved": a.get("saved"),
            "schedules": [_schedule(s) for s in schedules if s["attrs"]["preset"] == a["name"]]}


def _run_summary(t: Team, r: dict[str, Any]) -> dict[str, Any]:
    a = r["attrs"]
    u = t.run_usage(r["id"])
    return {"id": r["id"], "title": a.get("title", ""), "phase": a.get("phase"), "state": r["state"],
            "requested_by": r.get("origin") or r["author"], "preset": a.get("preset"), "schedule": a.get("schedule"),
            "agents": len(t.agents(r["id"])), "tokens": u.get("input", 0) + u.get("output", 0),
            "requested": a.get("requested"), "ended": a.get("ended")}


def _note(n: dict[str, Any]) -> dict[str, Any]:
    a = n["attrs"]
    return {"id": n["id"], "kind": a.get("kind"), "state": n["state"], "by": a.get("by"), "title": a.get("title"),
            "text": n["content"]}


def install(m: Any, *, stores: Callable[[str], Handbook], who: Callable[[Request], str | None], data_dir: Path,
            public_url: str, lock: Any) -> None:
    """Register the API's routes on the MCP server `m` (remote.build)."""
    from urllib.parse import urlparse

    origin = "{0.scheme}://{0.netloc}".format(urlparse(public_url))
    api = endpoint(origin=origin, user_errors=(HandbookError, K.KeyError_, cron.CronError))

    def route(path: str, methods: list[str]) -> Callable[..., Any]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            m.custom_route(PREFIX + path, methods=methods)(api(fn))
            return fn
        return deco

    def user(request: Request) -> str:
        uid = who(request)
        if uid is None:
            raise unauthorized()
        return uid

    async def locked(fn: Callable[[], Any]) -> Any:
        def run() -> Any:
            with lock:
                return fn()
        return await anyio.to_thread.run_sync(run)

    def keystore() -> K.KeyStore:
        return K.KeyStore.for_web(data_dir)

    def space(uid: str) -> tuple[Workspace, Team, Presets]:
        ws = Workspace(stores(uid))
        return ws, Team(ws.g), Presets(ws.g, crew.schedules_marker(ws))

    def grant_of(data: dict[str, Any], uid: str) -> dict[str, Any]:
        """The grant from a request, its keys checked to be the user's (check_grant does the rest)."""
        g = data.get("grant")
        if not isinstance(g, dict):
            raise bad("grant: an object (routes, limits, levels, policy, effort)")
        mine = {k.ref for k in keystore().list(uid)}
        for i, r in enumerate(g.get("routes") or []):
            if not isinstance(r, dict) or r.get("key") not in mine:
                raise bad(f"route {i + 1}: a key you registered")
        return g

    def approve_url(run: str) -> str:
        return f"/approvals/runs/{run}"

    # ── who, and the vocabulary ──────────────────────────────────────────

    @route("/me", ["GET"])
    async def me(request: Request) -> Any:
        return {"uid": user(request)}

    @route("/options", ["GET"])
    async def options(request: Request) -> Any:
        uid = user(request)
        policies = await locked(lambda: Workspace(stores(uid)).policies())
        return {"roles": list(ROLES), "context": list(CONTEXT_LEVELS), "handoff": list(HANDOFF_LEVELS),
                "retention": list(RETENTION_LEVELS), "efforts": list(EFFORTS), "policies": policies,
                "defaults": {k: v for k, v in DEFAULT_GRANT.items() if k != "routes"}, "max_routes": MAX_ROUTES,
                "providers": list(K.PROVIDERS), "formats": list(K.FORMATS)}

    # ── keys ─────────────────────────────────────────────────────────────

    @route("/keys", ["GET"])
    async def keys_list(request: Request) -> Any:
        uid = user(request)
        return [_key(k) for k in await anyio.to_thread.run_sync(lambda: keystore().list(uid))]

    @route("/keys", ["POST"])
    async def keys_add(request: Request) -> Any:
        uid = user(request)
        d = await body(request)
        provider, label = str(d.get("provider", "")), str(d.get("label", "")).strip()
        secret, fmt, base = str(d.get("secret", "")).strip(), str(d.get("format", "")), str(d.get("base_url", "")).strip()
        ks = keystore()
        if ks.public is None:
            raise ApiError(503, "unavailable", "keys cannot be registered until the administrator finishes the setup")
        models, status = await P.check_key(provider, secret, fmt, base)
        info = await anyio.to_thread.run_sync(lambda: ks.put(uid, provider, label, secret, fmt=fmt, base_url=base,
                                                             models=models))
        if status != "ok":
            await anyio.to_thread.run_sync(lambda: ks.mark(uid, provider, label, status))
            info.status = status
        return answer(_key(info), 201)

    @route("/keys/{provider}/{label}", ["DELETE"])
    async def keys_delete(request: Request) -> Any:
        uid = user(request)
        provider, label = K.split_ref(f"{request.path_params['provider']}/{request.path_params['label']}")
        if not await anyio.to_thread.run_sync(lambda: keystore().delete(uid, provider, label)):
            raise missing(f"no key {provider}/{label}")
        return {"deleted": f"{provider}/{label}"}

    # ── runs ─────────────────────────────────────────────────────────────

    def the_run(t: Team, run: str) -> dict[str, Any]:
        n = t.g.get_node(run) if run.startswith("run:") and len(run) <= 40 else None
        if n is None or n["type"] != "run":
            raise missing(f"no run {run}")
        return n

    @route("/runs", ["GET"])
    async def runs_list(request: Request) -> Any:
        uid = user(request)

        def get() -> Any:
            _, t, _ = space(uid)
            return [_run_summary(t, r) for r in t.runs()[:200]]
        return await locked(get)

    @route("/runs", ["POST"])
    async def runs_start(request: Request) -> Any:
        uid = user(request)
        d = await body(request)
        grant = grant_of(d, uid)

        def act() -> Any:
            ws, t, ps = space(uid)
            if str(d.get("save_as", "")).strip():
                ps.save(str(d["save_as"]), str(d.get("goal", "")), grant, title=str(d.get("title", "")))
            run = t.request_run(str(d.get("goal", "")), actor="user", title=str(d.get("title", "")).strip())
            try:
                t.approve(run, grant, actor="user")
            except HandbookError:
                t.cancel_run(run, "the grant was refused", actor="user")
                raise
            crew.mark(ws, run)
            return _run_summary(t, t.g.node(run))
        return answer(await locked(act), 201)

    @route("/runs/{run}", ["GET"])
    async def run_detail(request: Request) -> Any:
        uid = user(request)
        run = request.path_params["run"]

        def get() -> Any:
            _, t, _ = space(uid)
            r = the_run(t, run)
            a = r["attrs"]
            try:
                grant = t.grant(run)
            except TeamError:
                grant = None
            res = t.result(run)
            return {**_run_summary(t, r), "goal": r["content"], "error": a.get("error"), "grant": grant,
                    "proposal": a.get("proposal") if a.get("phase") == "requested" else None,
                    "approve_url": approve_url(run) if a.get("phase") == "requested" else None,
                    "usage": t.run_usage(run), "tree": t.tree(run),
                    "result": ({"outcome": res["attrs"].get("outcome"), "text": res["content"],
                                "notes": [_note(n) for n in t.carried(res["id"])]} if res else None),
                    "board": [_note(n) for n in t.board(run)[-50:]]}
        return await locked(get)

    @route("/runs/{run}/cancel", ["POST"])
    async def run_cancel(request: Request) -> Any:
        uid = user(request)
        run = request.path_params["run"]

        def act() -> Any:
            _, t, _ = space(uid)
            the_run(t, run)
            t.request_cancel(run, "cancelled by the user", by="user")
            return _run_summary(t, t.g.node(run))
        return await locked(act)

    # ── presets and schedules ────────────────────────────────────────────

    @route("/presets", ["GET"])
    async def presets_list(request: Request) -> Any:
        uid = user(request)

        def get() -> Any:
            _, _, ps = space(uid)
            sched = ps.schedules()
            return [_preset(p, sched) for p in ps.list()]
        return await locked(get)

    @route("/presets/{name}", ["PUT"])
    async def preset_put(request: Request) -> Any:
        uid = user(request)
        d = await body(request)
        grant = grant_of(d, uid)

        def act() -> Any:
            _, _, ps = space(uid)
            p = ps.save(request.path_params["name"], str(d.get("goal", "")), grant, title=str(d.get("title", "")))
            return _preset(p, ps.schedules())
        return await locked(act)

    @route("/presets/{name}", ["DELETE"])
    async def preset_delete(request: Request) -> Any:
        uid = user(request)

        def act() -> Any:
            _, _, ps = space(uid)
            ps.delete(request.path_params["name"])
            return {"deleted": request.path_params["name"]}
        return await locked(act)

    @route("/presets/{name}/run", ["POST"])
    async def preset_run(request: Request) -> Any:
        uid = user(request)

        def act() -> Any:
            ws, t, ps = space(uid)
            run = ps.start(request.path_params["name"])
            crew.mark(ws, run)
            return _run_summary(t, t.g.node(run))
        return answer(await locked(act), 201)

    @route("/presets/{name}/schedules", ["POST"])
    async def preset_schedule(request: Request) -> Any:
        uid = user(request)
        d = await body(request)

        def act() -> Any:
            _, _, ps = space(uid)
            return _schedule(ps.schedule(request.path_params["name"], str(d.get("cron", ""))))
        return answer(await locked(act), 201)

    def the_schedule(ps: Presets, sid: str) -> dict[str, Any]:
        s = next((x for x in ps.schedules() if x["id"] == sid), None)
        if s is None:
            raise missing(f"no schedule {sid}")
        return s

    @route("/schedules/{sid}", ["PATCH"])
    async def schedule_patch(request: Request) -> Any:
        uid = user(request)
        d = await body(request)
        if not isinstance(d.get("enabled"), bool):
            raise bad("enabled: true or false")

        def act() -> Any:
            _, _, ps = space(uid)
            the_schedule(ps, request.path_params["sid"])
            ps.set_enabled(request.path_params["sid"], d["enabled"])
            return _schedule(the_schedule(ps, request.path_params["sid"]))
        return await locked(act)

    @route("/schedules/{sid}", ["DELETE"])
    async def schedule_delete(request: Request) -> Any:
        uid = user(request)

        def act() -> Any:
            _, _, ps = space(uid)
            the_schedule(ps, request.path_params["sid"])
            ps.unschedule(request.path_params["sid"])
            return {"deleted": request.path_params["sid"]}
        return await locked(act)

    @route("/cron", ["POST"])
    async def cron_preview(request: Request) -> Any:
        user(request)
        d = await body(request)
        c = cron.parse(str(d.get("cron", "")))
        t, out = dt.datetime.now(), []
        for _ in range(5):
            t = c.next_after(t)
            out.append(t.timestamp())
        return {"cron": c.text, "next": out}

    # ── the workspace's files ────────────────────────────────────────────

    @route("/files", ["GET"])
    async def files(request: Request) -> Any:
        uid = user(request)
        rel = request.query_params.get("path", "").strip("/")[:1000]

        def get() -> Any:
            ws = Workspace(stores(uid))
            try:
                rows = ws.ls(rel or ".")
                return {"path": rel, "kind": "dir",
                        "entries": [{"name": n, "kind": k, "size": s} for n, k, s in rows]}
            except (HandbookError, OSError):
                pass
            parent, _, name = rel.rpartition("/")
            try:
                size = next((s for n, k, s in ws.ls(parent or ".") if n == name and k == "file"), None)
            except (HandbookError, OSError):
                size = None
            if size is None:
                raise missing(f"{rel}: no such file or directory")
            text = ws.read(rel, limit=500_000)
            return {"path": rel, "kind": "file", "size": size, "text": None if "\x00" in text[:8000] else text}
        return await locked(get)
