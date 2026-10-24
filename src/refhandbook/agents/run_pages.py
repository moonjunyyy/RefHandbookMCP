"""The pages for API keys and runs (docs/agents.md §9), rendered for pages.install's routes:

    /agents/keys          the user's keys: provider (Claude, OpenAI, Gemini, or a custom server in one
                          of the standard formats), label, fingerprint, models; add and delete
    /agents/runs          a new run (goal and grant) and the list of runs
    /agents/runs/<run>    one run: the grant form while it awaits approval; then its agents, usage,
                          shared notes, result, and cancel

The grant form is the routing policy: rows of key, model and the roles it serves, in order of
preference (the first route for a role is where its agents start; the next ones are where they go
when a key is refused or a provider keeps failing), then the limits, the pruning levels, the sandbox
policy and the effort.
"""

from __future__ import annotations

import html
import time
from typing import Any

from ..store import HandbookError
from .keys import FORMATS, PROVIDERS, KeyInfo
from .team import CONTEXT_LEVELS, DEFAULT_GRANT, EFFORTS, HANDOFF_LEVELS, RETENTION_LEVELS, ROLES, Team

ROUTE_ROWS = 4
PROVIDER_NAMES = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Gemini (Google)",
                  "custom": "Custom (표준 형식 서버)"}
FORMAT_NAMES = {"anthropic": "Anthropic Messages", "openai": "OpenAI Responses",
                "openai-chat": "OpenAI Chat Completions (vLLM, Ollama, OpenRouter …)", "gemini": "Gemini generateContent"}
