"""FastAPI app: login, self-service profile/password, account requests, invitation sign-up, and the
admin/helpdesk console."""
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import audit, i18n, tokens, validators
from .accounts import Accounts, Forbidden
from .config import Settings
from .facts import SIGNIN
from .directory import Directory, DirectoryError, User
from .invites import InviteError, InviteStore
from .kerberos import KAdmin, Kerberos, KerberosError, LoginResult
from .rbac import Actor, can, roles_for
from .requests import RequestError, RequestStore
from .security import SecurityHeadersMiddleware, Throttle, csrf_ok, csrf_token
from .i18n import t
from .validators import ValidationError

HERE = Path(__file__).parent


class LoginRequired(Exception):
    pass


class RootPath:
    """Serve under a sub-path whether nginx passes /account/... as is or strips the prefix.

    Starlette expects `path` to include `root_path` and routes on the remainder, so the prefix is
    put back when it was stripped. Links and redirects add it themselves (see url())."""

    def __init__(self, app, prefix: str):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.prefix:
            path = scope["path"]
            if path == self.prefix:
                path += "/"
            elif not path.startswith(self.prefix + "/"):
                path = self.prefix + path
            scope = dict(scope, path=path, root_path=self.prefix)
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None, directory=None, kerberos=None, kadmin=None,
               requests: RequestStore | None = None, sso_public_key=None,
               invites: InviteStore | None = None) -> FastAPI:
    s = settings or Settings()
    s.site()  # apps.toml is read at start: a bad file stops the portal, not a page
    sso = s.auth_mode == "sso"
    if sso and sso_public_key is None:
        sso_public_key = tokens.load_public_key(s.sso_public_key_file)
    if len(s.session_secret) < 32:
        raise RuntimeError("PORTAL_SESSION_SECRET must be set to at least 32 random characters.")
    directory = directory or Directory(s)
    kerberos = kerberos or Kerberos(s)
    kadmin = kadmin or KAdmin(s)
    if requests is None and s.requests_enabled:
        requests = RequestStore(s.requests_db, s.request_ttl_days, s.request_max_pending)
    if invites is None and s.invites_enabled:
        invites = InviteStore(s.invites_db, s.invite_ttl_hours)
    throttle = Throttle()
    join_throttle = Throttle(limit=10, window=3600)  # failed invitation sign-ups per client address
    request_throttle = Throttle(limit=5, window=3600)  # account requests per client address
    audit.setup(s.audit_log)
    acc = Accounts(s, directory, kerberos, kadmin, requests, invites, throttle)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=s.session_secret, session_cookie="portal_session",
                       max_age=s.session_max_age, same_site="strict", https_only=s.cookie_secure,
                       path=s.root_path or "/")
    app.add_middleware(i18n.Language)  # the request's language, for every message and page under it
    app.add_middleware(RootPath, prefix=s.root_path)  # added last, so it runs first
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(t=i18n.t, lang=i18n.current)

    # ---- helpers -----------------------------------------------------------------------------

    def ip(request: Request) -> str:
        return request.client.host if request.client else "-"

    def url(path: str) -> str:
        return s.root_path + path

    def flash(request: Request, kind: str, msg: str) -> None:
        request.session.setdefault("flash", []).append([kind, msg])

    def render(request: Request, name: str, actor: Actor | None = None, **ctx):
        ctx.update(actor=actor, csrf=csrf_token(request.session), flashes=request.session.pop("flash", []),
                   can=(lambda action, target=None: actor is not None and can(actor, action, s, target)),
                   settings=s, url=url, sso=sso, signin=SIGNIN, requests_enabled=requests is not None,
                   invites_enabled=invites is not None,
                   site_menu=s.site().menu(set(actor.user.groups) if actor else set()),
                   pending_requests=(lambda: requests.count() if requests is not None else 0))
        return templates.TemplateResponse(request, name, ctx)

    def redirect(path: str) -> RedirectResponse:
        return RedirectResponse(url(path), status_code=303)

    async def form(request: Request) -> dict:
        data = await request.form()
        if not csrf_ok(request.session, data.get("csrf")):
            raise Forbidden("Invalid or missing CSRF token. Reload the page and try again.")
        return data

    def signed_in_uid(request: Request) -> str | None:
        if sso:  # the SSO's token, minted for this backend by /auth/check a moment ago
            token = request.headers.get("x-auth-token", "")
            try:
                return tokens.verify(sso_public_key, token, s.sso_issuer, s.token_audience) if token else None
            except tokens.TokenError:
                return None
        uid = request.session.get("uid")
        if not uid or time.time() - request.session.get("login_at", 0) > s.session_max_age:
            return None
        return uid

    def current_actor(request: Request) -> Actor:
        """Re-checked on every request so disabling a user or removing a role takes effect at once."""
        actor = acc.actor(signed_in_uid(request))
        if actor is None:
            if not sso:
                request.session.clear()
            raise LoginRequired()
        return actor

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if sso:
            back = s.root_path + request.url.path.removeprefix(s.root_path)
            return RedirectResponse(f"{s.login_url}?next={back}", status_code=303)
        return redirect("/login")

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        resp = render(request, "error.html", message=str(exc))
        resp.status_code = 403
        return resp

    @app.exception_handler(DirectoryError)
    @app.exception_handler(KerberosError)
    async def _backend_error(request: Request, exc: Exception):
        ref = secrets.token_hex(4)  # the page says this; the audit log says what went wrong, under it
        audit.record(request.session.get("uid"), "backend_error", None, False, ip(request), f"[{ref}] {exc}")
        resp = render(request, "error.html", message=f"The operation could not be completed. "
                                                     f"Tell an administrator the reference {ref}.")
        resp.status_code = 502
        return resp

    # ---- login -------------------------------------------------------------------------------

    @app.get("/login")
    async def login_page(request: Request):
        if sso:
            return RedirectResponse(f"{s.login_url}?next={url('/')}", status_code=303)
        return render(request, "login.html")

    @app.post("/login")
    async def login(request: Request):
        if sso:
            raise Forbidden("Sign in at the site sign-in page.")
        data = await form(request)
        raw_uid, password = str(data.get("uid", "")).strip().lower(), str(data.get("password", ""))
        keys = (f"ip:{ip(request)}", f"uid:{raw_uid}")
        if throttle.blocked(*keys):
            audit.record(raw_uid, "login", None, False, ip(request), "throttled")
            flash(request, "error", "Too many failed attempts. Try again in 15 minutes.")
            return redirect("/login")
        try:
            uid = validators.uid(raw_uid)
        except ValidationError:
            uid = None
        result = LoginResult.BAD
        if uid and password and directory.get_user(uid) is not None:
            result = kerberos.verify_password(s.principal(uid), password)
        audit.record(uid or raw_uid, "login", None, result is LoginResult.OK, ip(request), result.value)
        if result is LoginResult.EXPIRED:
            request.session["expired_uid"] = uid
            flash(request, "info", "Your password has expired or must be changed before first use.")
            return redirect("/expired")
        if result is not LoginResult.OK:
            throttle.fail(*keys)
            flash(request, "error", "Invalid username or password."
                  if result is LoginResult.BAD else "This account is disabled or locked.")
            return redirect("/login")
        throttle.reset(f"uid:{uid}")
        request.session.clear()  # new session on login
        request.session.update(uid=uid, login_at=time.time())
        return redirect("/")

    @app.get("/expired")
    async def expired_page(request: Request):
        if sso:
            return RedirectResponse(f"{SIGNIN}/expired", status_code=303)
        return render(request, "expired.html", uid=request.session.get("expired_uid", ""))

    @app.post("/expired")
    async def expired_change(request: Request):
        if sso:
            raise Forbidden("Change it at the site sign-in page.")
        data = await form(request)
        raw_uid = str(data.get("uid", "")).strip().lower()
        keys = (f"ip:{ip(request)}", f"uid:{raw_uid}")
        if throttle.blocked(*keys):
            flash(request, "error", "Too many failed attempts. Try again in 15 minutes.")
            return redirect("/expired")
        try:
            uid = validators.uid(raw_uid)
            new = validators.new_password(str(data.get("new", "")), str(data.get("confirm", "")))
            kerberos.change_own_password(s.principal(uid), str(data.get("old", "")), new)
        except (ValidationError, KerberosError) as e:
            throttle.fail(*keys)
            audit.record(raw_uid, "change_expired_password", raw_uid, False, ip(request), str(e))
            flash(request, "error", str(e))
            return redirect("/expired")
        audit.record(uid, "change_expired_password", uid, True, ip(request))
        request.session.pop("expired_uid", None)
        flash(request, "ok", "Password changed. Please sign in with your new password.")
        return redirect("/login")

    @app.post("/logout")
    async def logout(request: Request):
        await form(request)
        audit.record(request.session.get("uid"), "logout", None, True, ip(request))
        request.session.clear()
        return redirect("/login")

    # ---- self-service ------------------------------------------------------------------------

    @app.get("/")
    async def home(request: Request):
        actor = current_actor(request)
        return render(request, "home.html", actor, me=actor.user)

    @app.post("/profile")
    async def update_profile(request: Request):
        actor = current_actor(request)
        data = await form(request)
        try:
            acc.update_profile(actor, dict(data), ip(request))
        except ValidationError as e:
            flash(request, "error", str(e))
            return redirect("/")
        flash(request, "ok", "Profile updated.")
        return redirect("/")

    @app.post("/password")
    async def change_password(request: Request):
        actor = current_actor(request)
        data = await form(request)
        try:
            acc.change_password(actor, str(data.get("old", "")), str(data.get("new", "")), str(data.get("confirm", "")),
                                ip(request))
        except (ValidationError, KerberosError, Forbidden) as e:
            flash(request, "error", str(e))
            return redirect("/")
        flash(request, "ok", "Password changed.")
        return redirect("/")

    def shown_once(request: Request, actor: Actor, made: tuple[User, str], created: bool):
        """The page with a one-time password (made or reset): shown once, never kept."""
        user, password = made
        return render(request, "temp_password.html", actor, target=user, password=password, created=created)

    # ---- account requests (public) -------------------------------------------------------------

    def requests_on():
        if requests is None:
            raise Forbidden("Account requests are not enabled here.")
        return requests

    @app.get("/request")
    async def request_page(request: Request):
        requests_on()
        return render(request, "request.html", values={})

    @app.post("/request")
    async def request_submit(request: Request):
        store = requests_on()
        data = await form(request)
        key = f"req:{ip(request)}"
        if request_throttle.blocked(key):
            flash(request, "error", t("신청이 너무 많습니다. 한 시간 뒤 다시 시도해 주세요."))
            return render(request, "request.html", values=dict(data))
        request_throttle.fail(key)  # every submission counts, accepted or not
        try:
            if data.get("consent") != "1":
                raise ValidationError(t("개인정보 수집·이용에 동의해야 신청할 수 있습니다."))
            uid = validators.new_uid(str(data.get("uid", "")).strip().lower())
            name = validators.optional_name(str(data.get("name", "")), t("이름"))
            mail = validators.email(str(data.get("mail", "")))
            purpose = validators.purpose(str(data.get("purpose", "")))
        except ValidationError as e:
            flash(request, "error", str(e))
            return render(request, "request.html", values=dict(data))
        try:
            # Same answer whether or not the name is taken or already requested: this page is public,
            # and it should not tell anyone which usernames exist.
            added = store.add(uid, name, mail, purpose)
        except RequestError:
            flash(request, "error", t("지금은 신청을 받을 수 없습니다. 관리자에게 직접 문의해 주세요."))
            return render(request, "request.html", values=dict(data))
        audit.record(None, "account_request", uid, added, ip(request), "" if added else "duplicate")
        return render(request, "request_done.html")

    # ---- sign-up by invitation (public, with a link an admin made) -----------------------------

    def invites_on() -> InviteStore:
        if invites is None:
            raise Forbidden("Invitations are not enabled here.")
        return invites

    def join_page(request: Request, token: str, status: int = 200, **values):
        resp = render(request, "join.html", token=token, values=values)
        resp.status_code = status
        return resp

    @app.get("/join/{token}")
    async def join_form(request: Request, token: str):
        if invites_on().find(token[:64]) is None:
            resp = render(request, "join_invalid.html")
            resp.status_code = 404
            return resp
        return join_page(request, token[:64])

    @app.post("/join/{token}")
    async def join(request: Request, token: str):
        store, token = invites_on(), token[:64]
        data = await form(request)
        values = {k: str(data.get(k, "")) for k in ("uid", "name", "mail")}
        key = f"join:{ip(request)}"
        if join_throttle.blocked(key):
            flash(request, "error", t("실패가 너무 많습니다. 한 시간 뒤 다시 시도해 주세요."))
            return join_page(request, token, 429, **values)
        try:
            if data.get("consent") != "1":
                raise ValidationError(t("개인정보 수집·이용에 동의해야 가입할 수 있습니다."))
            uid = validators.new_uid(values["uid"].strip().lower())
            password = validators.new_password(str(data.get("password", "")), str(data.get("confirm", "")))
            name = validators.optional_name(values["name"], t("이름"))
            mail = validators.email(values["mail"])
            if directory.get_user(uid) is not None:  # the holder of a link may know which names are taken
                raise ValidationError(t("'{uid}'은(는) 이미 쓰이는 사용자명입니다. 다른 이름을 고르세요.", uid=uid))
        except ValidationError as e:
            join_throttle.fail(key)
            flash(request, "error", str(e))
            return join_page(request, token, 400, **values)
        inv = store.claim(token)
        if inv is None:
            resp = render(request, "join_invalid.html")
            resp.status_code = 404
            return resp
        try:
            acc.make_account(uid, uid, name, mail, s.allowed_shells[0], password, False, ip(request),
                             detail=f"invited by {inv.created_by}")
        except (DirectoryError, KerberosError) as e:
            store.restore(inv)  # the link still works: the person can try again
            join_throttle.fail(key)
            flash(request, "error", t("계정을 만들지 못했습니다: {reason}", reason=e))
            return join_page(request, token, 400, **values)
        return render(request, "join_done.html", uid=uid)

    # ---- admin / helpdesk (the operations are portal/accounts.py's) ---------------------------

    @app.get("/admin/invites")
    async def invite_list(request: Request):
        actor = current_actor(request)
        return render(request, "invites.html", actor, items=acc.invitations(actor))

    @app.post("/admin/invites")
    async def invite_create(request: Request):
        actor = current_actor(request)
        data = await form(request)
        inv, token = acc.invite(actor, str(data.get("note", "")), ip(request))
        return render(request, "invite_link.html", actor, invite=inv, link=f"{s.public_url}{url('/join/' + token)}")

    @app.post("/admin/invites/{iid}/revoke")
    async def invite_revoke(request: Request, iid: str):
        actor = current_actor(request)
        await form(request)
        if acc.revoke_invite(actor, iid, ip(request)):
            flash(request, "ok", "Invitation revoked.")
        return redirect("/admin/invites")

    @app.get("/admin/requests")
    async def request_list(request: Request):
        actor = current_actor(request)
        return render(request, "requests.html", actor, items=acc.pending_requests(actor))

    @app.post("/admin/requests/{rid}/approve")
    async def request_approve(request: Request, rid: str):
        actor = current_actor(request)
        data = await form(request)
        return shown_once(request, actor, acc.approve_request(actor, rid, str(data.get("loginShell", "")), ip(request)),
                          True)

    @app.post("/admin/requests/{rid}/reject")
    async def request_reject(request: Request, rid: str):
        actor = current_actor(request)
        await form(request)
        uid = acc.reject_request(actor, rid, ip(request))
        flash(request, "ok", f"Request for {uid} rejected and deleted.")
        return redirect("/admin/requests")

    @app.get("/admin/users")
    async def users(request: Request, q: str = ""):
        actor = current_actor(request)
        return render(request, "users.html", actor, users=acc.users(actor, q), q=q[:64])

    @app.get("/admin/users/new")
    async def new_user_page(request: Request):
        actor = current_actor(request)
        acc.require(actor, "create_user")
        return render(request, "user_new.html", actor, values={})

    @app.post("/admin/users/new")
    async def create_user(request: Request):
        actor = current_actor(request)
        data = await form(request)
        try:
            made = acc.create(actor, dict(data), ip(request))
        except ValidationError as e:
            flash(request, "error", str(e))
            return render(request, "user_new.html", actor, values=dict(data))
        return shown_once(request, actor, made, True)

    @app.get("/admin/users/{uid}")
    async def user_detail(request: Request, uid: str):
        actor = current_actor(request)
        target = acc.user(actor, uid)
        all_groups = [g for g, _ in acc.groups(actor) if g != target.uid]
        return render(request, "user.html", actor, target=target,
                      addable=[g for g in all_groups if g not in target.groups])

    @app.post("/admin/users/{uid}/reset")
    async def reset_password(request: Request, uid: str):
        actor = current_actor(request)
        await form(request)
        return shown_once(request, actor, acc.reset_password(actor, uid, ip(request)), False)

    @app.post("/admin/users/{uid}/unlock")
    async def unlock(request: Request, uid: str):
        actor = current_actor(request)
        await form(request)
        target = acc.unlock(actor, uid, ip(request))
        flash(request, "ok", f"{target.uid} unlocked.")
        return redirect(f"/admin/users/{target.uid}")

    @app.post("/admin/users/{uid}/enabled")
    async def set_enabled(request: Request, uid: str):
        actor = current_actor(request)
        data = await form(request)
        enabled = data.get("enabled") == "1"
        target = acc.set_enabled(actor, uid, enabled, ip(request))
        flash(request, "ok", f"{target.uid} {'enabled' if enabled else 'disabled'}.")
        return redirect(f"/admin/users/{target.uid}")

    @app.post("/admin/users/{uid}/delete")
    async def delete_user(request: Request, uid: str):
        actor = current_actor(request)
        data = await form(request)
        try:
            target = acc.delete(actor, uid, str(data.get("confirm", "")), ip(request))
        except ValidationError as e:
            flash(request, "error", str(e))
            return redirect(f"/admin/users/{uid}")
        flash(request, "ok", f"{target.uid} deleted. Files it owned (home directory, data) were not touched.")
        return redirect("/admin/users")

    @app.post("/admin/users/{uid}/groups")
    async def set_group(request: Request, uid: str):
        actor = current_actor(request)
        data = await form(request)
        add = data.get("op") == "add"
        group = str(data.get("group", ""))
        target = acc.set_group(actor, uid, group, add, ip(request))
        flash(request, "ok", f"{'Added' if add else 'Removed'} {target.uid} {'to' if add else 'from'} {group}.")
        return redirect(f"/admin/users/{target.uid}")

    from . import account_api

    account_api.install(app, acc, signed_in_uid=signed_in_uid, ip=ip,
                        join_link=lambda token: f"{s.public_url}{url('/join/' + token)}")

    return app
