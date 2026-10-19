"""FastAPI app: login, self-service profile/password, account requests, and the admin/helpdesk console."""
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import audit, tokens, validators
from .config import Settings
from .directory import Directory, DirectoryError, User
from .kerberos import KAdmin, Kerberos, KerberosError, LoginResult
from .rbac import Actor, can, roles_for
from .requests import RequestError, RequestStore
from .security import SecurityHeadersMiddleware, Throttle, csrf_ok, csrf_token
from .validators import ValidationError

HERE = Path(__file__).parent


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
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
               requests: RequestStore | None = None, sso_public_key=None) -> FastAPI:
    s = settings or Settings()
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
    throttle = Throttle()
    request_throttle = Throttle(limit=5, window=3600)  # account requests per client address
    audit.setup(s.audit_log)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=s.session_secret, session_cookie="portal_session",
                       max_age=s.session_max_age, same_site="strict", https_only=s.cookie_secure,
                       path=s.root_path or "/")
    app.add_middleware(RootPath, prefix=s.root_path)  # added last, so it runs first
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

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
                   settings=s, url=url, sso=sso, requests_enabled=requests is not None,
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
        uid = signed_in_uid(request)
        if not uid:
            if not sso:
                request.session.clear()
            raise LoginRequired()
        user = directory.get_user(uid)
        if user is None or user.disabled:
            request.session.clear()
            raise LoginRequired()
        return Actor(user=user, roles=roles_for(user, s))

    def require(actor: Actor, action: str, target: User | None = None) -> None:
        if not can(actor, action, s, target):
            raise Forbidden("You are not allowed to do that.")

    def target_user(uid: str) -> User:
        try:
            user = directory.get_user(validators.uid(uid))
        except ValidationError:
            user = None
        if user is None:
            raise Forbidden("No such user.")
        return user

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
        audit.record(request.session.get("uid"), "backend_error", None, False, ip(request), str(exc))
        resp = render(request, "error.html", message=f"Directory operation failed: {exc}")
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
            return RedirectResponse("/auth/expired", status_code=303)
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
            changes = {
                "displayName": validators.optional_name(str(data.get("displayName", "")), "Display name"),
                "mail": validators.email(str(data.get("mail", ""))),
                "loginShell": validators.shell(str(data.get("loginShell", "")), s.allowed_shells),
            }
        except ValidationError as e:
            flash(request, "error", str(e))
            return redirect("/")
        directory.update_self(actor.uid, changes)
        audit.record(actor.uid, "update_profile", actor.uid, True, ip(request), ",".join(changes))
        flash(request, "ok", "Profile updated.")
        return redirect("/")

    @app.post("/password")
    async def change_password(request: Request):
        actor = current_actor(request)
        data = await form(request)
        key = f"pw:{actor.uid}"
        if throttle.blocked(key):
            flash(request, "error", "Too many failed attempts. Try again in 15 minutes.")
            return redirect("/")
        try:
            new = validators.new_password(str(data.get("new", "")), str(data.get("confirm", "")))
            kerberos.change_own_password(s.principal(actor.uid), str(data.get("old", "")), new)
        except (ValidationError, KerberosError) as e:
            throttle.fail(key)
            audit.record(actor.uid, "change_password", actor.uid, False, ip(request), str(e))
            flash(request, "error", str(e))
            return redirect("/")
        audit.record(actor.uid, "change_password", actor.uid, True, ip(request))
        flash(request, "ok", "Password changed.")
        return redirect("/")

    def provision(request: Request, actor: Actor, uid: str, name: str, mail: str, shell: str,
                  detail: str = ""):
        """LDAP entry, then the Kerberos principal with a one-time password; LDAP is rolled back if
        Kerberos fails."""
        user = directory.create_user(uid, name, mail, shell)
        password = validators.temp_password()
        try:
            kadmin.create_principal(s.principal(uid), user.dn, password, s.principal_alias(uid))
        except KerberosError as e:
            directory.rollback_user(uid)
            audit.record(actor.uid, "create_user", uid, False, ip(request), str(e))
            raise
        audit.record(actor.uid, "create_user", uid, True, ip(request),
                     f"uidNumber={user.uid_number}" + (f" {detail}" if detail else ""))
        return render(request, "temp_password.html", actor, target=user, password=password, created=True)

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
            flash(request, "error", "신청이 너무 많습니다. 한 시간 뒤 다시 시도해 주세요.")
            return render(request, "request.html", values=dict(data))
        request_throttle.fail(key)  # every submission counts, accepted or not
        try:
            if data.get("consent") != "1":
                raise ValidationError("개인정보 수집·이용에 동의해야 신청할 수 있습니다.")
            uid = validators.new_uid(str(data.get("uid", "")).strip().lower())
            name = validators.optional_name(str(data.get("name", "")), "이름")
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
            flash(request, "error", "지금은 신청을 받을 수 없습니다. 관리자에게 직접 문의해 주세요.")
            return render(request, "request.html", values=dict(data))
        audit.record(None, "account_request", uid, added, ip(request), "" if added else "duplicate")
        return render(request, "request_done.html")

    # ---- admin / helpdesk --------------------------------------------------------------------

    def pending_request(rid: str):
        r = requests_on().get(rid[:32])
        if r is None:
            raise Forbidden("That request no longer exists (approved, rejected, or expired).")
        return r

    @app.get("/admin/requests")
    async def request_list(request: Request):
        actor = current_actor(request)
        require(actor, "review_requests")
        return render(request, "requests.html", actor, items=requests_on().list())

    @app.post("/admin/requests/{rid}/approve")
    async def request_approve(request: Request, rid: str):
        actor = current_actor(request)
        require(actor, "review_requests")
        require(actor, "create_user")
        data = await form(request)
        r = pending_request(rid)
        try:
            uid = validators.new_uid(r.uid)
            shell = validators.shell(str(data.get("loginShell", "")), s.allowed_shells)
        except ValidationError as e:
            raise Forbidden(str(e))
        resp = provision(request, actor, uid, r.name, r.mail, shell, detail="from request")
        requests_on().delete(r.id)  # the request's copy of the personal data goes now
        return resp

    @app.post("/admin/requests/{rid}/reject")
    async def request_reject(request: Request, rid: str):
        actor = current_actor(request)
        require(actor, "review_requests")
        await form(request)
        r = pending_request(rid)
        requests_on().delete(r.id)
        audit.record(actor.uid, "reject_request", r.uid, True, ip(request))
        flash(request, "ok", f"Request for {r.uid} rejected and deleted.")
        return redirect("/admin/requests")

    @app.get("/admin/users")
    async def users(request: Request, q: str = ""):
        actor = current_actor(request)
        require(actor, "view_users")
        return render(request, "users.html", actor, users=directory.search_users(q[:64]), q=q[:64])

    @app.get("/admin/users/new")
    async def new_user_page(request: Request):
        actor = current_actor(request)
        require(actor, "create_user")
        return render(request, "user_new.html", actor, values={})

    @app.post("/admin/users/new")
    async def create_user(request: Request):
        actor = current_actor(request)
        require(actor, "create_user")
        data = await form(request)
        try:
            uid = validators.new_uid(str(data.get("uid", "")))
            name = validators.optional_name(str(data.get("name", "")), "Name")
            mail = validators.email(str(data.get("mail", "")))
            shell = validators.shell(str(data.get("loginShell", "")), s.allowed_shells)
        except ValidationError as e:
            flash(request, "error", str(e))
            return render(request, "user_new.html", actor, values=dict(data))
        return provision(request, actor, uid, name, mail, shell)

    @app.get("/admin/users/{uid}")
    async def user_detail(request: Request, uid: str):
        actor = current_actor(request)
        require(actor, "view_users")
        target = target_user(uid)
        all_groups = [g for g, _ in directory.list_groups() if g != target.uid]
        return render(request, "user.html", actor, target=target,
                      addable=[g for g in all_groups if g not in target.groups])

    @app.post("/admin/users/{uid}/reset")
    async def reset_password(request: Request, uid: str):
        actor = current_actor(request)
        await form(request)
        target = target_user(uid)
        require(actor, "reset_password", target)
        password = validators.temp_password()
        kadmin.reset_password(s.principal(target.uid), password)
        audit.record(actor.uid, "reset_password", target.uid, True, ip(request))
        return render(request, "temp_password.html", actor, target=target, password=password, created=False)

    @app.post("/admin/users/{uid}/unlock")
    async def unlock(request: Request, uid: str):
        actor = current_actor(request)
        await form(request)
        target = target_user(uid)
        require(actor, "unlock", target)
        kadmin.unlock(s.principal(target.uid))
        audit.record(actor.uid, "unlock", target.uid, True, ip(request))
        flash(request, "ok", f"{target.uid} unlocked.")
        return redirect(f"/admin/users/{target.uid}")

    @app.post("/admin/users/{uid}/enabled")
    async def set_enabled(request: Request, uid: str):
        actor = current_actor(request)
        data = await form(request)
        target = target_user(uid)
        require(actor, "set_enabled", target)
        enabled = data.get("enabled") == "1"
        kadmin.set_enabled(s.principal(target.uid), enabled)
        audit.record(actor.uid, "enable" if enabled else "disable", target.uid, True, ip(request))
        flash(request, "ok", f"{target.uid} {'enabled' if enabled else 'disabled'}.")
        return redirect(f"/admin/users/{target.uid}")

    @app.post("/admin/users/{uid}/groups")
    async def set_group(request: Request, uid: str):
        actor = current_actor(request)
        data = await form(request)
        target = target_user(uid)
        require(actor, "manage_groups", target)
        try:
            group = validators.group(str(data.get("group", "")))
        except ValidationError as e:
            raise Forbidden(str(e))
        if group == target.uid or group not in {g for g, _ in directory.list_groups()}:
            raise Forbidden("That group cannot be changed here.")
        add = data.get("op") == "add"
        directory.set_membership(group, target.uid, add)
        audit.record(actor.uid, "group_add" if add else "group_remove", target.uid, True, ip(request), group)
        flash(request, "ok", f"{'Added' if add else 'Removed'} {target.uid} {'to' if add else 'from'} {group}.")
        return redirect(f"/admin/users/{target.uid}")

    return app
