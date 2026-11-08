"""The account portal's JSON API, /account/api/v1 (docs/site.md "APIs and pages").

The operations are portal/accounts.py's, as the pages' are; this only reads requests and shapes
answers. Who is asking is the site sign-in's token (as for the pages). A one-time password (a new
account, a reset) is in the answer once and kept nowhere.

    GET    me                          the signed-in person: profile, groups, roles, what they may do
    PATCH  me                          {displayName, mail, loginShell}
    POST   me/password                 {old, new, confirm} → {changed[, warning]}
    GET    users?q=                    (helpdesk, admin)
    POST   users                       {uid, name, mail, loginShell} → {user, password[, warning]}   (admin)
    GET    users/{uid}                 the account, and what the caller may do to it
    POST   users/{uid}/reset           → {user, password[, warning]}
    POST   users/{uid}/unlock          the site's lock after failed passwords, and the KDC's → the account[, warning]
    PATCH  users/{uid}                 {enabled} → the account[, warning]
    PUT    users/{uid}/groups/{group}  /  DELETE users/{uid}/groups/{group}
    DELETE users/{uid}?confirm={uid}
    GET    groups
    GET    requests                    POST requests/{id}/approve {loginShell} → {user, password[, warning]}
                                       POST requests/{id}/reject
    GET    invites                     POST invites {note} → {invite, link}   POST invites/{id}/revoke

A warning: the site has set a password or disabled an account in Kerberos, and the SMB side could not
follow (docs/smb.md); the change itself stands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from .accounts import BACKEND_ERRORS, Accounts, Forbidden
from .api import answer, bad, body, endpoint, unauthorized
from .directory import User
from .rbac import Actor
from .validators import ValidationError

PREFIX = "/api/v1"


def warned(out: dict[str, Any], warning: str | None) -> dict[str, Any]:
    """An answer, with the warning when there is one."""
    return {**out, "warning": warning} if warning else out
ACTIONS = ("view_users", "create_user", "reset_password", "unlock", "set_enabled", "manage_groups", "delete_user",
           "review_requests", "manage_invites")


def user_json(u: User) -> dict[str, Any]:
    """An account as the API shows it: no directory names or sign-in internals."""
    return {"uid": u.uid, "name": u.cn if u.cn != u.uid else "", "display_name": u.display_name, "mail": u.mail,
            "login_shell": u.login_shell, "uid_number": u.uid_number, "gid_number": u.gid_number, "home": u.home,
            "groups": u.groups, "disabled": u.disabled, "failed_logins": u.failed_logins,
            "complete": bool(u.principals)}


def install(app: Any, acc: Accounts, *, signed_in_uid: Callable[[Request], str | None], ip: Callable[[Request], str],
            join_link: Callable[[str], str]) -> None:
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

    def may(actor: Actor, target: User | None = None) -> dict[str, bool]:
        return {a: acc.may(actor, a, target) for a in ACTIONS}

    @route("/me", ["GET"])
    async def me(request: Request) -> Any:
        actor = await who(request)
        return {"user": user_json(actor.user), "roles": sorted(actor.roles), "may": may(actor),
                "shells": list(acc.s.allowed_shells), "requests": acc.requests is not None,
                "invites": acc.invites is not None}

    @route("/me", ["PATCH"])
    async def me_patch(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        return user_json(await call(acc.update_profile, actor, d, ip(request)))

    @route("/me/password", ["POST"])
    async def me_password(request: Request) -> Any:
        from .kerberos import KerberosError

        actor = await who(request)
        d = await body(request)
        try:
            warning = await call(acc.change_password, actor, str(d.get("old", "")), str(d.get("new", "")),
                                 str(d.get("confirm", "")), ip(request))
        except KerberosError as e:  # a wrong current password, a rejected new one: the person's to fix
            raise bad(str(e)) from e
        return warned({"changed": True}, warning)

    @route("/users", ["GET"])
    async def users(request: Request) -> Any:
        actor = await who(request)
        return [user_json(u) for u in await call(acc.users, actor, request.query_params.get("q", ""))]

    @route("/users", ["POST"])
    async def users_create(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        user, password, warning = await call(acc.create, actor, d, ip(request))
        return answer(warned({"user": user_json(user), "password": password}, warning), 201)

    @route("/users/{uid}", ["GET"])
    async def user(request: Request) -> Any:
        actor = await who(request)
        target = await call(acc.user, actor, request.path_params["uid"])
        groups = [g for g, _ in await call(acc.groups, actor) if g != target.uid]
        return {"user": user_json(target), "may": may(actor, target),
                "addable_groups": [g for g in groups if g not in target.groups]}

    @route("/users/{uid}/reset", ["POST"])
    async def reset(request: Request) -> Any:
        actor = await who(request)
        target, password, warning = await call(acc.reset_password, actor, request.path_params["uid"], ip(request))
        return warned({"user": user_json(target), "password": password}, warning)

    @route("/users/{uid}/unlock", ["POST"])
    async def unlock(request: Request) -> Any:
        actor = await who(request)
        target, warning = await call(acc.unlock, actor, request.path_params["uid"], ip(request))
        return warned(user_json(target), warning)

    @route("/users/{uid}", ["PATCH"])
    async def user_patch(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        if not isinstance(d.get("enabled"), bool):
            raise bad("enabled: true or false")
        target, warning = await call(acc.set_enabled, actor, request.path_params["uid"], d["enabled"], ip(request))
        return warned(user_json(target), warning)

    @route("/users/{uid}/groups/{group}", ["PUT", "DELETE"])
    async def membership(request: Request) -> Any:
        actor = await who(request)
        return user_json(await call(acc.set_group, actor, request.path_params["uid"], request.path_params["group"],
                                    request.method == "PUT", ip(request)))

    @route("/users/{uid}", ["DELETE"])
    async def user_delete(request: Request) -> Any:
        actor = await who(request)
        target = await call(acc.delete, actor, request.path_params["uid"], request.query_params.get("confirm", ""),
                            ip(request))
        return {"deleted": target.uid}

    @route("/groups", ["GET"])
    async def groups(request: Request) -> Any:
        actor = await who(request)
        return [{"name": g, "gid": n} for g, n in await call(acc.groups, actor)]

    @route("/requests", ["GET"])
    async def requests(request: Request) -> Any:
        actor = await who(request)
        return [{"id": r.id, "uid": r.uid, "name": r.name, "mail": r.mail, "purpose": r.purpose, "created": r.created}
                for r in await call(acc.pending_requests, actor)]

    @route("/requests/{rid}/approve", ["POST"])
    async def request_approve(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        user, password, warning = await call(acc.approve_request, actor, request.path_params["rid"],
                                             str(d.get("loginShell", "")), ip(request))
        return answer(warned({"user": user_json(user), "password": password}, warning), 201)

    @route("/requests/{rid}/reject", ["POST"])
    async def request_reject(request: Request) -> Any:
        actor = await who(request)
        return {"rejected": await call(acc.reject_request, actor, request.path_params["rid"], ip(request))}

    @route("/invites", ["GET"])
    async def invites(request: Request) -> Any:
        actor = await who(request)
        return [{"id": i.id, "note": i.note, "created_by": i.created_by, "created": i.created, "expires": i.expires}
                for i in await call(acc.invitations, actor)]

    @route("/invites", ["POST"])
    async def invite(request: Request) -> Any:
        actor = await who(request)
        d = await body(request)
        inv, token = await call(acc.invite, actor, str(d.get("note", "")), ip(request))
        return answer({"invite": {"id": inv.id, "note": inv.note, "expires": inv.expires}, "link": join_link(token)}, 201)

    @route("/invites/{iid}/revoke", ["POST"])
    async def invite_revoke(request: Request) -> Any:
        actor = await who(request)
        return {"revoked": await call(acc.revoke_invite, actor, request.path_params["iid"], ip(request))}