# offered in the model field when a key's own list is empty (the provider's list call failed or is not offered)
SUGGESTED = {"anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]}
ROLE_NAMES = {"lead": "리드", "worker": "워커", "verifier": "검증"}
PHASE_TAGS = {"requested": "warn", "approved": "", "running": "ok", "done": "ok", "cancelled": "bad", "failed": "bad"}
PHASE_NAMES = {"requested": "승인 대기", "approved": "시작 대기", "running": "실행 중", "done": "완료",
               "cancelled": "취소됨", "failed": "실패"}
LIMIT_FIELDS = (("max_agents", "동시 에이전트"), ("max_spawns", "총 에이전트 수"), ("max_depth", "최대 깊이"),
                ("max_steps", "에이전트당 턴"), ("max_tokens", "토큰 한도 (0: 없음)"))
LEVEL_NAMES = {"full": "전체", "trim": "오래된 출력 정리", "digest": "주기적 요약", "minimal": "최소",
               "refs": "id만", "all": "모두 보관", "verified": "검증된 것만", "exits": "결과만", "purge": "결과 외 삭제"}


def _e(x: Any) -> str:
    return html.escape(str(x))


def _day(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


def _flash(q: Any) -> str:
    out = ""
    if q.get("ok"):
        out += f"<p class='flash ok'>{_e(q['ok'])}</p>"
    if q.get("err"):
        out += f"<p class='flash error'>{_e(q['err'])}</p>"
    return out


def nav(here: str) -> str:
    links = (("/agents", "승인 · 샌드박스"), ("/agents/runs", "에이전트 실행"), ("/agents/presets", "프리셋 · 예약"),
             ("/agents/files", "파일"), ("/agents/keys", "API 키"))
    return "<nav class='chips'>" + "".join(
        f"<a class='chip{' warn' if href == here else ''}' href='{href}'>{label}</a>" for href, label in links) + "</nav>"


def _head(title: str, intro: str, here: str, uid: str) -> str:
    return (f"<div class='page-head'><h1>{title}</h1><p class='muted'><b>{_e(uid)}</b> · {intro}</p>"
            f"{nav(here)}</div>")


def _select(name: str, options: list[tuple[str, str]], value: str = "", attrs: str = "") -> str:
    return (f"<select name={name} {attrs}>" + "".join(
        f"<option value='{_e(v)}'{' selected' if v == value else ''}>{_e(label)}</option>" for v, label in options)
        + "</select>")


# ── keys ─────────────────────────────────────────────────────────────────


def keys_page(uid: str, keys: list[KeyInfo], hidden: str, q: Any, can_add: str | None) -> str:
    rows = "".join(
        f"<tr><td><b>{_e(k.ref)}</b></td><td>{_e(FORMAT_NAMES.get(k.format, k.format))}"
        + (f"<br><span class='muted small'>{_e(k.base_url)}</span>" if k.base_url else "")
        + f"</td><td><code>{_e(k.fingerprint)}</code></td>"
        f"<td><span class='tag {'ok' if k.status == 'ok' else 'warn' if k.status == 'unchecked' else 'bad'}'>"
        f"{_e(k.status)}</span></td><td>{len(k.models) or '-'}</td><td>{_day(k.created)}</td><td>{_day(k.last_used)}</td>"
        f"<td><form class=inline method=post action='/agents/keys/delete'>{hidden}"
        f"<input type=hidden name=ref value='{_e(k.ref)}'><button class=secondary>삭제</button></form></td></tr>"
        for k in keys)
    table = ("<div class='table-wrap'><table><thead><tr><th>키</th><th>형식</th><th>지문</th><th>상태</th><th>모델</th>"
             f"<th>등록</th><th>마지막 사용</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"
             if keys else "<p class='empty muted'>등록한 키가 없습니다.</p>")
    if can_add:
        add = f"<p class='flash error'>지금은 키를 등록할 수 없습니다: {_e(can_add)}</p>"
    else:
        add = (f"<form method=post action='/agents/keys/add' autocomplete=off>{hidden}"
               "<div class='cols'><label>제공자 "
               + _select("provider", [(p, PROVIDER_NAMES[p]) for p in PROVIDERS])
               + "</label><label>이름 <span class='muted small'>영문·숫자·.-_ (예: main, work)</span>"
               "<input name=label required pattern='[A-Za-z0-9._-]{1,32}' value='main'></label></div>"
               "<label>API 키 <span class='muted small'>Custom 서버가 인증을 받지 않으면 비워 두세요</span>"
               "<input name=secret type=password autocomplete=new-password></label>"
               "<details><summary>Custom 서버 설정</summary><div class='cols'><label>형식 "
               + _select("format", [(f, FORMAT_NAMES[f]) for f in FORMATS], "openai-chat")
               + "</label><label>Base URL <span class='muted small'>버전 경로까지 (예: https://openrouter.ai/api/v1)"
               "</span><input name=base_url placeholder='https://…/v1'></label></div>"
               "<p class='muted small'>사설 주소나 http 서버는 관리자가 RHB_AGENT_PRIVATE_ENDPOINTS에 둔 호스트만 쓸 수 "
               "있습니다.</p></details>"
               "<div class='actions'><button>확인하고 등록</button></div></form>")
    return (_head("API 키", "에이전트가 쓰는 본인의 키입니다. 키는 등록 즉시 암호화되어, 에이전트를 실행하는 러너만 열 수 "
                  "있습니다. 모델도, 이 웹 서버도 키를 볼 수 없습니다.", "/agents/keys", uid)
            + _flash(q)
            + f"<section class='card section'><h2>등록된 키 ({len(keys)})</h2>{table}</section>"
            + "<section class='card section'><h2>키 등록</h2><p class='muted small'>등록할 때 제공자의 모델 목록을 한 번 "
              f"불러와 키를 확인합니다. 그 목록은 실행 화면의 모델 선택에 쓰입니다.</p>{add}</section>")


# ── runs ─────────────────────────────────────────────────────────────────


def _models(keys: list[KeyInfo]) -> str:
    names: set[str] = set()
    for k in keys:
        names |= set(k.models) or set(SUGGESTED.get(k.format if k.provider == "custom" else k.provider, []))
    return "<datalist id=models>" + "".join(f"<option value='{_e(m)}'>" for m in sorted(names)) + "</datalist>"


def _routes_prefill(keys: list[KeyInfo], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """The routes of a grant (a preset's), or those suggested by the requester (roles → model), else one
    route for every role on the first key."""
    if not keys:
        return []
    if isinstance(proposal.get("routes"), list) and proposal["routes"]:
        return [dict(r) for r in proposal["routes"]][:ROUTE_ROWS]
    roles = proposal.get("roles") if isinstance(proposal.get("roles"), dict) else {}
    by_model: dict[str, list[str]] = {}
    for role, model in roles.items():
        by_model.setdefault(model, []).append(role)
    out = []
    for model, rs in by_model.items():
        key = next((k for k in keys if model in k.models), keys[0])
        out.append({"key": key.ref, "model": model, "roles": rs})
    if out and not any("lead" in r["roles"] for r in out):
        out[0]["roles"].append("lead")
    if not out:
        k = keys[0]
        model = (SUGGESTED.get(k.provider) or sorted(k.models) or [""])[0]
        out = [{"key": k.ref, "model": model, "roles": list(ROLES)}]
    return out


def grant_form(action: str, keys: list[KeyInfo], policies: list[str], hidden: str, *, goal: bool,
               proposal: dict[str, Any] | None = None, submit: str = "승인하고 시작", reject: str = "",
               values: dict[str, str] | None = None, head: str = "", buttons: str = "") -> str:
    """The grant form. `reject` is an action the same form can post to instead (its token rides along);
    `values` fill the goal and title, `head` goes first (a preset's name), `buttons` after the submit."""
    proposal = proposal or {}
    values = values or {}
    if not keys:
        return "<p class='flash error'>먼저 <a href='/agents/keys'>API 키</a>를 등록하세요.</p>"
    v = {**DEFAULT_GRANT, **{k: proposal[k] for k in DEFAULT_GRANT if k in proposal}}
    pre = _routes_prefill(keys, proposal)
    key_opts = [("", "—")] + [(k.ref, f"{k.ref} ({PROVIDER_NAMES[k.provider].split(' ')[0]})") for k in keys]
    rows = []
    for i in range(ROUTE_ROWS):
        r = pre[i] if i < len(pre) else {"key": "", "model": "", "roles": []}
        checks = "".join(f"<label class='check'><input type=checkbox name=route{i}_{role}"
                         f"{' checked' if role in r['roles'] else ''}> {ROLE_NAMES[role]}</label>" for role in ROLES)
        rows.append(f"<tr><td>{i + 1}</td><td>{_select(f'route{i}_key', key_opts, r['key'])}</td>"
                    f"<td><input name=route{i}_model list=models value='{_e(r['model'])}' placeholder='모델'></td>"
                    f"<td class='roles'>{checks}</td></tr>")
    routes = ("<div class='table-wrap'><table class='routes'><thead><tr><th>순서</th><th>키</th><th>모델</th><th>역할</th>"
              f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>{_models(keys)}")
    limits = "".join(f"<label>{label}<input name={k} type=number min=0 value='{_e(v[k])}'></label>"
                     for k, label in LIMIT_FIELDS)

    def levels(name: str, values: tuple[str, ...]) -> str:
        return _select(name, [(x, f"{LEVEL_NAMES.get(x, x)} ({x})") for x in values], str(v[name]))

    pol = v["policy"] if v["policy"] in policies else (policies[0] if policies else "")
    return (f"<form method=post action='{action}'>{hidden}"
            + head
            + ("<label>목표 <span class='muted small'>무엇을 이루면 끝인지까지</span>"
               f"<textarea name=goal rows=4 required>{_e(values.get('goal', ''))}</textarea></label>"
               f"<label>제목 <input name=title value='{_e(values.get('title', ''))}'></label>"
               if goal else "")
            + "<h3>라우팅</h3><p class='muted small'>역할마다 위에서부터 첫 경로로 시작하고, 키가 거부되거나 제공자가 "
              "계속 실패하면 같은 역할의 다음 경로로 넘어갑니다. 워커에는 싼 모델을 두면 비용이 줄어듭니다.</p>"
            + routes
            + f"<h3>한도</h3><div class='fields'>{limits}</div>"
            + "<h3>정리 · 실행 환경</h3><div class='fields'>"
            + f"<label>문맥 {levels('context', CONTEXT_LEVELS)}</label>"
            + f"<label>전달 {levels('handoff', HANDOFF_LEVELS)}</label>"
            + f"<label>보관 {levels('retention', RETENTION_LEVELS)}</label>"
            + f"<label>샌드박스 정책 {_select('policy', [(p, p) for p in policies], pol)}</label>"
            + f"<label>effort {_select('effort', [(e, e or '기본값') for e in EFFORTS], str(v['effort']))}</label>"
            + f"</div><div class='actions'><button>{submit}</button>{buttons}"
            + (f"<button class=secondary formaction='{_e(reject)}' formnovalidate>거절</button>" if reject else "")
            + "</div></form>")


def parse_grant(f: dict[str, str], keys: list[KeyInfo]) -> dict[str, Any]:
    """The grant from the form; the keys must be the user's (Team.approve checks the rest)."""
    mine = {k.ref for k in keys}
    routes = []
    for i in range(ROUTE_ROWS):
        key, model = f.get(f"route{i}_key", "").strip(), f.get(f"route{i}_model", "").strip()
        if not key and not model:
            continue
        if key not in mine:
            raise HandbookError(f"경로 {i + 1}: 등록된 키를 고르세요")
        if not model:
            raise HandbookError(f"경로 {i + 1}: 모델을 적으세요")
        roles = [r for r in ROLES if f.get(f"route{i}_{r}")]
        if not roles:
            raise HandbookError(f"경로 {i + 1}: 역할을 하나 이상 고르세요")
        routes.append({"key": key, "model": model, "roles": roles})
    grant: dict[str, Any] = {"routes": routes}
    for k, _ in LIMIT_FIELDS:
        if f.get(k, "").strip():
            grant[k] = f[k].strip()
    for k in ("context", "handoff", "retention", "policy", "effort"):
        if k in f:
            grant[k] = f[k]
    return grant


def runs_page(uid: str, t: Team, keys: list[KeyInfo], policies: list[str], hidden: str, q: Any) -> str:
    runs = t.runs()
    rows = []
    for r in runs[:100]:
        a = r["attrs"]
        phase = a.get("phase", "")
        rows.append(f"<tr><td><a href='/agents/runs/{_e(r['id'])}'><code>{_e(r['id'])}</code></a></td>"
                    f"<td class='wrap'>{_e(a.get('title', ''))}</td>"
                    f"<td><span class='tag {PHASE_TAGS.get(phase, '')}'>{_e(PHASE_NAMES.get(phase, phase))}</span></td>"
                    f"<td>{len(t.agents(r['id']))}</td><td>{_e(_tokens(t.run_usage(r['id'])))}</td>"
                    f"<td>{_e(r['author'] if r['author'] != 'kernel' else r.get('origin', ''))}</td></tr>")
    table = ("<div class='table-wrap'><table><thead><tr><th>실행</th><th>제목</th><th>상태</th><th>에이전트</th>"
             f"<th>토큰</th><th>요청</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
             if rows else "<p class='empty muted'>아직 실행이 없습니다.</p>")
    waiting = sum(1 for r in runs if r["attrs"].get("phase") == "requested")
    return (_head("에이전트 실행", "목표와 한도를 정해 에이전트 팀을 띄웁니다. Claude가 agent_run으로 요청한 실행도 "
                  "여기서 승인해야 시작됩니다.", "/agents/runs", uid)
            + _flash(q)
            + (f"<p class='flash'>승인을 기다리는 요청이 {waiting}건 있습니다.</p>" if waiting else "")
            + f"<section class='card section'><h2>실행 목록 ({len(runs)})</h2>{table}</section>"
            + "<section class='card section' id='new'><h2>새 실행</h2>"
            + grant_form("/agents/runs/new", keys, policies, hidden, goal=True, submit="시작",
                         head="<label>프리셋으로도 저장 <span class='muted small'>이름을 적으면 같은 설정을 프리셋으로 "
                              "남깁니다 (선택)</span><input name=preset pattern='[a-z0-9][a-z0-9._\\-]*' "
                              "placeholder='예: daily-report'></label>")
            + "</section>")


def _tokens(u: dict[str, int]) -> str:
    n = u.get("input", 0) + u.get("output", 0)
    return f"{n:,}" if n else "-"


def _tree(nodes: list[dict[str, Any]]) -> str:
    if not nodes:
        return ""
    items = []
    for n in nodes:
        state = n["status"] or n["state"]
        tag = "ok" if state in ("done", "running") else "bad" if state in ("cancelled", "failed") else "warn"
        items.append(f"<li><b>{_e(n['id'].rsplit(':', 1)[1])}</b> <span class='tag'>{_e(ROLE_NAMES.get(n['role'], n['role']))}"
                     f"</span><span class='tag {tag}'>{_e(state)}</span><span class='muted small'>{_e(n['model'])} · "
                     f"{n['steps']}턴 · {_e(_tokens(n['usage']))} 토큰</span><div class='small'>{_e(n['goal'])}</div>"
                     f"{_tree(n['children'])}</li>")
    return f"<ul class='tree'>{''.join(items)}</ul>"


def run_page(uid: str, t: Team, run: str, keys: list[KeyInfo], policies: list[str], hidden: str, q: Any) -> str:
    from .team import render_note

    r = t.g.node(run)
    a = r["attrs"]
    phase = a.get("phase", "")
    head = (f"<div class='page-head'><h1>{_e(a.get('title') or run)}</h1>"
            f"<p class='muted'><code>{_e(run)}</code> <span class='tag {PHASE_TAGS.get(phase, '')}'>"
            f"{_e(PHASE_NAMES.get(phase, phase))}</span> · 요청 {_e(r.get('origin') or r['author'])}</p>"
            f"{nav('/agents/runs')}</div>")
    out = [head, _flash(q), f"<section class='card section'><h2>목표</h2><p>{_e(r['content'])}</p>"]
    if a.get("error"):
        out.append(f"<p class='flash error'>{_e(a['error'])}</p>")
    out.append("</section>")
    cancel = (f"<form class=inline method=post action='/agents/runs/{_e(run)}/cancel'>{hidden}"
              "<button class=secondary>{label}</button></form>")
    if phase == "requested" and r["state"] == "open":
        sugg = a.get("proposal") or {}
        out.append("<section class='card section'><h2>승인</h2><p class='muted small'>모델이 제안한 값으로 채워져 "
                   "있습니다. 키·모델·한도를 정해 승인하면 러너가 시작합니다.</p>"
                   + (grant_form(f"/agents/runs/{run}/approve", keys, policies, hidden, goal=False, proposal=sugg,
                                 reject=f"/agents/runs/{run}/cancel") if keys
                      else grant_form("", keys, policies, hidden, goal=False)
                      + f"<div class='actions'>{cancel.replace('{label}', '거절')}</div>")
                   + "</section>")
        return "".join(out)
    try:
        grant = t.grant(run)
    except HandbookError:
        grant = None
    if grant:
        routes = "".join(f"<li><b>{_e(x['key'])}</b> {_e(x['model'])} <span class='muted small'>"
                         f"{_e(', '.join(ROLE_NAMES[y] for y in x['roles']))}</span></li>" for x in grant["routes"])
        out.append("<section class='card section'><h2>허가</h2><ol>" + routes + "</ol>"
                   f"<p class='muted small'>동시 {grant['max_agents']} · 총 {grant['max_spawns']} · 깊이 {grant['max_depth']} · "
                   f"턴 {grant['max_steps']} · 토큰 {grant['max_tokens'] or '무제한'} · 문맥 {grant['context']} · "
                   f"보관 {grant['retention']} · 정책 {_e(grant['policy'])}</p></section>")
    usage = t.run_usage(run)
    out.append(f"<section class='card section'><h2>에이전트</h2><p class='muted small'>입력 {usage.get('input', 0):,} · "
               f"출력 {usage.get('output', 0):,} · 캐시 {usage.get('cache_read', 0):,} 토큰. "
               f"<a href='/agents/runs/{_e(run)}'>새로고침</a></p>"
               + (_tree(t.tree(run)) or "<p class='empty muted'>러너가 아직 시작하지 않았습니다.</p>")
               + (f"<div class='actions'>{cancel.replace('{label}', '실행 취소')}</div>" if r["state"] == "open" else "")
               + "</section>")
    res = t.result(run)
    if res:
        notes = t.carried(res["id"])
        out.append(f"<section class='card section'><h2>결과 <span class='tag'>{_e(res['attrs'].get('outcome'))}</span></h2>"
                   f"<pre class='wrap'>{_e(res['content'])}</pre>"
                   + "".join(f"<p class='small'>{_e(render_note(n))}</p>" for n in notes) + "</section>")
    board = t.board(run)
    if board:
        out.append("<section class='card section'><h2>공유된 노트</h2>"
                   + "".join(f"<p class='small'>{_e(render_note(n))}</p>" for n in board[-30:]) + "</section>")
    return "".join(out)


# ── presets and schedules ────────────────────────────────────────────────


def _when(ts: float | None) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "-"


PRESET_NAME = "<label>이름 <span class='muted small'>영문 소문자·숫자·.-_</span><input name=name required " \
              "pattern='[a-z0-9][a-z0-9._\\-]*' value='{v}' {ro}></label>"


def presets_page(uid: str, presets: list[dict[str, Any]], schedules: list[dict[str, Any]], keys: list[KeyInfo],
                 policies: list[str], hidden: str, q: Any) -> str:
    cards = []
    for p in presets:
        a = p["attrs"]
        name = a["name"]
        g = a["grant"]
        routes = ", ".join(f"{r['model']} ({'/'.join(ROLE_NAMES[x] for x in r['roles'])})" for r in g["routes"])
        mine = [s for s in schedules if s["attrs"]["preset"] == name]
        rows = "".join(
            f"<tr><td><code>{_e(s['attrs']['cron'])}</code></td>"
            f"<td><span class='tag {'ok' if s['attrs'].get('enabled') else ''}'>{'켜짐' if s['attrs'].get('enabled') else '꺼짐'}"
            f"</span></td><td>{_when(s['attrs'].get('next_at')) if s['attrs'].get('enabled') else '-'}</td>"
            f"<td>{_when(s['attrs'].get('last_at'))}"
            + (f" <a href='/agents/runs/{_e(s['attrs']['last_run'])}'>실행</a>" if s['attrs'].get('last_run') else "")
            + f"</td><td class='wrap muted small'>{_e(s['attrs'].get('last_note', ''))}</td><td>"
            f"<form class=inline method=post action='/agents/schedules/{_e(s['id'])}/toggle'>{hidden}"
            f"<input type=hidden name=enabled value='{'0' if s['attrs'].get('enabled') else '1'}'>"
            f"<button class=secondary>{'끄기' if s['attrs'].get('enabled') else '켜기'}</button></form> "
            f"<form class=inline method=post action='/agents/schedules/{_e(s['id'])}/delete'>{hidden}"
            f"<button class=secondary>삭제</button></form></td></tr>" for s in mine)
        sched = ((f"<div class='table-wrap'><table><thead><tr><th>cron</th><th>상태</th><th>다음</th><th>마지막</th>"
                  f"<th>메모</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>") if mine else "")
        edit = grant_form(f"/agents/presets/save", keys, policies, hidden, goal=True, proposal=g, submit="저장",
                          values={"goal": p["content"], "title": a["title"]},
                          head=PRESET_NAME.format(v=_e(name), ro="readonly")) if keys else ""
        cards.append(
            f"<div class='item'><div class='item-head'><b>{_e(a['title'])}</b><code>{_e(name)}</code>"
            f"<span class='muted small'>{_e(routes)} · 동시 {g['max_agents']} · 턴 {g['max_steps']}</span></div>"
            f"<p class='small'>{_e(p['content'])}</p>"
            f"<div class='actions'><form class=inline method=post action='/agents/presets/{_e(name)}/run'>{hidden}"
            f"<button>지금 실행</button></form>"
            f"<form class=inline method=post action='/agents/presets/{_e(name)}/schedule'>{hidden}"
            f"<input name=cron required placeholder='0 9 * * mon-fri' class='cron'><button class=secondary>예약 추가</button>"
            f"</form>"
            f"<form class=inline method=post action='/agents/presets/{_e(name)}/delete'>{hidden}"
            f"<button class=secondary>삭제</button></form></div>{sched}"
            f"<details class='panel'><summary>설정 고치기</summary>{edit}</details></div>")
    body = "".join(cards) or "<p class='empty muted'>아직 프리셋이 없습니다. 아래에서 만들거나, 새 실행을 시작할 때 "\
                              "이름을 적어 저장하세요.</p>"
    return (_head("프리셋 · 예약", "자주 하는 실행을 목표와 허가째로 저장해 두고, 한 번에 실행하거나 정해진 때에 저절로 "
                  "실행되게 합니다. 예약은 미리 해 둔 승인입니다: 때가 되면 러너가 이 설정 그대로 실행을 엽니다.",
                  "/agents/presets", uid)
            + _flash(q)
            + f"<section class='card section'><h2>프리셋 ({len(presets)})</h2>"
              "<p class='muted small'>예약은 cron 다섯 칸(분 시 일 월 요일, 서버 시간)입니다. 예: <code>0 9 * * mon-fri</code> "
              "평일 9시, <code>*/30 * * * *</code> 30분마다, <code>@daily</code> 매일 0시. 목표에 <code>{date}</code>, "
              "<code>{time}</code>을 쓰면 실행한 때로 바뀝니다. 앞 실행이 아직 돌고 있으면 그 회차는 건너뜁니다.</p>"
              f"{body}</section>"
            + "<section class='card section'><h2>새 프리셋</h2>"
            + grant_form("/agents/presets/save", keys, policies, hidden, goal=True, submit="저장",
                         head=PRESET_NAME.format(v="", ro=""),
                         buttons="<button class=secondary name=then value=run>저장하고 실행</button>")
            + "</section>")


# ── the workspace's files ────────────────────────────────────────────────


def files_page(uid: str, rel: str, rows: list[tuple[str, str, int]] | None, text: str | None, size: int,
               work: str, q: Any) -> str:
    """A directory listing (`rows`) or a file (`text`, None when it is not text) of the workspace."""
    parts = [x for x in rel.split("/") if x not in ("", ".")]
    crumbs = ["<a href='/agents/files'>/work</a>"] + [
        f"<a href='/agents/files?path={_e('/'.join(parts[:i + 1]))}'>{_e(x)}</a>" for i, x in enumerate(parts)]
    head = (_head("파일", "샌드박스의 <code>/work</code>: 스크립트와 에이전트가 쓰는 작업 공간입니다(읽기 전용으로 "
                  "보여 줍니다). 에이전트 실행은 <code>/work/runs/&lt;실행&gt;</code>에서 일합니다.", "/agents/files", uid)
            + _flash(q) + f"<p class='muted small'>서버의 위치: <code>{_e(work)}</code></p>"
            + f"<section class='card section'><h2>{' / '.join(crumbs)}</h2>")
    if rows is not None:
        base = "/".join(parts)
        items = "".join(
            f"<tr><td class='wrap'><a href='/agents/files?path="
            f"{_e((base + '/' if base else '') + name)}'>{_e(name)}{'/' if k == 'dir' else ''}</a></td>"
            f"<td class='muted small num'>{'' if k == 'dir' else f'{n:,} B'}</td></tr>" for name, k, n in rows)
        return head + (f"<div class='table-wrap'><table><tbody>{items}</tbody></table></div>" if rows
                       else "<p class='empty muted'>비어 있습니다.</p>") + "</section>"
    if text is None:
        return head + f"<p class='muted'>텍스트가 아닌 파일입니다 ({size:,} B).</p></section>"
    return head + f"<p class='muted small'>{size:,} B</p><pre class='wrap'>{_e(text)}</pre></section>"
