"""The approval page: /agents, the user's channel (docs/kernel.md "Reviewing the rules", docs/agents.md §9).

Behind the site sign-in: nginx asks the SSO, which mints an X-Auth-Token for the
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
from ..page import page
from ..store import Handbook, HandbookError
from .workspace import Workspace

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
        return page("에이전트 · 샌드박스", body, login_url=login_url, status=status, referrer="same-origin")

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
            return _html("<p class='flash error'>로그인이 필요합니다.</p>", 401)
        form = {k: str(v)[:20_000] for k, v in (await request.form()).items()}
        if not same_origin(request) or not hmac.compare_digest(form.get("csrf", ""), csrf(uid)):
            return _html("<p class='flash error'>요청을 확인할 수 없습니다. 페이지를 새로 열어 다시 시도하세요.</p>", 403)
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
                    changes["ports"] = "any" if ports == "any" else [int(x) for x in ports.split()]
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


def _e(x: Any) -> str:
    return html.escape(str(x))


# ── the page ─────────────────────────────────────────────────────────────
# Laid out with the site's stylesheet (portal/static/style.css): a card per section, folded panels for
# the policies, key/value lists instead of JSON dumps.

LIMITS = (("timeout", "시간(초)"), ("memory_mb", "메모리 MB"), ("cpus", "CPU"), ("disk_mb", "디스크 MB"),
          ("tmp_mb", "tmp MB"), ("concurrent", "동시 실행"))
STATE_TAGS = {"active": "ok", "proposed": "warn", "deprecated": "bad"}


def _value(v: Any) -> str:
    """A spec value as the page shows it: lists joined, booleans in words."""
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, list):
        return " ".join(v) if all(isinstance(x, str) for x in v) else json.dumps(v, ensure_ascii=False)
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
    status = f"현재 v{a['version']}" if a.get("version") else "아직 적용된 버전 없음"
    body = (f"<details><summary>본문</summary><pre>{_e(ver['body'][:20000])}</pre></details>" if ver["body"] else "")
    return (f"<div class='item'><div class='item-head'><b>{_e(a['kind'])} {_e(a['name'])}</b>"
            f"<span class='tag'>v{a['pending']}</span><span class='muted small'>작성 {_e(ver['author'])} · {status}</span></div>"
            f"<p>넓어지는 것: {''.join(f'<span class=\"tag warn\">{_e(w)}</span>' for w in why) or '-'}</p>"
            + (f"<p class='muted'>{_e(ver['note'])}</p>" if ver["note"] else "")
            + _kv(ver["spec"]) + body
            + f"<div class='actions'><form class=inline method=post action='/agents/cap/approve'>{ident}<button>승인</button></form>"
            f"<form class=inline method=post action='/agents/cap/reject'>{ident}<button class=secondary>거절</button></form></div></div>")


def _rule(r: dict[str, Any], hidden: str) -> str:
    rid = f"<input type=hidden name=rule value='{_e(r['id'])}'>"
    replaces = "".join(f"<details><summary>승인하면 은퇴하는 규칙 {_e(o['id'])}</summary>"
                       f"<p class='muted small'>{_e(o.get('message', ''))}</p><pre>{_e(o.get('body', ''))}</pre></details>"
                       for o in r["replaces"])
    label = "승인" + (f" ({_e(' '.join(o['id'] for o in r['replaces']))} 대체)" if r["replaces"] else "")
    return (f"<div class='item'><div class='item-head'><b>{_e(r['id'])}</b><span class='tag'>{_e(r['phase'])}</span>"
            f"<span class='tag warn'>승인하면 {_e(r['severity'])}</span>"
            f"<span class='muted small'>승인 해시 {r['approval']}</span></div>"
            f"<p>{_e(r['message'])}</p><p class='muted small'>{_e(r['why'])}</p><pre>{_e(r['body'])}</pre>{replaces}"
            f"<div class='actions'><form class=inline method=post action='/agents/approve'>{hidden}{rid}"
            f"<input type=hidden name=seen value='{r['approval']}'><button>{label}</button></form>"
            f"<form class=inline method=post action='/agents/reject'>{hidden}{rid}<button class=secondary>거절</button></form>"
            "</div></div>")


def _policy(name: str, a: dict[str, Any], p: dict[str, Any] | None, hidden: str) -> str:
    """One policy as a folded panel: a summary line, and its form when opened (a new one has a name field)."""
    ports = "any" if a.get("ports") in (None, "any") else " ".join(map(str, a.get("ports") or []))
    mounts = "\n".join(m["source"] + " " + m["target"] + (" rw" if m["rw"] else "") for m in a.get("mounts") or [])
    if p:
        head = (f"<b>{_e(name)}</b><span class='muted small'>작성 {_e(p['author'])}</span>"
                f"<span class='tag {'warn' if a['network'] else ''}'>네트워크 {'켜짐' if a['network'] else '꺼짐'}"
                f"{' · ' + _e(ports) if a['network'] else ''}</span>"
                f"<span class='tag'>명령 {'전부' if '*' in a['commands'] else len(a['commands'])}</span>"
                f"<span class='tag'>{_e(a.get('timeout', ''))}s · {_e(a.get('memory_mb', ''))} MB</span>"
                + (f"<span class='muted small'>{_e(p['content'])}</span>" if p["content"] else ""))
        ident = f"<input type=hidden name=name value='{_e(name)}'>"
    else:
        head = "<b>새 정책</b><span class='muted small'>기본 정책에서 시작합니다</span>"
        ident = "<label>이름 <input name=name required pattern='[a-z0-9][a-z0-9._-]*'></label>"
    limits = "".join(f"<label>{lab}<input name={k} value='{_e(a.get(k, ''))}'></label>" for k, lab in LIMITS)
    return (f"<details class='panel'><summary>{head}</summary>"
            f"<form method=post action='/agents/policy'>{hidden}"
            f"<div class='cols'>{ident}<label>설명 <input name=description value='{_e(p['content'] if p else '')}'></label></div>"
            f"<label>명령 <span class='muted small'>공백으로 구분, * 는 모든 명령</span>"
            f"<textarea name=commands rows=3>{_e(' '.join(a['commands']))}</textarea></label>"
            f"<div class='cols'><label>레이어 <span class='muted small'>공백으로 구분</span>"
            f"<input name=layers value='{_e(' '.join(a.get('layers') or []))}'></label>"
            f"<label>마운트 <span class='muted small'>한 줄에 하나: 원본 대상 [rw] · {{user}} 사용 가능</span>"
            f"<textarea name=mounts rows=2>{_e(mounts)}</textarea></label></div>"
            f"<div class='cols'><label class='check'><input type=checkbox name=network {'checked' if a['network'] else ''}>"
            f" 네트워크 허용</label><label>포트 <input name=ports value='{_e(ports)}'></label></div>"
            f"<div class='fields'>{limits}</div>"
            f"<div class='actions'><button>저장</button></div></form></details>")


def _records(caps: Any) -> tuple[int, str]:
    recs = caps.list()
    rows = []
    for r in recs:
        a = r["attrs"]
        note = (a.get("reason") or "") if r["state"] != "active" else time.strftime(
            "%Y-%m-%d", time.localtime(a.get("review_after") or 0)) if a.get("review_after") else ""
        rows.append(f"<tr><td>{_e(a['kind'])}</td><td><b>{_e(a['name'])}</b></td><td>{_e(a.get('version') or '-')}</td>"
                    f"<td><span class='tag {STATE_TAGS.get(r['state'], '')}'>{_e(r['state'])}</span></td>"
                    f"<td>{_e(r['author'])}</td><td>{_e(note)}</td><td class='wrap'>{_e(r['content'])}</td></tr>")
    table = ("<div class='table-wrap'><table><thead><tr><th>종류</th><th>이름</th><th>버전</th><th>상태</th><th>작성</th>"
             f"<th>검토 / 사유</th><th>설명</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    return len(recs), table if recs else _empty("기록이 없습니다.")


def _jobs(ws: Workspace) -> str:
    rows = [f"<tr><td><code>{_e(j['id'])}</code></td><td><span class='tag'>{_e(j['state'])}</span></td>"
            f"<td class='wrap'>{_e(j['attrs'].get('script'))} {_e(' '.join(j['attrs'].get('args', [])))}</td>"
            f"<td>{_e(j['attrs'].get('exit', ''))}</td></tr>" for j in ws.jobs(30)]
    if not rows:
        return _empty("아직 실행한 작업이 없습니다.")
    return ("<div class='table-wrap'><table><thead><tr><th>작업</th><th>상태</th><th>스크립트</th><th>종료 코드</th></tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table></div>")


def _overview(ws: Workspace, uid: str, token: str, q: Any) -> str:
    caps = ws.caps
    hidden = f"<input type=hidden name=csrf value='{token}'>"
    waiting = [r for r in caps.list() if r["attrs"].get("pending")]
    rules = proposals.open_proposals(ws.g)
    policies = ws.policies()
    n_records, records = _records(caps)

    summary = "".join(f"<a class='chip{' warn' if n and warn else ''}' href='#{a}'>{label} <b>{n}</b></a>"
                      for a, label, n, warn in (("grants", "승인 대기", len(waiting), True),
                                                ("rules", "제안된 규칙", len(rules), True),
                                                ("policies", "정책", len(policies), False),
                                                ("records", "기능 기록", n_records, False)))
    out = [f"<div class='page-head'><h1>에이전트 · 샌드박스</h1>"
           f"<p class='muted'><b>{_e(uid)}</b> · 여기서 하는 승인과 정책은 모델이 대신할 수 없는, 사용자의 결정입니다.</p>"
           f"<nav class='chips'>{summary}</nav></div>"]
    if q.get("ok"):
        out.append(f"<p class='flash ok'>{_e(q['ok'])}</p>")
    if q.get("err"):
        out.append(f"<p class='flash error'>{_e(q['err'])}</p>")

    out.append(_section("grants", f"승인 대기 중인 권한 ({len(waiting)})",
                        "모델이 쓴 버전 중 할 수 있는 일을 넓히는 것. 좁히는 변경과 스크립트는 승인 없이 바로 적용됩니다.",
                        "".join(_grant(caps, r, hidden) for r in waiting) or _empty("모델이 요청한 권한 확장이 없습니다.")))
    out.append(_section("rules", f"제안된 규칙 ({len(rules)})",
                        "제안은 경고로만 돌다가, 여기서 승인하면 막는 규칙이 됩니다.",
                        "".join(_rule(r, hidden) for r in rules) or _empty("열린 제안이 없습니다.")))
    out.append(_section("policies", f"샌드박스 정책 ({len(policies)})",
                        "정책이 곧 샌드박스입니다: 보이는 명령, 네트워크, 한도. 한 번 허용하면 그 안의 스크립트와 실행은 "
                        "다시 묻지 않습니다. 정책을 눌러 펼치면 고칠 수 있습니다.",
                        "".join(_policy(n, ws.policy(n)["attrs"], ws.policy(n), hidden) for n in policies)
                        + _policy("", ws.base_policy(), None, hidden)))
    out.append(_section("records", f"기능 기록 ({n_records})",
                        "스크립트·정책·레이어·규칙·카드·별칭. 각 기록은 버전이 남고, 검토 기한이 지나면 스스로 점검해 갱신되거나 "
                        "폐기 예정이 됩니다.", records))
    out.append(_section("jobs", "최근 작업", "마지막 30개.", _jobs(ws)))
    return "".join(out)
