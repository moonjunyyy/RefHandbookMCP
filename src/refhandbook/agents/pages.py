"""The approvals: /approvals, the user's channel (docs/kernel.md "Reviewing the rules", docs/agents.md §9).

Server-rendered, with no script at all: this is where a model's proposal becomes a rule that blocks,
where a capability that widens what the model may do is granted, where a sandbox policy is set, and
where a run the model asked for gets its grant. Everything else of the agents (runs, presets, keys,
files) is the site's pages app over /agents/api/v1 (agents/api.py).

Behind the site sign-in: nginx asks the SSO, which mints an X-Auth-Token for the audience
`refhandbook`, and every request here verifies it. What the page writes is written as `user`. Forms
carry a token bound to the signed-in uid (HMAC with a key kept in the data directory) and must come
from this origin.

    GET  /approvals                   grants waiting, rule proposals, policies, records, jobs
    POST /approvals/cap/approve|reject   kind, name, version → Registry.approve|reject(actor=user)
    POST /approvals/cap/manage        kind, name, action: rename|deprecate|remove|restore|review|edit
                                      → Workspace.rename, Registry.deprecate|remove|restore|review_now|update
    POST /approvals/approve           rule, seen → Graph.approve(actor=user, seen=…)
    POST /approvals/reject            rule → retire_rule(actor=user)
    POST /approvals/policy            name, … → Workspace.set_policy(actor=user)
    GET  /approvals/runs/<run>        a run the model asked for: its grant form (else: the run's page)
    POST /approvals/runs/<run>/approve|reject
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import os
import logging
import secrets
import shlex
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from portal.i18n import N_, t

from ..kernel import proposals
from ..page import page
from ..store import Handbook, HandbookError
from . import keys as K
from . import run_pages
from .workspace import Workspace

log = logging.getLogger("refhandbook.agents.pages")

def _key(data_dir: Path) -> bytes:
    p = Path(data_dir) / "agents-pages.key"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".new")
        tmp.write_bytes(secrets.token_bytes(32))
        tmp.chmod(0o600)
        tmp.replace(p)
    return p.read_bytes()


def install(m: Any, *, stores: Callable[[str], Handbook], uid_of: Callable[[str], str | None], data_dir: Path,
            public_url: str, lock: Any, login_url: str,
            allowed: Callable[[str], bool] = lambda uid: True) -> None:
    """Register the /agents routes on the MCP server `m` (remote.build)."""
    key = _key(data_dir)

    def _html(body: str, status: int = 200) -> HTMLResponse:
        return page(t("에이전트 · 샌드박스"), body, login_url=login_url, status=status)

    origin = "{0.scheme}://{0.netloc}".format(urlparse(public_url))

    def csrf(uid: str) -> str:
        return hmac.new(key, f"agents|{uid}".encode(), hashlib.sha256).hexdigest()

    def who(request: Request) -> str | None:
        uid = uid_of(request.headers.get("x-auth-token", ""))
        return uid if uid is not None and allowed(uid) else None

    def same_origin(request: Request) -> bool:
        o = request.headers.get("origin") or request.headers.get("referer", "")
        return bool(o) and (o == origin or o.startswith(origin + "/"))  # a browser's form POST always says

    async def locked(fn: Callable[[], Any]) -> Any:
        def run() -> Any:
            with lock:
                return fn()
        return await anyio.to_thread.run_sync(run)

    @m.custom_route("/approvals", methods=["GET"])
    async def overview(request: Request) -> Response:
        uid = who(request)
        if uid is None:
            return RedirectResponse(f"{login_url}?next=/approvals", status_code=303)
        body = await locked(lambda: _overview(Workspace(stores(uid)), uid, csrf(uid), request.query_params))
        return _html(body)

    async def checked(request: Request) -> tuple[str, dict[str, str]] | Response:
        """The signed-in user and the form, or the refusal: a POST needs the sign-in, this origin and
        the form's token."""
        uid = who(request)
        if uid is None:
            return _html(f"<p class='flash error'>{t('로그인이 필요합니다.')}</p>", 401)
        form: dict[str, str] = {}
        for k, v in (await request.form()).items():
            text = str(v)
            if len(text) > (FIELD_BIG if k in ("body", "spec") else FIELD_MAX):
                return _html(f"<p class='flash error'>{t('입력이 너무 깁니다: {field}', field=_e(k))}</p>", 413)
            form[k] = text
        if not same_origin(request) or not hmac.compare_digest(form.get("csrf", ""), csrf(uid)):
            return _html(f"<p class='flash error'>{t('요청을 확인할 수 없습니다. 페이지를 새로 열어 다시 시도하세요.')}</p>", 403)
        return uid, form

    def back(where: str, done: str = "", err: str = "", anchor: str = "") -> Response:
        q = f"ok={quote(done)}" if done else f"err={quote(err[:300])}"
        return RedirectResponse(f"{where}{'&' if '?' in where else '?'}{q}{'#' + anchor if anchor else ''}",
                                status_code=303)

    async def post(request: Request, action: Callable[[Workspace, dict[str, str]], str], anchor: str = "") -> Response:
        got = await checked(request)
        if isinstance(got, Response):
            return got
        uid, form = got
        try:
            done = await locked(lambda: action(Workspace(stores(uid)), form))
            return back("/approvals", done, anchor=anchor)
        except HandbookError as e:  # the page again, with what was typed still in its form
            draft = form if request.url.path == "/approvals/policy" else None  # the forms that keep a draft
            body = await locked(lambda: _overview(Workspace(stores(uid)), uid, csrf(uid), {"err": str(e)}, draft=draft))
            return _html(body, 400)

    async def get_page(request: Request, here: str, render: Callable[[str, str], str]) -> Response:
        uid = who(request)
        if uid is None:
            return RedirectResponse(f"{login_url}?next={quote(here)}", status_code=303)
        return _html(await locked(lambda: render(uid, f"<input type=hidden name=csrf value='{csrf(uid)}'>")))

    # ── a run the model asked for: its grant, approved here (the user's channel) ──

    from . import crew
    from .team import Team

    def run_of(request: Request) -> str:
        run = request.path_params["run"]
        if not run.startswith("run:") or len(run) > 40:
            raise HandbookError(t("그런 실행이 없습니다"))
        return run

    @m.custom_route("/approvals/runs/{run}", methods=["GET"])
    async def run_page(request: Request) -> Response:
        uid = who(request)
        if uid is None:
            return RedirectResponse(f"{login_url}?next={quote(request.url.path)}", status_code=303)
        ks = K.KeyStore.for_web(data_dir)

        def render() -> str | None:
            ws = Workspace(stores(uid))
            team = Team(ws.g)
            run = run_of(request)
            n = team.g.get_node(run)
            if n is None or n["type"] != "run":
                raise HandbookError(t("그런 실행이 없습니다"))
            if n["attrs"].get("phase") != "requested" or n["state"] != "open":
                return None  # nothing to approve: the run's own page
            return run_pages.run_page(uid, team, run, ks.list(uid), ws.policies(),
                                      f"<input type=hidden name=csrf value='{csrf(uid)}'>", request.query_params)
        try:
            body = await locked(render)
        except HandbookError as e:
            return _html(f"<p class='flash error'>{html.escape(str(e))}</p>", 404)
        if body is None:
            return RedirectResponse(f"/agents/runs/{quote(request.path_params['run'], safe=':')}", status_code=303)
        return _html(body)

    @m.custom_route("/approvals/runs/{run}/approve", methods=["POST"])
    async def run_approve(request: Request) -> Response:
        got = await checked(request)
        if isinstance(got, Response):
            return got
        uid, f = got
        keys = await anyio.to_thread.run_sync(lambda: K.KeyStore.for_web(data_dir).list(uid))

        def act() -> str:
            run = run_of(request)
            ws = Workspace(stores(uid))
            Team(ws.g).approve(run, run_pages.parse_grant(f, keys), actor="user")
            crew.mark(ws, run)
            return run
        try:
            run = await locked(act)
        except HandbookError as e:  # the form again, as it was filled in
            def again() -> str:
                ws = Workspace(stores(uid))
                return run_pages.run_page(uid, Team(ws.g), run_of(request), keys, ws.policies(),
                                          f"<input type=hidden name=csrf value='{csrf(uid)}'>", {"err": str(e)},
                                          draft=run_pages.draft_grant(f))
            return _html(await locked(again), 400)
        return back(f"/agents/runs/{run}", t("승인했습니다. 곧 시작합니다."))

    @m.custom_route("/approvals/runs/{run}/reject", methods=["POST"])
    async def run_reject(request: Request) -> Response:
        got = await checked(request)
        if isinstance(got, Response):
            return got
        uid, _ = got

        def act() -> None:
            Team(Workspace(stores(uid)).g).request_cancel(run_of(request), "rejected by the user", by="user")
        try:
            await locked(act)
        except HandbookError as e:
            return back(f"/approvals/runs/{request.path_params['run']}", err=str(e))
        return back("/approvals", t("요청을 거절했습니다."))

    # Until the site's pages app is published, /agents/ is the handbook's: it points to the approvals.
    @m.custom_route("/agents", methods=["GET"])
    @m.custom_route("/agents/", methods=["GET"])
    async def agents_home(request: Request) -> Response:
        return RedirectResponse("/approvals", status_code=303)

    @m.custom_route("/approvals/approve", methods=["POST"])
    async def approve(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            retired = proposals.approve(ws.g, f.get("rule", ""), f.get("seen", ""), actor="user")
            if retired:
                return t("규칙 {rule} 승인, {retired} 은퇴", rule=f.get("rule"), retired=" ".join(retired))
            return t("규칙 {rule} 승인", rule=f.get("rule"))
        return await post(request, act)

    @m.custom_route("/approvals/reject", methods=["POST"])
    async def reject(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            proposals.reject(ws.g, f.get("rule", ""), actor="user")
            return t("규칙 {rule} 거절", rule=f.get("rule"))
        return await post(request, act)

    @m.custom_route("/approvals/cap/approve", methods=["POST"])
    async def cap_approve(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            return ws.caps.approve(f.get("kind", ""), f.get("name", ""), _int(f.get("version")), actor="user")
        return await post(request, act)

    @m.custom_route("/approvals/cap/reject", methods=["POST"])
    async def cap_reject(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            return ws.caps.reject(f.get("kind", ""), f.get("name", ""), _int(f.get("version")), actor="user")
        return await post(request, act)

    @m.custom_route("/approvals/cap/manage", methods=["POST"])
    async def cap_manage(request: Request) -> Response:
        return await post(request, _manage_action, anchor="records")

    @m.custom_route("/approvals/policy", methods=["POST"])
    async def policy(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            changes: dict[str, Any] = {"commands": f.get("commands", "").split(), "network": f.get("network") == "on",
                                       "exec_work": f.get("exec_work") == "on",
                                       "description": f.get("description", ""),
                                       "layers": f.get("layers", "").split(), "mounts": _mounts(f.get("mounts", ""))}
            ports = f.get("ports", "").strip()
            if ports:
                try:
                    changes["ports"] = "any" if ports == "any" else [int(x) for x in ports.split()]
                except ValueError as e:
                    raise HandbookError(t("포트: 숫자 또는 any")) from e
            for k, label in LIMITS:
                if f.get(k, "").strip():
                    changes[k] = _number(f[k], t(label), whole=k != "cpus")
            name = f.get("name", "")
            ws.set_policy(name, actor="user", **changes)
            return t("정책 {name} 저장", name=name)
        return await post(request, act)


def _number(text: str, label: str, *, whole: bool) -> int | float:
    """A number as a person writes it: 120, 120.0 or 1,024 (a whole number where one is needed)."""
    try:
        v = float(text.strip().replace(",", ""))
    except ValueError as e:
        raise HandbookError(t("{label}: 숫자로 적어 주세요 ({text})", label=label, text=repr(text.strip()))) from e
    if whole:
        if not v.is_integer():
            raise HandbookError(t("{label}: 정수로 적어 주세요 ({text})", label=label, text=repr(text.strip())))
        return int(v)
    return v


def _shown(v: Any) -> str:
    """A number as the form shows it: 120, not 120.0."""
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _int(x: str | None) -> int:
    try:
        return int(x or "")
    except ValueError as e:
        raise HandbookError(t("버전이 숫자가 아닙니다")) from e


def _mounts(text: str) -> list[dict[str, Any]]:
    """One mount per line: SOURCE TARGET [rw], split as a shell would: a path with spaces is quoted
    ("…" or '…') or has its spaces escaped (\\ ). _mount_line writes a mount back the same way."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parts = shlex.split(line)
        except ValueError as e:
            raise HandbookError(t("마운트 줄 {line}: 따옴표가 닫히지 않았습니다", line=repr(line))) from e
        if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "rw"):
            raise HandbookError(t("마운트 줄 {line}: '원본 대상 [rw]', 공백이 든 경로는 따옴표로 감쌉니다",
                                  line=repr(line)))
        out.append({"source": parts[0], "target": parts[1], "rw": len(parts) == 3})
    return out


def _quoted(path: str) -> str:
    """A path as a mount line writes it: as it is, or quoted when a shell would split or unquote it."""
    return path if path and not re.search(r"""[\s'"\\#]""", path) else shlex.quote(path)


def _mount_line(m: dict[str, Any]) -> str:
    return f"{_quoted(m['source'])} {_quoted(m['target'])}" + (" rw" if m.get("rw") else "")


def _e(x: Any) -> str:
    return html.escape(str(x))


# ── the page ─────────────────────────────────────────────────────────────
# Laid out with the site's stylesheet (portal/static/style.css): a card per section, folded panels for
# the policies, key/value lists instead of JSON dumps.

LIMITS = (("timeout", N_("시간(초)")), ("memory_mb", N_("메모리 MB")), ("cpus", "CPU"), ("disk_mb", N_("디스크 MB")),
          ("tmp_mb", "tmp MB"), ("concurrent", N_("동시 실행")))
STATE_TAGS = {"active": "ok", "proposed": "warn", "deprecated": "bad", "retired": ""}
STATE_LABELS = {"active": N_("사용 중"), "proposed": N_("승인 대기"), "deprecated": N_("폐기 예정"), "retired": N_("은퇴")}
KIND_LABELS = {"policy": N_("정책"), "script": N_("스크립트"), "layer": N_("레이어"), "egress": N_("외부 접속"),
               "alias": N_("별칭"), "card": N_("카드"), "rule": N_("규칙")}
KIND_ORDER = ("policy", "script", "layer", "egress", "alias", "card", "rule")
JOB_TAGS = {"done": "ok", "failed": "bad", "cancelled": "warn", "running": "warn"}
JOB_LABELS = {"queued": N_("대기"), "running": N_("실행 중"), "done": N_("완료"), "failed": N_("실패"),
              "cancelled": N_("취소됨")}
NAME_PATTERN = r"[a-z0-9][a-z0-9._\-]*"  # an HTML pattern: valid under the v flag browsers now compile it with
FIELD_MAX, FIELD_BIG = 20_000, 400_000  # a form field; a record's body or spec


def _kind(kind: str) -> str:
    return t(KIND_LABELS[kind]) if kind in KIND_LABELS else kind


def _state(state: str) -> str:
    return t(STATE_LABELS[state]) if state in STATE_LABELS else state


def _day(ts: Any) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else ""


def _value(v: Any) -> str:
    """A spec value as the page shows it: lists joined, booleans in words."""
    if isinstance(v, bool):
        return t("예") if v else t("아니오")
    if isinstance(v, list):  # as the policy form writes it: 80 443, not [80, 443]
        if all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in v):
            return " ".join(x if isinstance(x, str) else _shown(x) for x in v)
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float):
        return _shown(v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _kv(spec: dict[str, Any]) -> str:
    rows = "".join(f"<dt>{_e(k)}</dt><dd>{_e(_value(v)) or '<span class=muted>-</span>'}</dd>"
                   for k, v in sorted(spec.items()))
    return f"<dl class='kv'>{rows}</dl>"


def _section(anchor: str, title: str, intro: str, body: str) -> str:
    return (f"<section class='card section' id='{anchor}'><h2>{title}</h2>"
            f"<p class='muted small'>{intro}</p>{body}</section>")


def _empty(text: str) -> str:
    return f"<p class='empty muted'>{text}</p>"


def _grant(caps: Any, r: dict[str, Any], hidden: str) -> str:
    a = r["attrs"]
    ver = caps.version(r, a["pending"])
    cur = caps.version(r) if a.get("version") else None
    why = caps.kind(a["kind"]).widens(caps, cur["spec"] if cur else None, ver["spec"])
    ident = (f"{hidden}<input type=hidden name=kind value='{_e(a['kind'])}'><input type=hidden name=name value='{_e(a['name'])}'>"
             f"<input type=hidden name=version value='{a['pending']}'>")
    status = t("현재 v{version}", version=a["version"]) if a.get("version") else t("아직 적용된 버전 없음")
    body = (f"<details><summary>{t('본문')}</summary><pre>{_e(ver['body'][:20000])}</pre></details>" if ver["body"] else "")
    return (f"<div class='item'><div class='item-head'><b>{_e(a['kind'])} {_e(a['name'])}</b>"
            f"<span class='tag'>v{a['pending']}</span><span class='muted small'>{t('작성 {author}', author=_e(ver['author']))} · {status}</span></div>"
            f"<p>{t('넓어지는 것:')} {''.join(f'<span class=\"tag warn\">{_e(w)}</span>' for w in why) or '-'}</p>"
            + (f"<p class='muted'>{_e(ver['note'])}</p>" if ver["note"] else "")
            + _kv(ver["spec"]) + body
            + f"<div class='actions'><form class=inline method=post action='/approvals/cap/approve'>{ident}<button>{t('승인')}</button></form>"
            f"<form class=inline method=post action='/approvals/cap/reject'>{ident}<button class=secondary>{t('거절')}</button></form></div></div>")


def _rule(r: dict[str, Any], hidden: str) -> str:
    rid = f"<input type=hidden name=rule value='{_e(r['id'])}'>"
    replaces = "".join(f"<details><summary>{t('승인하면 은퇴하는 규칙 {id}', id=_e(o['id']))}</summary>"
                       f"<p class='muted small'>{_e(o.get('message', ''))}</p><pre>{_e(o.get('body', ''))}</pre></details>"
                       for o in r["replaces"])
    label = (t("승인 ({ids} 대체)", ids=_e(" ".join(o["id"] for o in r["replaces"]))) if r["replaces"]
             else t("승인"))
    return (f"<div class='item'><div class='item-head'><b>{_e(r['id'])}</b><span class='tag'>{_e(r['phase'])}</span>"
            f"<span class='tag warn'>{t('승인하면 {severity}', severity=_e(r['severity']))}</span>"
            f"<span class='muted small'>{t('승인 해시 {hash}', hash=r['approval'])}</span></div>"
            f"<p>{_e(r['message'])}</p><p class='muted small'>{_e(r['why'])}</p><pre>{_e(r['body'])}</pre>{replaces}"
            f"<div class='actions'><form class=inline method=post action='/approvals/approve'>{hidden}{rid}"
            f"<input type=hidden name=seen value='{r['approval']}'><button>{label}</button></form>"
            f"<form class=inline method=post action='/approvals/reject'>{hidden}{rid}<button class=secondary>{t('거절')}</button></form>"
            "</div></div>")


def _offered(ws: Workspace) -> str:
    """Where this user may pick directories to mount from, as the policy form says it."""
    from .capkinds import mount_roots

    try:
        roots = mount_roots(ws)
    except HandbookError as e:
        log.warning("mount settings: %s", e)
        return t("마운트 설정에 문제가 있습니다(관리자에게 알려 주세요)")
    if not roots:
        return t("이 서버는 마운트를 허용하지 않습니다")
    return t("고를 수 있는 곳: {roots}",
             roots=", ".join(t("{path} (읽기 전용)", path=r.host) if r.ro else r.host for r in roots))


def _mount_status(ws: Workspace, a: dict[str, Any]) -> str:
    """Each mount of a policy and what became of it (root's staging): ready, waiting, or why not."""
    from . import mounts
    from .capkinds import mount_check

    stage = mounts.stage_root()
    if not a.get("mounts") or stage is None:
        return ""
    said = mounts.status_of(stage, ws.owner)
    rows = []
    for m in a["mounts"]:
        try:
            host = mount_check(ws, m["source"])
        except HandbookError as e:
            rows.append(f"<li><code>{_e(m['source'])}</code> <span class='tag bad'>{t('안 됨')}</span> {_e(e)}</li>")
            continue
        ready = os.path.ismount(mounts.staged_path(stage, ws.owner, host))
        why = said.get(host)
        tag = (f"<span class='tag ok'>{t('준비됨')}</span>" if ready else
               f"<span class='tag bad'>{t('안 됨')}</span> {_e(why)}" if why and why != "ok" else
               f"<span class='tag warn'>{t('준비 중')}</span> {t('1분 안에 준비됩니다')}")
        rows.append(f"<li><code>{_e(m['source'])}</code> → <code>{_e(m['target'])}</code> {tag}</li>")
    return "<ul class='small'>" + "".join(rows) + "</ul>"


def _policy(name: str, a: dict[str, Any], p: dict[str, Any] | None, hidden: str, offered: str = "",
            draft: dict[str, str] | None = None, status: str = "", manage: str = "", by: str = "") -> str:
    """One policy as a folded panel: a summary line, and its form when opened (a new one has a name field),
    with what its owner can do with the record under it. `draft`: what was typed into this form and
    refused: shown again as typed, the panel open. `by`: the version in force and who wrote it."""
    ports = "any" if a.get("ports") in (None, "any") else " ".join(map(str, a.get("ports") or []))
    mounts = "\n".join(_mount_line(m) for m in a.get("mounts") or [])
    d = draft or {}

    def val(key: str, current: str) -> str:
        return _e(d[key]) if key in d else _e(current)

    def checked(key: str, current: bool) -> str:
        return "checked" if ((d.get(key) == "on") if draft is not None else current) else ""
    if p:
        head = (f"<b>{_e(name)}</b><span class='muted small'>{_e(by or p['author'])}</span>"
                f"<span class='tag {'warn' if a['network'] else ''}'>{t('네트워크 켜짐') if a['network'] else t('네트워크 꺼짐')}"
                f"{' · ' + _e(ports) if a['network'] else ''}</span>"
                f"<span class='tag'>{t('명령 전부') if '*' in a['commands'] else t('명령 {n}개', n=len(a['commands']))}</span>"
                + (f"<span class='tag warn'>{t('빌드 실행')}</span>" if a.get("exec_work") else "")
                + (f"<span class='tag'>{t('마운트 {n}개', n=len(a['mounts']))}</span>" if a.get("mounts") else "") +
                f"<span class='tag'>{_e(_shown(a.get('timeout', '')))}s · {_e(_shown(a.get('memory_mb', '')))} MB</span>"
                + (f"<span class='muted small'>{_e(p['content'])}</span>" if p["content"] else ""))
        ident = f"<input type=hidden name=name value='{_e(name)}'>"
    else:
        head = f"<b>{t('새 정책')}</b><span class='muted small'>{t('기본 정책에서 시작합니다')}</span>"
        ident = (f"<label>{t('이름')} <input name=name required pattern='{NAME_PATTERN}' maxlength=64 "
                 f"value='{val('name', '')}'></label>")
    limits = "".join(f"<label>{t(lab)}<input name={k} value='{val(k, _shown(a.get(k, '')))}'></label>" for k, lab in LIMITS)
    example = '"/data/me/Obsidian/Research Vault" /Vault rw'
    anchor = f" id='policy-{_e(name)}'" if p else ""  # the records' link to this form
    return (f"<details class='panel'{' open' if draft is not None else ''}>"
            f"<summary{anchor}>{head}</summary>"
            f"<form method=post action='/approvals/policy'>{hidden}"
            f"<div class='cols'>{ident}<label>{t('설명')} <input name=description value='{val('description', p['content'] if p else '')}'></label></div>"
            f"<label>{t('명령')} <span class='muted small'>{t('공백으로 구분, * 는 모든 명령')}</span>"
            f"<textarea name=commands rows=3>{val('commands', ' '.join(a['commands']))}</textarea></label>"
            f"<div class='cols'><label>{t('레이어')} <span class='muted small'>{t('공백으로 구분')}</span>"
            f"<input name=layers value='{val('layers', ' '.join(a.get('layers') or []))}'></label>"
            f"<label>{t('마운트')} <span class='muted small'>"
            f"{t('한 줄에 하나: 원본 경로, 샌드박스 안의 경로, 쓰기 허용이면 rw. 공백이 든 경로는 따옴표로 감쌉니다. 예:')} "
            f"<code>{_e(example)}</code> · {_e(offered)}</span>"
            f"<textarea name=mounts rows=3 spellcheck=false>{val('mounts', mounts)}</textarea>{status}</label></div>"
            f"<div class='cols'><label class='check'><input type=checkbox name=network {checked('network', a['network'])}>"
            f" {t('네트워크 허용')}</label><label>{t('포트')} <input name=ports value='{val('ports', ports)}'></label></div>"
            f"<label class='check'><input type=checkbox name=exec_work {checked('exec_work', bool(a.get('exec_work')))}>"
            f" {t('빌드 결과 실행 허용')} <span class='muted small'>"
            f"{t('/work·/tmp에서 만든 실행 파일(컴파일 결과, 빌드 도구)을 실행할 수 있게 합니다. 끄면 인터프리터로만 실행됩니다.')}"
            "</span></label>"
            f"<div class='fields'>{limits}</div>"
            f"<div class='actions'><button>{t('저장')}</button></div></form>"
            + (f"<div class='panel-foot'><h4>{t('관리')}</h4>{manage}</div>" if manage else "")
            + "</details>")


def _records(ws: Workspace, hidden: str) -> tuple[int, str]:
    """The records by kind, one folded row each (_record); the retired ones folded away at the end, where
    they can be restored. The count is of the records not retired."""
    caps = ws.caps
    live, gone = caps.list(), caps.list(states=("retired",))

    def groups(recs: list[dict[str, Any]]) -> str:
        by: dict[str, list[dict[str, Any]]] = {}
        for r in recs:
            by.setdefault(r["attrs"]["kind"], []).append(r)
        order = [k for k in KIND_ORDER if k in by] + sorted(k for k in by if k not in KIND_ORDER)
        return "".join(f"<div class='rec-group'><h3>{_e(_kind(k))} <span class='muted small'>{len(by[k])}</span></h3>"
                       + "".join(_record(ws, r, hidden) for r in by[k]) + "</div>" for k in order)

    out = groups(live) or _empty(t("기록이 없습니다."))
    if gone:
        out += (f"<details class='retired'><summary>{t('은퇴한 기록 ({n})', n=len(gone))}</summary>"
                f"<p class='muted small'>{t('이력이 남아 있어 복원할 수 있습니다.')}</p>{groups(gone)}</details>")
    return len(live), out


def _record(ws: Workspace, r: dict[str, Any], hidden: str) -> str:
    """One record as a folded row: its name, version and state, who wrote it and when, why it is not in
    use (when it is not), what it is (two lines at most). Opened: its spec, body and history, and what
    its owner can do with it (_manage)."""
    caps = ws.caps
    a = r["attrs"]
    kind, name, state = a["kind"], a["name"], r["state"]
    v = a.get("version") or a.get("pending") or a.get("last_in_force")
    try:
        ver = caps.version(r, v) if v else None
    except HandbookError:
        ver = None
    meta = [t("만든 이 {author}", author=r["author"])]
    if ver:
        meta.append(t("마지막 수정 {author}, {day}", author=ver["author"], day=_day(ver["created"])))
    if state == "active" and a.get("review_after"):
        meta.append(t("검토 {day}", day=_day(a["review_after"])))
    why = [str(a["reason"])] if state != "active" and a.get("reason") else []
    if a.get("replaced_by"):
        why.append(t("대체: {name}", name=a["replaced_by"]))
    if state in ("deprecated", "proposed") and a.get("retire_at"):
        why.append(t("{day} 은퇴 예정", day=_day(a["retire_at"])))
    if state == "retired" and a.get("retired_at"):
        why.append(t("{day} 은퇴", day=_day(a["retired_at"])))
    head = (f"<span class='rec-name'>{_e(name)}</span>" + (f"<span class='tag'>v{_e(v)}</span>" if v else "")
            + f"<span class='tag {STATE_TAGS.get(state, '')}'>{_e(_state(state))}</span>"
            + (f"<span class='tag warn'>{t('v{version} 승인 대기', version=a['pending'])}</span>"
               if a.get("pending") and a.get("version") else "")
            + f"<span class='muted small'>{_e(' · '.join(meta))}</span>"
            + (f"<span class='rec-why'>{_e(' · '.join(why))}</span>" if why else "")
            + (f"<span class='rec-desc'>{_e(r['content'])}</span>" if r.get("content") else ""))
    body = ""
    if ver:
        body += _kv(ver["spec"])
        if ver.get("body"):
            body += f"<details><summary>{t('본문')}</summary><pre>{_e(ver['body'][:20000])}</pre></details>"
    hist = "".join(f"<li><b>v{h['version']}</b> <span class='muted'>{_e(h['author'])} · {_e(_day(h['created']))}</span>"
                   + (f" — {_e(h['note'])}" if h.get("note") else "") + "</li>"
                   for h in caps.history(kind, name)[-6:][::-1])
    if hist:
        body += f"<h4>{t('이력')} <span class='muted small'>{t('최근 6개')}</span></h4><ol class='history'>{hist}</ol>"
    return (f"<details class='panel rec' id='rec-{_e(kind)}-{_e(name)}'><summary>{head}</summary>"
            f"<div class='panel-body'>{body}<h4>{t('관리')}</h4>{_manage(ws, r, hidden)}</div></details>")


def _manage(ws: Workspace, r: dict[str, Any], hidden: str, *, edit: bool = True) -> str:
    """What the owner can do with a record, as it stands: rename it, deprecate it, review it, remove it,
    restore it, write a new version of it (a policy: in its own form, `edit` links there)."""
    a = r["attrs"]
    kind, name, state = a["kind"], a["name"], r["state"]
    k = ws.caps.kind(kind)
    ident = (f"{hidden}<input type=hidden name=kind value='{_e(kind)}'>"
             f"<input type=hidden name=name value='{_e(name)}'>")

    def form(action: str, label: str, hint: str, fields: str, button: str, cls: str = "") -> str:
        return (f"<form method=post action='/approvals/cap/manage'>{ident}<input type=hidden name=action value={action}>"
                f"<span class='lab'>{label}" + (f" <span class='muted'>{hint}</span>" if hint else "") + "</span>"
                f"{fields}<button{f' class={cls}' if cls else ''}>{button}</button></form>")

    forms = []
    if state in ("active", "deprecated") and k.renamable:
        move = (f"<label class='check'><input type=checkbox name=move checked> {t('이 정책을 쓰는 스크립트도 옮기기')}</label>"
                if kind == "policy" else "")
        forms.append(form("rename", t("이름 바꾸기"), t("옛 이름은 새 이름을 가리키다 은퇴합니다"),
                          f"<input name=new required pattern='{NAME_PATTERN}' maxlength=64 "
                          f"placeholder='{_e(t('새 이름'))}' aria-label='{_e(t('새 이름'))}'>{move}", t("바꾸기")))
    if state == "active":
        forms.append(form("deprecate", t("폐기 예정 표시"), t("유예 기간 동안 경고와 함께 동작합니다"),
                          f"<input name=why required placeholder='{_e(t('사유'))}' aria-label='{_e(t('사유'))}'>",
                          t("폐기 예정으로"), "secondary"))
        forms.append(form("review", t("지금 점검"), t("검토 기한을 기다리지 않고 점검합니다"), "", t("점검"), "secondary"))
    if state in ("deprecated", "retired"):
        forms.append(form("restore", t("복원"), t("마지막으로 쓰던 버전을 새 버전으로 되살립니다"), "", t("복원")))
    if state != "retired":
        forms.append(form("remove", t("제거"), t("바로 은퇴합니다. 이력은 남고 복원할 수 있습니다"),
                          f"<input name=why placeholder='{_e(t('사유 (선택)'))}' aria-label='{_e(t('사유'))}'>",
                          t("제거"), "danger"))
    out = f"<div class='manage'>{''.join(forms)}</div>"
    if edit and kind == "policy" and state != "retired":
        out += f"<p class='small'><a href='#policy-{_e(name)}'>{t('정책 폼에서 고치기')}</a></p>"
    elif edit and state != "retired" and kind != "rule":
        cur = ws.caps.version(r, a.get("version") or a.get("pending"))
        body = (f"<label>{t('본문')}<textarea name=body rows=10 spellcheck=false>{_e(cur['body'] or '')}</textarea></label>"
                if k.has_body else "")
        out += (f"<details class='edit'><summary>{t('새 버전으로 고치기')}</summary>"
                f"<form method=post action='/approvals/cap/manage'>{ident}<input type=hidden name=action value=edit>"
                f"<label>{t('설정 (JSON)')}<textarea name=spec rows=6 spellcheck=false>"
                f"{_e(json.dumps(cur['spec'], ensure_ascii=False, indent=1, sort_keys=True))}</textarea></label>{body}"
                f"<label>{t('메모')}<input name=note placeholder='{_e(t('무엇을 왜 바꿨는지'))}'></label>"
                f"<div class='actions'><button>{t('새 버전 저장')}</button></div></form></details>")
    return out


def _manage_action(ws: Workspace, f: dict[str, str]) -> str:
    """POST /approvals/cap/manage: the user's change of a record (the user changes any record)."""
    kind, name, what = f.get("kind", ""), f.get("name", ""), f.get("action", "")
    why, who, caps = f.get("why", "").strip(), f"{_kind(kind)} {name}", ws.caps
    if what == "rename":
        new = f.get("new", "").strip()
        was = caps.get(kind, name)["state"]
        _, moved, kept = ws.rename(kind, name, new, actor="user", why=why,
                                   move=f.get("move") == "on" or kind != "policy")
        out = (t("{what} → {new}: 마지막으로 쓰던 버전으로 새 기록을 만들었습니다. 옛 기록은 은퇴한 채 남습니다.", what=who, new=new)
               if was == "retired" else
               t("{what} → {new}: 이름을 바꿨습니다. 옛 이름은 폐기 예정으로 남아 새 이름을 가리키다 은퇴합니다.", what=who, new=new))
        if moved:
            out += " " + t("함께 옮긴 것: {names}", names=", ".join(moved))
        if kept:
            out += " " + t("아직 옛 이름을 쓰는 것: {names}", names=", ".join(kept))
        return out
    if what == "deprecate":
        caps.deprecate(kind, name, actor="user", why=why or "deprecated by the user")
        return t("{what}: 폐기 예정으로 표시했습니다. 유예 기간 동안 경고와 함께 동작합니다.", what=who)
    if what == "remove":
        caps.remove(kind, name, actor="user", why=why)
        return t("{what}: 제거했습니다. 이력은 남아 있어 복원할 수 있습니다.", what=who)
    if what == "restore":
        caps.restore(kind, name, actor="user")
        if kind == "policy":
            ws.request_mounts()
        return t("{what}: 복원했습니다.", what=who)
    if what == "review":
        return t("{what}: 점검했습니다 ({result})", what=who, result=caps.review_now(kind, name, actor="user"))
    if what == "edit":
        if kind in ("policy", "rule"):
            raise HandbookError(t("{what}: 이 종류는 여기서 고치지 않습니다", what=who))
        try:
            spec = json.loads(f.get("spec") or "{}")
        except ValueError as e:
            raise HandbookError(t("설정이 올바른 JSON이 아닙니다: {error}", error=str(e))) from e
        if not isinstance(spec, dict):
            raise HandbookError(t("설정은 JSON 객체여야 합니다"))
        body = f["body"].replace("\r\n", "\n") if "body" in f else None  # a browser sends a textarea's lines as CRLF
        _, msg = caps.update(kind, name, spec=spec, body=body, actor="user", note=f.get("note", "").strip(), replace=True)
        return t("{what}: 새 버전을 저장했습니다 ({result})", what=who, result=msg.splitlines()[0])
    raise HandbookError(t("모르는 동작입니다: {action}", action=what))


def _jobs(ws: Workspace) -> str:
    """The last jobs, one line each: a long argument list is cut on the line (all of it on hover)."""
    rows = []
    for j in ws.jobs(30):
        args = " ".join(j["attrs"].get("args", []))
        rows.append(f"<tr><td><code>{_e(j['id'])}</code></td>"
                    f"<td><span class='tag {JOB_TAGS.get(j['state'], '')}'>"
                    f"{_e(t(JOB_LABELS[j['state']]) if j['state'] in JOB_LABELS else j['state'])}</span></td>"
                    f"<td><code>{_e(j['attrs'].get('script'))}</code> "
                    f"<span class='clip muted small' title='{_e(args[:2000])}'>{_e(args[:300])}</span></td>"
                    f"<td class='num'>{_e(j['attrs'].get('exit', ''))}</td></tr>")
    if not rows:
        return _empty(t("아직 실행한 작업이 없습니다."))
    heads = "".join(f"<th>{t(h)}</th>" for h in (N_("작업"), N_("상태"), N_("스크립트"), N_("종료 코드")))
    return (f"<div class='table-wrap'><table><thead><tr>{heads}</tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _policy_record(ws: Workspace, name: str, hidden: str) -> tuple[str, str]:
    """A policy panel's foot (what its owner can do with its record) and who wrote the version in force."""
    rec = ws.caps.find("policy", name)
    if rec is None:
        return "", ""
    by = ""
    if rec["attrs"].get("version"):
        ver = ws.caps.version(rec)
        by = f"v{ver['version']} · {ver['author']} · {_day(ver['created'])}"
    return _manage(ws, rec, hidden, edit=False), by


def _overview(ws: Workspace, uid: str, token: str, q: Any, draft: dict[str, str] | None = None) -> str:
    """The page. `draft`: a policy form that was refused, to show again as it was typed."""
    caps = ws.caps
    hidden = f"<input type=hidden name=csrf value='{token}'>"
    waiting = [r for r in caps.list() if r["attrs"].get("pending")]
    rules = proposals.open_proposals(ws.g)
    policies = ws.policies()
    n_records, records = _records(ws, hidden)
    offered = _offered(ws)

    summary = "".join(f"<a class='chip{' warn' if n and warn else ''}' href='#{a}'>{label} <b>{n}</b></a>"
                      for a, label, n, warn in (("grants", t("승인 대기"), len(waiting), True),
                                                ("rules", t("제안된 규칙"), len(rules), True),
                                                ("policies", t("정책"), len(policies), False),
                                                ("records", t("기능 기록"), n_records, False)))
    out = [f"<div class='page-head'><h1>{t('에이전트 · 샌드박스')}</h1>"
           f"<p class='muted'><b>{_e(uid)}</b> · {t('여기서 하는 승인과 정책은 모델이 대신할 수 없는, 사용자의 결정입니다.')}</p>"
           f"<nav class='chips'>{summary}<a class='chip' href='/agents/'>{t('에이전트 실행')}</a>"
           f"<a class='chip' href='/agents/keys'>{t('API 키')}</a></nav></div>"]
    if q.get("ok"):
        out.append(f"<p class='flash ok'>{_e(q['ok'])}</p>")
    if q.get("err"):
        out.append(f"<p class='flash error'>{_e(q['err'])}</p>")

    out.append(_section("grants", t("승인 대기 중인 권한 ({n})", n=len(waiting)),
                        t("모델이 쓴 버전 중 할 수 있는 일을 넓히는 것. 좁히는 변경과 스크립트는 승인 없이 바로 적용됩니다."),
                        "".join(_grant(caps, r, hidden) for r in waiting) or _empty(t("모델이 요청한 권한 확장이 없습니다."))))
    out.append(_section("rules", t("제안된 규칙 ({n})", n=len(rules)),
                        t("제안은 경고로만 돌다가, 여기서 승인하면 막는 규칙이 됩니다."),
                        "".join(_rule(r, hidden) for r in rules) or _empty(t("열린 제안이 없습니다."))))
    out.append(_section("policies", t("샌드박스 정책 ({n})", n=len(policies)),
                        t("정책이 곧 샌드박스입니다: 보이는 명령, 네트워크, 한도. 한 번 허용하면 그 안의 스크립트와 실행은 다시 묻지 않습니다. 정책을 눌러 펼치면 고칠 수 있습니다."),
                        "".join(_policy(n, ws.policy(n)["attrs"], ws.policy(n), hidden, offered,
                                        draft if draft is not None and draft.get("name") == n else None,
                                        _mount_status(ws, ws.policy(n)["attrs"]), *_policy_record(ws, n, hidden))
                                for n in policies)
                        + _policy("", ws.base_policy(), None, hidden, offered,
                                  draft if draft is not None and draft.get("name") not in policies else None)))
    out.append(_section("records", t("기능 기록 ({n})", n=n_records),
                        t("정책·스크립트·레이어·외부 접속·별칭·카드·규칙. 각 기록은 버전이 남고, 검토 기한이 지나면 스스로 점검해 갱신되거나 폐기 예정이 됩니다. 기록을 펼치면 내용과 이력을 보고 이름 바꾸기·폐기 예정·제거·복원을 할 수 있습니다."),
                        records))
    out.append(_section("jobs", t("최근 작업"), t("마지막 30개."), _jobs(ws)))
    return "".join(out)
