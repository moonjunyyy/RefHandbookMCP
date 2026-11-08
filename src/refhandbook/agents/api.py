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
    GET    files?path=                the workspace: a directory's entries or a file's text
    GET    files/download?path=       a file as it is, or a folder (the workspace itself when path is empty) as a zip;
                                      several path= as one zip, each under its own name
    POST   files/move                 {from, to}: rename or move a file or a folder; nothing is overwritten;
                                      {from: [..], into}: several into one folder, all checked before any moves
    POST   files/mkdir                {path}: a new folder
    DELETE files?path=                a file, or a folder with what it holds (the workspace itself stays); several path=

The workspace is the user's only way to their sandbox's files (/work: the scripts' and the runs'), so the
pages manage it here; every name is resolved by Workspace on descriptors, no symlink followed.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import IO, Any
from urllib.parse import quote

import anyio
from starlette.requests import Request
from starlette.responses import StreamingResponse

from portal.api import ApiError, answer, bad, body, endpoint, missing, unauthorized

from ..store import Handbook, HandbookError
from . import cron, crew, flows
from . import providers as P
from . import keys as K
from .branches import Branches
from .presets import Presets
from .team import (CONTEXT_LEVELS, DEFAULT_GRANT, EFFORTS, HANDOFF_LEVELS, MAX_ROUTES, RETENTION_LEVELS, ROLES,
                   Team, TeamError)
from .workspace import Workspace, WorkspaceError

PREFIX = "/agents/api/v1"
CHUNK = 1 << 16
log = logging.getLogger("refhandbook.agents.api")


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
    return {"name": a["name"], "title": a["title"], "goal": p["content"], "grant": a["grant"], "flow": a.get("flow"),
            "saved": a.get("saved"),
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


def _attachment(name: str) -> str:
    """A Content-Disposition that saves the response as `name` (RFC 6266: an ASCII fallback, and the name itself)."""
    plain = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name) or "download"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


async def _file_chunks(f: IO[bytes]) -> AsyncIterator[bytes]:
    """An open file's bytes, read off the event loop."""
    try:
        while chunk := await anyio.to_thread.run_sync(f.read, CHUNK):
            yield chunk
    finally:
        f.close()


