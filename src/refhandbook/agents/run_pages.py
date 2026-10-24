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
from .team import CONTEXT_LEVELS, DEFAULT_GRANT, EFFORTS, HANDOFF_LEVELS, MAX_ROUTES, RETENTION_LEVELS, ROLES, Team

ROUTE_ROWS = 4
PROVIDER_NAMES = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Gemini (Google)",
                  "custom": "Custom (표준 형식 서버)"}
FORMAT_NAMES = {"anthropic": "Anthropic Messages", "openai": "OpenAI Responses",
                "openai-chat": "OpenAI Chat Completions (vLLM, Ollama, OpenRouter …)", "gemini": "Gemini generateContent"}
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
    links = (("/approvals", "승인 · 샌드박스"), ("/agents/", "에이전트 실행"), ("/agents/presets", "프리셋 · 예약"),
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


# ── runs ─────────────────────────────────────────────────────────────────


def _models(keys: list[KeyInfo]) -> str:
    """A list of models per key (a row's model field offers its key's), and one of them all, each
    labelled with its key, for a row with no key yet."""
    out = [f"<datalist id='models-{_e(k.ref)}'>" + "".join(f"<option value='{_e(m)}'>" for m in k.offered)
           + "</datalist>" for k in keys]
    out.append("<datalist id='models'>" + "".join(f"<option value='{_e(m)}' label='{_e(k.ref)}'>"
                                                  for k in keys for m in k.offered) + "</datalist>")
    return "".join(out)


def _routes_prefill(keys: list[KeyInfo], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """The routes of a grant (a preset's), or those suggested by the requester (roles → model), else one
    route for every role on the first key."""
    if not keys:
        return []
    if isinstance(proposal.get("routes"), list) and proposal["routes"]:
        return [dict(r) for r in proposal["routes"]][:MAX_ROUTES]
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
        model = (k.offered or [""])[0]
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
    for i in range(min(MAX_ROUTES, max(ROUTE_ROWS, len(pre) + 2))):  # no script here: the rows are drawn
        r = pre[i] if i < len(pre) else {"key": "", "model": "", "roles": []}
        checks = "".join(f"<label class='check'><input type=checkbox name=route{i}_{role}"
                         f"{' checked' if role in r['roles'] else ''}> {ROLE_NAMES[role]}</label>" for role in ROLES)
        rows.append(f"<tr><td>{i + 1}</td><td>{_select(f'route{i}_key', key_opts, r['key'])}</td>"
                    f"<td><input name=route{i}_model list='{'models-' + _e(r['key']) if r['key'] else 'models'}' "
                    f"value='{_e(r['model'])}' placeholder='모델'></td>"
                    f"<td class='roles'>{checks}</td></tr>")
    routes = ("<div class='table-wrap'><table class='routes'><thead><tr><th>순서</th><th>키</th><th>모델</th><th>역할</th>"
              f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>{_models(keys)}")
    limits = "".join(f"<label>{label}<input name={k} type=number min=0 step=any value='{_e(v[k])}'></label>"
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
    for i in range(MAX_ROUTES):
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


def draft_grant(f: dict[str, str]) -> dict[str, Any]:
    """A refused grant form read back as it was filled in (no checks: it is only shown again)."""
    routes = []
    for i in range(MAX_ROUTES):
        key, model = f.get(f"route{i}_key", ""), f.get(f"route{i}_model", "")
        if key or model:
            routes.append({"key": key, "model": model, "roles": [r for r in ROLES if f.get(f"route{i}_{r}")]})
    out: dict[str, Any] = {"routes": routes}
    for k, _ in LIMIT_FIELDS:
        if k in f:
            out[k] = f[k]
    for k in ("context", "handoff", "retention", "policy", "effort"):
        if k in f:
            out[k] = f[k]
    return out


def run_page(uid: str, t: Team, run: str, keys: list[KeyInfo], policies: list[str], hidden: str, q: Any,
             draft: dict[str, Any] | None = None) -> str:
    """A run the model asked for: its grant form (prefilled from what it suggested, or from `draft`:
    what the user filled in and was refused)."""
    from .team import render_note

    r = t.g.node(run)
    a = r["attrs"]
    phase = a.get("phase", "")
    head = (f"<div class='page-head'><h1>{_e(a.get('title') or run)}</h1>"
            f"<p class='muted'><code>{_e(run)}</code> <span class='tag {PHASE_TAGS.get(phase, '')}'>"
            f"{_e(PHASE_NAMES.get(phase, phase))}</span> · 요청 {_e(r.get('origin') or r['author'])}</p>"
            f"{nav('/approvals')}</div>")
    out = [head, _flash(q), f"<section class='card section'><h2>목표</h2><p>{_e(r['content'])}</p>"]
    if a.get("error"):
        out.append(f"<p class='flash error'>{_e(a['error'])}</p>")
    out.append("</section>")
    cancel = (f"<form class=inline method=post action='/approvals/runs/{_e(run)}/reject'>{hidden}"
              "<button class=secondary>{label}</button></form>")
    if phase == "requested" and r["state"] == "open":
        sugg = draft if draft is not None else (a.get("proposal") or {})
        out.append("<section class='card section'><h2>승인</h2><p class='muted small'>모델이 제안한 값으로 채워져 "
                   "있습니다. 키·모델·한도를 정해 승인하면 시작합니다.</p>"
                   + (grant_form(f"/approvals/runs/{run}/approve", keys, policies, hidden, goal=False, proposal=sugg,
                                 reject=f"/approvals/runs/{run}/reject") if keys
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
               + (_tree(t.tree(run)) or "<p class='empty muted'>아직 시작하지 않았습니다.</p>")
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


