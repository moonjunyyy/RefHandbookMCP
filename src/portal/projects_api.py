"""The projects' JSON API, /account/api/v1/projects (docs/site.md "APIs and pages", docs/projects.md).

The operations are portal/projects.py's; this only reads requests and shapes answers. Who is asking
is the site sign-in's token, as for the account API; `may` in each answer is what they may do here.

    GET    projects                          {projects: [view, ...], may_create}
    POST   projects                          {name, title, description, join_policy, listed} → view   (201)
    POST   projects/join                     {token} → view                         (an invitation link)
    GET    projects/{cn}                     view, with requests and invites for one who manages it
    PATCH  projects/{cn}                     {title, description, join_policy, listed}
    DELETE projects/{cn}?confirm={cn}        for good: the group, the record, the links → {deleted}
    POST   projects/{cn}/join                {note} → view   (open: in; request: waiting; invite: refused)
    POST   projects/{cn}/withdraw            take a waiting request back
    POST   projects/{cn}/leave
    PUT    projects/{cn}/members/{uid}       DELETE projects/{cn}/members/{uid}
    PUT    projects/{cn}/owners/{uid}        DELETE projects/{cn}/owners/{uid}
    POST   projects/{cn}/requests/{rid}/approve   POST projects/{cn}/requests/{rid}/reject
    POST   projects/{cn}/invites {note}      → {invite, link}   (201)
    POST   projects/{cn}/invites/{iid}/revoke
    POST   projects/{cn}/archive             POST projects/{cn}/restore
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from .accounts import BACKEND_ERRORS, Accounts, Forbidden
from .api import answer, bad, body, endpoint, unauthorized
from .projects import JoinRequest, ProjectInvite, Projects, View
from .rbac import Actor
from .validators import ValidationError

PREFIX = "/api/v1/projects"


def view_json(v: View) -> dict[str, Any]:
    manages = v.manages
    return {"cn": v.cn, "gid": v.gid, "title": v.title, "description": v.description, "join_policy": v.join_policy,
            "listed": v.listed, "created": v.created, "created_by": v.created_by, "archived": v.archived or None,
            "members": v.members, "owners": v.owners, "role": v.role, "member": v.member, "requested": v.requested,
            "may": {"manage": manages, "leave": v.member and not (v.role == "owner" and len(v.owners) == 1),
                    "join": not v.member and not v.archived and v.join_policy in ("open", "request") and not v.requested,
                    "archive": manages and not v.archived, "restore": manages and bool(v.archived),
                    "delete": manages}}


def request_json(r: JoinRequest) -> dict[str, Any]:
    return {"id": r.id, "uid": r.uid, "note": r.note, "created": r.created}


def invite_json(i: ProjectInvite) -> dict[str, Any]:
    return {"id": i.id, "note": i.note, "created_by": i.created_by, "created": i.created, "expires": i.expires}


def install(app: Any, acc: Accounts, prj: Projects, *, signed_in_uid: Callable[[Request], str | None],
            ip: Callable[[Request], str], join_link: Callable[[str], str]) -> None:
    api = endpoint(origin=acc.s.public_url, user_errors=(ValidationError,), refusals=(Forbidden,),
                   backend_errors=BACKEND_ERRORS)

    def route(path: str, methods: list[str]) -> Callable[..., Any]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            app.add_route(PREFIX + path, api(fn), methods=methods)
            return fn
        return deco

    async def who(request: Request) -> Actor:
        actor = await run_in_threadpool(acc.actor, signed_in_uid(request))
        if actor is None:
            raise unauthorized()
        return actor

    def call(fn: Callable[..., Any], *args: Any) -> Any:
        return run_in_threadpool(fn, *args)

    def cn(request: Request) -> str:
        return request.path_params["cn"]

    @route("", ["GET"])
    async def projects(request: Request) -> Any:
        actor = await who(request)
        return {"projects": [view_json(v) for v in await call(prj.list, actor)], "may_create": prj.may_create(actor)}

    @route("", ["POST"])
    async def create(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        return answer(view_json(await call(prj.create, actor, d, ip(request))), 201)

    @route("/join", ["POST"])
    async def join_by_invite(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        token = str(d.get("token", ""))
        if not token:
            raise bad("token: the invitation link's token")
        return view_json(await call(prj.join_by_invite, actor, token, ip(request)))

    @route("/{cn}", ["GET"])
    async def project(request: Request) -> Any:
        actor = await who(request)
        v = await call(prj.get, actor, cn(request))
        out = view_json(v)
        if v.manages:
            out["requests"] = [request_json(r) for r in await call(prj.requests, actor, v.cn)]
            out["invites"] = [invite_json(i) for i in await call(prj.invites, actor, v.cn)]
        return out

    @route("/{cn}", ["PATCH"])
    async def project_patch(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        return view_json(await call(prj.update, actor, cn(request), d, ip(request)))

    @route("/{cn}", ["DELETE"])
    async def project_delete(request: Request) -> Any:
        actor = await who(request)
        v = await call(prj.delete, actor, cn(request), request.query_params.get("confirm", ""), ip(request))
        return {"deleted": v.cn}

    @route("/{cn}/join", ["POST"])
    async def join(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        return view_json(await call(prj.join, actor, cn(request), str(d.get("note", "")), ip(request)))

    @route("/{cn}/withdraw", ["POST"])
    async def withdraw(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.withdraw, actor, cn(request), ip(request)))

    @route("/{cn}/leave", ["POST"])
    async def leave(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.leave, actor, cn(request), ip(request)))

    @route("/{cn}/members/{uid}", ["PUT", "DELETE"])
    async def member(request: Request) -> Any:
        actor = await who(request)
        fn = prj.add_member if request.method == "PUT" else prj.remove_member
        return view_json(await call(fn, actor, cn(request), request.path_params["uid"], ip(request)))

    @route("/{cn}/owners/{uid}", ["PUT", "DELETE"])
    async def owner(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.set_owner, actor, cn(request), request.path_params["uid"],
                                    request.method == "PUT", ip(request)))

    @route("/{cn}/requests/{rid}/approve", ["POST"])
    async def approve(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.approve, actor, cn(request), request.path_params["rid"], ip(request)))

    @route("/{cn}/requests/{rid}/reject", ["POST"])
    async def reject(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.reject, actor, cn(request), request.path_params["rid"], ip(request)))

    @route("/{cn}/invites", ["POST"])
    async def invite(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        inv, token = await call(prj.invite, actor, cn(request), str(d.get("note", "")), ip(request))
        return answer({"invite": invite_json(inv), "link": join_link(token)}, 201)

    @route("/{cn}/invites/{iid}/revoke", ["POST"])
    async def invite_revoke(request: Request) -> Any:
        actor = await who(request)
        return {"revoked": await call(prj.revoke_invite, actor, cn(request), request.path_params["iid"], ip(request))}

    @route("/{cn}/archive", ["POST"])
    async def archive(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.archive, actor, cn(request), ip(request)))

    @route("/{cn}/restore", ["POST"])
    async def restore(request: Request) -> Any:
        actor = await who(request)
        return view_json(await call(prj.restore, actor, cn(request), ip(request)))