async def _piped(write: Callable[[IO[bytes]], Any]) -> AsyncIterator[bytes]:
    """What `write` writes to a stream, as it is written: `write` runs in a thread on a pipe's end and the
    response reads the other. A reader that goes away closes its end, and the writer stops on the broken pipe."""
    r, w = os.pipe()

    def produce() -> None:
        try:
            with os.fdopen(w, "wb") as out:
                write(out)
        except BrokenPipeError:
            pass
        except Exception:  # noqa: BLE001 — the response is under way: cut it short, and say why in the log
            log.exception("writing a download")

    threading.Thread(target=produce, name="download", daemon=True).start()
    try:
        while chunk := await anyio.to_thread.run_sync(os.read, r, CHUNK):
            yield chunk
    finally:
        os.close(r)


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

    def grant_of(data: dict[str, Any], uid: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        """What a run or preset is given, from a request: the limits, the flow (its blocks' keys checked
        to be the user's) and the input. A goal with a routing table, as before flows, reads as a flow
        of one team block told that goal (flows.from_grant), with no input."""
        g = data.get("grant") or {}
        if not isinstance(g, dict):
            raise bad("grant: an object (limits, levels, policy, effort)")
        flow, given = data.get("flow"), str(data.get("goal", ""))
        if flow is None:
            if not given.strip():
                raise bad("a goal, or a flow")
            flow, given = flows.from_grant(given, g), ""
        mine = {k.ref for k in keystore().list(uid)}
        try:
            flow = flows.check(flow, mine)
        except TeamError as e:
            raise bad(str(e)) from e
        return flows.limits(g), flow, given

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

        def get() -> Any:
            _, _, ps = space(uid)
            used: dict[str, list[str]] = {}
            for p in ps.list():
                for st in (p["attrs"].get("flow") or {}).get("steps", []):
                    names = used.setdefault(st.get("key", ""), [])
                    if p["attrs"]["name"] not in names:
                        names.append(p["attrs"]["name"])
            return [{**_key(k), "used_by": used.get(k.ref, [])} for k in keystore().list(uid)]
        return await locked(get)

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

    def branches_of(ws: Workspace, run: str, a: dict[str, Any]) -> dict[str, Any] | None:
        """What became of the run's branches (kept on the run at its end), or, while it runs, what they are."""
        if a.get("branches"):
            return a["branches"]
        got = Branches(crew.run_dir(ws, run), run).listing()
        return got if got["repos"] or got["why"] else None

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
        grant, flow, given = grant_of(d, uid)

        def act() -> Any:
            ws, t, ps = space(uid)
            if str(d.get("save_as", "")).strip():
                ps.save(str(d["save_as"]), given, grant, title=str(d.get("title", "")), flow=flow)
            run = t.begin(given, grant, title=str(d.get("title", "")).strip(), flow=flow)
            crew.mark(ws, run)
            return _run_summary(t, t.g.node(run))
        return answer(await locked(act), 201)

    @route("/runs/{run}", ["GET"])
    async def run_detail(request: Request) -> Any:
        uid = user(request)
        run = request.path_params["run"]

        def get() -> Any:
            ws, t, _ = space(uid)
            r = the_run(t, run)
            a = r["attrs"]
            try:
                grant = t.grant(run)
            except TeamError:
                grant = None
            res = t.result(run)
            root = t.root(run)
            ra = t.g.node(root)["attrs"] if root else {}
            given = "" if a.get("no_input") else r["content"]
            # what it was started with, to start it again or keep as a preset, always as a flow
            recipe = ({"input": given, "flow": a["flow"]} if a.get("flow")
                      else {"input": "", "flow": flows.from_grant(r["content"], grant or a.get("proposal"))})
            recipe.update(title=a.get("title", ""), grant=flows.limits(grant))
            return {**_run_summary(t, r), "goal": r["content"], "input": given, "recipe": recipe,
                    "error": a.get("error"), "grant": grant,
                    "flow": a.get("flow"), "flow_path": ra.get("flow_path") or [], "flow_end": ra.get("flow_end"),
                    "proposal": a.get("proposal") if a.get("phase") == "requested" else None,
                    "approve_url": approve_url(run) if a.get("phase") == "requested" else None,
                    "usage": t.run_usage(run), "tree": t.tree(run),
                    "result": ({"outcome": res["attrs"].get("outcome"), "text": res["content"],
                                "notes": [_note(n) for n in t.carried(res["id"])]} if res else None),
                    "board": [_note(n) for n in t.board(run)[-50:]], "branches": branches_of(ws, run, a)}
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
        grant, flow, given = grant_of(d, uid)

        def act() -> Any:
            _, _, ps = space(uid)
            p = ps.save(request.path_params["name"], given, grant, title=str(d.get("title", "")), flow=flow)
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

    def workspace_path(value: Any) -> str:
        if not isinstance(value, str) or not value.strip("/ "):
            raise bad("a path in the workspace")
        return value.strip().strip("/")[:1000]

    @route("/files/download", ["GET"])
    async def files_download(request: Request) -> Any:
        """A file as it is; a folder (the workspace itself when path is empty) as a zip, streamed as it is packed."""
        uid = user(request)
        many = [p.strip("/")[:1000] for p in request.query_params.getlist("path")]
        if len(many) > 1:
            return await download_several(uid, many)
        rel = request.query_params.get("path", "").strip("/")[:1000]

        def open_() -> tuple[Workspace, str, IO[bytes] | None, int]:
            ws = Workspace(stores(uid))
            try:
                kind = ws.kind(rel)
            except WorkspaceError as e:
                raise missing(f"{rel}: no such file or directory") from e
            if kind == "dir":
                return ws, kind, None, 0
            if kind != "file":
                raise bad(f"{rel}: a {kind} is not downloaded (only files and folders)")
            f, size = ws.open_file(rel)
            return ws, kind, f, size
        ws, kind, f, size = await locked(open_)
        name = rel.rsplit("/", 1)[-1] or "work"
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if f is not None:
            return StreamingResponse(_file_chunks(f), media_type="application/octet-stream",
                                     headers={**headers, "Content-Disposition": _attachment(name), "Content-Length": str(size)})
        return StreamingResponse(_piped(lambda out: ws.zip_dir(rel, out)), media_type="application/zip",
                                 headers={**headers, "Content-Disposition": _attachment(name + ".zip")})

    async def download_several(uid: str, rels: list[str]) -> Any:
        """Several entries (the selection of the page) as one zip, each under its own name, named after their folder."""
        def check() -> Workspace:
            ws = Workspace(stores(uid))
            for rel in rels:
                try:
                    kind = ws.kind(rel)
                except WorkspaceError as e:
                    raise missing(f"{rel}: no such file or directory") from e
                if kind not in ("dir", "file") or not rel:
                    raise bad(f"{rel or '/work'}: only files and folders of the workspace are downloaded together")
            ws.zip_selection(rels)
            return ws
        ws = await locked(check)
        parents = {r.rpartition("/")[0] for r in rels}
        name = (parents.pop().rsplit("/", 1)[-1] if len(parents) == 1 else "") or "work"
        return StreamingResponse(_piped(lambda out: ws.zip_paths(rels, out)), media_type="application/zip",
                                 headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                          "Content-Disposition": _attachment(name + ".zip")})

    @route("/files/move", ["POST"])
    async def files_move(request: Request) -> Any:
        uid = user(request)
        d = await body(request)
        if isinstance(d.get("from"), list):
            srcs = [workspace_path(x) for x in d["from"]]
            into = d.get("into")
            if not isinstance(into, str):
                raise bad("into: the folder to move them into ('' for the workspace itself)")
            dest = into.strip().strip("/")[:1000]
            return await locked(lambda: {"moved": [{"from": s, "path": p} for s, p in
                                                   zip(srcs, Workspace(stores(uid)).move_into(srcs, dest))]})
        src, dst = workspace_path(d.get("from")), workspace_path(d.get("to"))
        return await locked(lambda: {"from": src, "path": Workspace(stores(uid)).move(src, dst)})

    @route("/files/mkdir", ["POST"])
    async def files_mkdir(request: Request) -> Any:
        uid = user(request)
        rel = workspace_path((await body(request)).get("path"))
        return answer(await locked(lambda: {"path": Workspace(stores(uid)).mkdir(rel)}), 201)

    @route("/files", ["DELETE"])
    async def files_delete(request: Request) -> Any:
        uid = user(request)
        rels = [workspace_path(p) for p in request.query_params.getlist("path")] or [workspace_path("")]

        def act() -> Any:
            ws = Workspace(stores(uid))
            for rel in rels:
                ws.kind(rel)  # every one there before any goes
            for rel in rels:
                ws.remove(rel)
            return {"deleted": rels[0] if len(rels) == 1 else rels}
        return await locked(act)
