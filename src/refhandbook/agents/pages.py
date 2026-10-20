"""The approval page: /agents, the user's channel (docs/kernel.md "Reviewing the rules", docs/agents.md §9).

Behind the site sign-in only (RHB_AUTH=sso): nginx asks the SSO, which mints an X-Auth-Token for the
audience `refhandbook`, and every request here verifies it. What the page writes is written as
`user`: it is the one place, besides the server's terminal, where a model's proposal becomes a rule
that blocks and where a sandbox policy is granted. Forms carry a token bound to the signed-in uid
(HMAC with a key kept in the data directory) and must come from this origin.

    GET  /agents              grants waiting (capability versions that widen what the model may do),
                              rule proposals (with the hash of what each says), policies, records, jobs
    POST /agents/cap/approve  kind, name, version → Registry.approve(actor=user): that version in force
    POST /agents/cap/reject   kind, name, version → Registry.reject(actor=user)
    POST /agents/approve      rule, seen   → Graph.approve(actor=user, seen=…), optionally retiring `replaces`
    POST /agents/reject       rule         → retire_rule(actor=user): the model cannot propose that id again
    POST /agents/policy       name, …      → Workspace.set_policy(actor=user): a new version of the policy
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import anyio
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from ..kernel import proposals
from ..store import Handbook, HandbookError
from .workspace import Workspace

CSS = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #ddd}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;padding:.4rem;vertical-align:top;text-align:left}
pre{background:#f6f6f6;padding:.5rem;white-space:pre-wrap;margin:.3rem 0;font-size:13px}
form.inline{display:inline}button{padding:.25rem .8rem;margin:.1rem}input,textarea{font:inherit;width:100%;box-sizing:border-box}
.small{width:6rem}.note{color:#555;font-size:13px}.ok{background:#e8f6e8;padding:.5rem}.err{background:#fde8e8;padding:.5rem}
@media (prefers-color-scheme:dark){body{background:#151515;color:#ddd}pre{background:#222}td,th{border-color:#333}}"""


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
            public_url: str, lock: Any, login_url: str = "/auth/login",
            allowed: Callable[[str], bool] = lambda uid: True) -> None:
    """Register the /agents routes on the MCP server `m` (remote.build, SSO mode only)."""
    key = _key(data_dir)
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

    @m.custom_route("/agents", methods=["GET"])
    async def overview(request: Request) -> Response:
        uid = who(request)
        if uid is None:
            return RedirectResponse(f"{login_url}?next=/agents", status_code=303)
        body = await locked(lambda: _overview(Workspace(stores(uid)), uid, csrf(uid), request.query_params))
        return _html(body)

    async def post(request: Request, action: Callable[[Workspace, dict[str, str]], str]) -> Response:
        uid = who(request)
        if uid is None:
            return _html("<p class=err>로그인이 필요합니다.</p>", 401)
        form = {k: str(v)[:20_000] for k, v in (await request.form()).items()}
        if not same_origin(request) or not hmac.compare_digest(form.get("csrf", ""), csrf(uid)):
            return _html("<p class=err>요청을 확인할 수 없습니다. 페이지를 새로 열어 다시 시도하세요.</p>", 403)
        try:
            done = await locked(lambda: action(Workspace(stores(uid)), form))
            return RedirectResponse(f"/agents?ok={quote(done)}", status_code=303)
        except HandbookError as e:
            return RedirectResponse(f"/agents?err={quote(str(e)[:300])}", status_code=303)

    @m.custom_route("/agents/approve", methods=["POST"])
    async def approve(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            retired = proposals.approve(ws.g, f.get("rule", ""), f.get("seen", ""), actor="user")
            return f"규칙 {f.get('rule')} 승인" + (f", {' '.join(retired)} 은퇴" if retired else "")
        return await post(request, act)

    @m.custom_route("/agents/reject", methods=["POST"])
    async def reject(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            proposals.reject(ws.g, f.get("rule", ""), actor="user")
            return f"규칙 {f.get('rule')} 거절"
        return await post(request, act)

    @m.custom_route("/agents/cap/approve", methods=["POST"])
    async def cap_approve(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            return ws.caps.approve(f.get("kind", ""), f.get("name", ""), _int(f.get("version")), actor="user")
        return await post(request, act)

    @m.custom_route("/agents/cap/reject", methods=["POST"])
    async def cap_reject(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            return ws.caps.reject(f.get("kind", ""), f.get("name", ""), _int(f.get("version")), actor="user")
        return await post(request, act)

    @m.custom_route("/agents/policy", methods=["POST"])
    async def policy(request: Request) -> Response:
        def act(ws: Workspace, f: dict[str, str]) -> str:
            changes: dict[str, Any] = {"commands": f.get("commands", "").split(), "network": f.get("network") == "on",
                                       "description": f.get("description", ""),
                                       "layers": f.get("layers", "").split(), "mounts": _mounts(f.get("mounts", ""))}
            ports = f.get("ports", "").strip()
            if ports:
                try:
                    changes["ports"] = None if ports == "any" else [int(x) for x in ports.split()]
                except ValueError as e:
                    raise HandbookError("포트: 숫자 또는 any") from e
            for k, cast in (("timeout", int), ("memory_mb", int), ("disk_mb", int), ("tmp_mb", int),
                            ("concurrent", int), ("cpus", float)):
                if f.get(k, "").strip():
                    try:
                        changes[k] = cast(f[k])
                    except ValueError as e:
                        raise HandbookError(f"{k}: 숫자가 아닙니다") from e
            name = f.get("name", "")
            ws.set_policy(name, actor="user", **changes)
            return f"정책 {name} 저장"
        return await post(request, act)


def _int(x: str | None) -> int:
    try:
        return int(x or "")
    except ValueError as e:
        raise HandbookError("버전이 숫자가 아닙니다") from e


def _mounts(text: str) -> list[dict[str, Any]]:
    """One mount per line: SOURCE TARGET [rw]."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "rw"):
            raise HandbookError(f"마운트 줄 {line!r}: '원본 대상 [rw]'")
        out.append({"source": parts[0], "target": parts[1], "rw": len(parts) == 3})
    return out


def _html(body: str, status: int = 200) -> HTMLResponse:
    page = (f"<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>에이전트 · 샌드박스</title><style>{CSS}</style><body>{body}</body></html>")
    return HTMLResponse(page, status_code=status, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"})


def _e(x: Any) -> str:
    return html.escape(str(x))


def _overview(ws: Workspace, uid: str, token: str, q: Any) -> str:
    g = ws.g
    out = [f"<h1>에이전트 · 샌드박스</h1><p class=note><b>{_e(uid)}</b> · 여기서 하는 승인과 정책은 "
           "모델이 대신할 수 없는, 사용자의 결정입니다.</p>"]
    if q.get("ok"):
        out.append(f"<p class=ok>{_e(q['ok'])}</p>")
    if q.get("err"):
        out.append(f"<p class=err>{_e(q['err'])}</p>")
    hidden = f"<input type=hidden name=csrf value='{token}'>"
    caps = ws.caps

    # grants waiting: versions the model wrote that widen what it may do
    waiting = [r for r in caps.list() if r["attrs"].get("pending")]
    out.append(f"<h2>승인 대기 중인 권한 ({len(waiting)})</h2>")
    if not waiting:
        out.append("<p class=note>모델이 요청한 권한 확장이 없습니다. 좁히는 변경과 스크립트는 승인 없이 바로 적용됩니다.</p>")
    for r in waiting:
        a = r["attrs"]
        k = caps.kind(a["kind"])
        ver = caps.version(r, a["pending"])
        cur = caps.version(r) if a.get("version") else None
        why = k.widens(caps, cur["spec"] if cur else None, ver["spec"])
        ident = (f"<input type=hidden name=kind value='{_e(a['kind'])}'><input type=hidden name=name value='{_e(a['name'])}'>"
                 f"<input type=hidden name=version value='{a['pending']}'>")
        out.append(
            f"<p><b>{_e(a['kind'])} {_e(a['name'])}</b> v{a['pending']} <span class=note>(작성: {_e(ver['author'])}"
            f"{', 현재 v' + str(a['version']) if a.get('version') else ', 아직 적용된 버전 없음'})</span><br>"
            f"넓어지는 것: <b>{_e('; '.join(why) or '-')}</b>{'<br>' + _e(ver['note']) if ver['note'] else ''}</p>"
            f"<pre>{_e(json.dumps(ver['spec'], ensure_ascii=False, indent=1, sort_keys=True))}</pre>"
            + (f"<pre>{_e(ver['body'][:20000])}</pre>" if ver["body"] else "")
            + f"<form class=inline method=post action='/agents/cap/approve'>{hidden}{ident}<button>승인</button></form>"
            f"<form class=inline method=post action='/agents/cap/reject'>{hidden}{ident}<button>거절</button></form>")

    # proposals
    rules = proposals.open_proposals(g)
    out.append(f"<h2>제안된 규칙 ({len(rules)})</h2>")
    if not rules:
        out.append("<p class=note>열린 제안이 없습니다. 제안은 경고로만 돌다가, 여기서 승인하면 막는 규칙이 됩니다.</p>")
    for r in rules:
        retires = "".join(f"<p class=note>승인하면 은퇴하는 규칙 <b>{_e(o['id'])}</b>: {_e(o.get('message', ''))}</p>"
                          f"<pre>{_e(o.get('body', ''))}</pre>" for o in r["replaces"])
        out.append(
            f"<p><b>{_e(r['id'])}</b> <span class=note>[{_e(r['phase'])}, 승인하면 {_e(r['severity'])}] "
            f"승인 해시 {r['approval']}</span><br>{_e(r['message'])}<br><span class=note>{_e(r['why'])}</span></p>"
            f"<pre>{_e(r['body'])}</pre>{retires}"
            f"<form class=inline method=post action='/agents/approve'>{hidden}<input type=hidden name=rule value='{_e(r['id'])}'>"
            f"<input type=hidden name=seen value='{r['approval']}'>"
            f"<button>승인{' (' + _e(' '.join(o['id'] for o in r['replaces'])) + ' 대체)' if r['replaces'] else ''}</button></form>"
            f"<form class=inline method=post action='/agents/reject'>{hidden}<input type=hidden name=rule value='{_e(r['id'])}'>"
            "<button>거절</button></form>")

    # policies
    out.append("<h2>샌드박스 정책</h2><p class=note>정책이 곧 샌드박스입니다: 보이는 명령, 네트워크, 한도. "
               "한 번 허용하면 그 안의 스크립트와 실행은 다시 묻지 않습니다.</p>")
    for name in ws.policies() + [""]:
        a = ws.policy(name)["attrs"] if name else ws.policy("default")["attrs"]
        p = ws.policy(name) if name else None
        title = f"{_e(name)} <span class=note>(작성: {_e(p['author'])})</span>" if p else "새 정책"
        out.append(
            f"<h3>{title}</h3><form method=post action='/agents/policy'>{hidden}"
            + (f"<input type=hidden name=name value='{_e(name)}'>" if name else
               "<label>이름 <input name=name required pattern='[a-z0-9][a-z0-9._-]*'></label>")
            + f"<label>설명 <input name=description value='{_e(p['content'] if p else '')}'></label>"
            f"<label>명령 (공백으로 구분, * 는 모든 명령) <textarea name=commands rows=3>{_e(' '.join(a['commands']))}</textarea></label>"
            f"<label>레이어 (공백으로 구분) <input name=layers value='{_e(' '.join(a.get('layers') or []))}'></label>"
            f"<label>마운트 (한 줄에 하나: 원본 대상 [rw]; 원본은 서버가 허용한 디렉터리 아래, {{user}} 사용 가능) "
            f"<textarea name=mounts rows=2>{_e(chr(10).join(m['source'] + ' ' + m['target'] + (' rw' if m['rw'] else '') for m in a.get('mounts') or []))}</textarea></label>"
            f"<label><input type=checkbox name=network {'checked' if a['network'] else ''} style='width:auto'> 네트워크</label> "
            f"<label>포트 <input class=small name=ports value='{_e('any' if a.get('ports') is None else ' '.join(map(str, a.get('ports') or [])))}'></label> "
            + " ".join(f"<label>{lab} <input class=small name={k} value='{_e(a.get(k, ''))}'></label>"
                       for k, lab in (("timeout", "시간(초)"), ("memory_mb", "메모리MB"), ("cpus", "CPU"),
                                      ("disk_mb", "디스크MB"), ("tmp_mb", "tmpMB"), ("concurrent", "동시")))
            + "<br><button>저장</button></form>")

    # every record (read-only): what is in force, what a review deprecated
    recs = caps.list()
    out.append(f"<h2>기능 기록 ({len(recs)})</h2><p class=note>스크립트·정책·레이어·규칙·카드·별칭. 각 기록은 버전이 남고, "
               "검토 기한이 지나면 스스로 점검해 갱신되거나 폐기 예정이 됩니다.</p><table><tr><th>종류</th><th>이름</th>"
               "<th>버전</th><th>상태</th><th>작성</th><th>검토/사유</th><th>설명</th></tr>")
    for r in recs:
        a = r["attrs"]
        note = (a.get("reason") or "") if r["state"] != "active" else time.strftime(
            "%Y-%m-%d", time.localtime(a.get("review_after") or 0)) if a.get("review_after") else ""
        out.append(f"<tr><td>{_e(a['kind'])}</td><td>{_e(a['name'])}</td><td>{_e(a.get('version') or '-')}</td>"
                   f"<td>{_e(r['state'])}</td><td>{_e(r['author'])}</td><td>{_e(note)}</td><td>{_e(r['content'])}</td></tr>")
    out.append("</table><h2>최근 작업</h2><table><tr><th>작업</th><th>상태</th><th>스크립트</th><th>종료</th></tr>")
    for j in ws.jobs(30):
        a = j["attrs"]
        out.append(f"<tr><td>{_e(j['id'])}</td><td>{_e(j['state'])}</td><td>{_e(a.get('script'))} "
                   f"{_e(' '.join(a.get('args', [])))}</td><td>{_e(a.get('exit', ''))}</td></tr>")
    out.append("</table>")
    return "".join(out)

