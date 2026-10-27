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

from portal.i18n import N_, t

from ..store import HandbookError
from .keys import FORMATS, PROVIDERS, KeyInfo
from .team import CONTEXT_LEVELS, DEFAULT_GRANT, EFFORTS, HANDOFF_LEVELS, MAX_ROUTES, RETENTION_LEVELS, ROLES, Team

ROUTE_ROWS = 4
PROVIDER_NAMES = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Gemini (Google)",
                  "custom": N_("Custom (표준 형식 서버)")}
FORMAT_NAMES = {"anthropic": "Anthropic Messages", "openai": "OpenAI Responses",
                "openai-chat": "OpenAI Chat Completions (vLLM, Ollama, OpenRouter …)", "gemini": "Gemini generateContent"}
ROLE_NAMES = {"lead": N_("리드"), "worker": N_("워커"), "verifier": N_("검증")}
PHASE_TAGS = {"requested": "warn", "approved": "", "running": "ok", "done": "ok", "cancelled": "bad", "failed": "bad"}
PHASE_NAMES = {"requested": N_("승인 대기"), "approved": N_("시작 대기"), "running": N_("실행 중"), "done": N_("완료"),
               "cancelled": N_("취소됨"), "failed": N_("실패")}
LIMIT_FIELDS = (("max_agents", N_("동시 에이전트")), ("max_spawns", N_("총 에이전트 수")), ("max_depth", N_("최대 깊이")),
                ("max_steps", N_("에이전트당 턴")), ("max_tokens", N_("토큰 한도 (0: 없음)")))
LEVEL_NAMES = {"full": N_("전체"), "trim": N_("오래된 출력 정리"), "digest": N_("주기적 요약"), "minimal": N_("최소"),
               "refs": N_("id만"), "all": N_("모두 보관"), "verified": N_("검증된 것만"), "exits": N_("결과만"),
               "purge": N_("결과 외 삭제")}


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
    links = (("/approvals", t("승인 · 샌드박스")), ("/agents/", t("에이전트 실행")), ("/agents/presets", t("프리셋")),
             ("/agents/files", t("파일")), ("/agents/keys", t("API 키")))
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
               proposal: dict[str, Any] | None = None, submit: str = N_("승인하고 시작"), reject: str = "",
               values: dict[str, str] | None = None, head: str = "", buttons: str = "",
               flow: dict[str, Any] | None = None) -> str:
    """The grant form. `reject` is an action the same form can post to instead (its token rides along);
    `values` fill the goal and title, `head` goes first (a preset's name), `buttons` after the submit.
    With a `flow` (a run asked for from a preset), its blocks are the routing: shown, not chosen."""
    proposal = proposal or {}
    values = values or {}
    if not keys:
        return (f"<p class='flash error'>{t('먼저 API 키를 등록하세요.')} "
                f"<a href='/agents/keys'>{t('API 키')}</a></p>")
    v = {**DEFAULT_GRANT, **{k: proposal[k] for k in DEFAULT_GRANT if k in proposal}}
    pre = _routes_prefill(keys, proposal)
    key_opts = [("", "—")] + [(k.ref, f"{k.ref} ({t(PROVIDER_NAMES[k.provider]).split(' ')[0]})") for k in keys]
    rows = []
    for i in range(min(MAX_ROUTES, max(ROUTE_ROWS, len(pre) + 2))):  # no script here: the rows are drawn
        r = pre[i] if i < len(pre) else {"key": "", "model": "", "roles": []}
        checks = "".join(f"<label class='check'><input type=checkbox name=route{i}_{role}"
                         f"{' checked' if role in r['roles'] else ''}> {t(ROLE_NAMES[role])}</label>" for role in ROLES)
        rows.append(f"<tr><td>{i + 1}</td><td>{_select(f'route{i}_key', key_opts, r['key'])}</td>"
                    f"<td><input name=route{i}_model list='{'models-' + _e(r['key']) if r['key'] else 'models'}' "
                    f"value='{_e(r['model'])}' placeholder='{t('모델')}'></td>"
                    f"<td class='roles'>{checks}</td></tr>")
    heads = "".join(f"<th>{t(h)}</th>" for h in (N_("순서"), N_("키"), N_("모델"), N_("역할")))
    routes = (f"<div class='table-wrap'><table class='routes'><thead><tr>{heads}"
              f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>{_models(keys)}")
    limits = "".join(f"<label>{t(label)}<input name={k} type=number min=0 step=any value='{_e(v[k])}'></label>"
                     for k, label in LIMIT_FIELDS)

    def levels(name: str, values: tuple[str, ...]) -> str:
        return _select(name, [(x, f"{t(LEVEL_NAMES.get(x, x))} ({x})") for x in values], str(v[name]))

    pol = v["policy"] if v["policy"] in policies else (policies[0] if policies else "")
    return (f"<form method=post action='{action}'>{hidden}"
            + head
            + (f"<label>{t('목표')} <span class='muted small'>{t('무엇을 이루면 끝인지까지')}</span>"
               f"<textarea name=goal rows=4 required>{_e(values.get('goal', ''))}</textarea></label>"
               f"<label>{t('제목')} <input name=title value='{_e(values.get('title', ''))}'></label>"
               if goal else "")
            + (_blocks(flow) if flow else
               f"<h3>{t('라우팅')}</h3><p class='muted small'>"
               f"{t('역할마다 위에서부터 첫 경로로 시작하고, 키가 거부되거나 제공자가 계속 실패하면 같은 역할의 다음 경로로 넘어갑니다. 워커에는 싼 모델을 두면 비용이 줄어듭니다.')}</p>"
               + routes)
            + f"<h3>{t('한도')}</h3><div class='fields'>{limits}</div>"
            + f"<h3>{t('정리 · 실행 환경')}</h3><div class='fields'>"
            + f"<label>{t('문맥')} {levels('context', CONTEXT_LEVELS)}</label>"
            + f"<label>{t('전달')} {levels('handoff', HANDOFF_LEVELS)}</label>"
            + f"<label>{t('보관')} {levels('retention', RETENTION_LEVELS)}</label>"
            + f"<label>{t('샌드박스 정책')} {_select('policy', [(p, p) for p in policies], pol)}</label>"
            + f"<label>effort {_select('effort', [(e, e or t('기본값')) for e in EFFORTS], str(v['effort']))}</label>"
            + f"</div><div class='actions'><button>{t(submit)}</button>{buttons}"
            + (f"<button class=secondary formaction='{_e(reject)}' formnovalidate>{t('거절')}</button>" if reject else "")
            + "</div></form>")


def _blocks(flow: dict[str, Any]) -> str:
    """A preset's flow on the approval page: each block's key, model and command, in the order drawn."""
    items = "".join(f"<li><b>{_e(s['title'])}</b> <span class='muted small'>{_e(s['key'])} · {_e(s['model'])}"
                    f"{' · ' + t('팀') if s.get('team') else ''}</span><div class='small'>{_e(s['command'][:300])}</div></li>"
                    for s in flow.get("steps", []))
    return (f"<h3>{t('순서도')}</h3><p class='muted small'>"
            f"{t('프리셋의 순서도대로 실행합니다. 블럭의 키·모델은 프리셋에서 고칩니다.')} "
            f"<a href='/agents/presets'>{t('프리셋 열기')}</a></p><ol>{items}</ol>")


def parse_grant(f: dict[str, str], keys: list[KeyInfo]) -> dict[str, Any]:
    """The grant from the form; the keys must be the user's (Team.approve checks the rest)."""
    mine = {k.ref for k in keys}
    routes = []
    for i in range(MAX_ROUTES):
        key, model = f.get(f"route{i}_key", "").strip(), f.get(f"route{i}_model", "").strip()
        if not key and not model:
            continue
        if key not in mine:
            raise HandbookError(t("경로 {n}: 등록된 키를 고르세요", n=i + 1))
        if not model:
            raise HandbookError(t("경로 {n}: 모델을 적으세요", n=i + 1))
        roles = [r for r in ROLES if f.get(f"route{i}_{r}")]
        if not roles:
            raise HandbookError(t("경로 {n}: 역할을 하나 이상 고르세요", n=i + 1))
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
        items.append(f"<li><b>{_e(n['id'].rsplit(':', 1)[1])}</b> <span class='tag'>{_e(t(ROLE_NAMES.get(n['role'], n['role'])))}"
                     f"</span><span class='tag {tag}'>{_e(state)}</span><span class='muted small'>{_e(n['model'])} · "
                     f"{t('{n}턴', n=n['steps'])} · {t('{n} 토큰', n=_e(_tokens(n['usage'])))}</span><div class='small'>{_e(n['goal'])}</div>"
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


def run_page(uid: str, team: Team, run: str, keys: list[KeyInfo], policies: list[str], hidden: str, q: Any,
             draft: dict[str, Any] | None = None) -> str:
    """A run the model asked for: its grant form (prefilled from what it suggested, or from `draft`:
    what the user filled in and was refused)."""
    from .team import render_note

    r = team.g.node(run)
    a = r["attrs"]
    phase = a.get("phase", "")
    head = (f"<div class='page-head'><h1>{_e(a.get('title') or run)}</h1>"
            f"<p class='muted'><code>{_e(run)}</code> <span class='tag {PHASE_TAGS.get(phase, '')}'>"
            f"{_e(t(PHASE_NAMES.get(phase, phase)))}</span> · {t('요청 {who}', who=_e(r.get('origin') or r['author']))}</p>"
            f"{nav('/approvals')}</div>")
    out = [head, _flash(q), f"<section class='card section'><h2>{t('목표')}</h2><p>{_e(r['content'])}</p>"]
    if a.get("error"):
        out.append(f"<p class='flash error'>{_e(a['error'])}</p>")
    out.append("</section>")
    cancel = (f"<form class=inline method=post action='/approvals/runs/{_e(run)}/reject'>{hidden}"
              "<button class=secondary>{label}</button></form>")
    if phase == "requested" and r["state"] == "open":
        sugg = draft if draft is not None else (a.get("proposal") or {})
        out.append(f"<section class='card section'><h2>{t('실행 승인')}</h2><p class='muted small'>"
                   f"{t('모델이 제안한 값으로 채워져 있습니다. 키·모델·한도를 정해 승인하면 시작합니다.')}</p>"
                   + (grant_form(f"/approvals/runs/{run}/approve", keys, policies, hidden, goal=False, proposal=sugg,
                                 reject=f"/approvals/runs/{run}/reject", flow=a.get("flow")) if keys
                      else grant_form("", keys, policies, hidden, goal=False)
                      + f"<div class='actions'>{cancel.replace('{label}', t('거절'))}</div>")
                   + "</section>")
        return "".join(out)
    try:
        grant = team.grant(run)
    except HandbookError:
        grant = None
    if grant:
        routes = "".join(f"<li><b>{_e(x['key'])}</b> {_e(x['model'])} <span class='muted small'>"
                         f"{_e(', '.join(t(ROLE_NAMES[y]) for y in x['roles']))}</span></li>" for x in grant["routes"])
        said = t("동시 {agents} · 총 {spawns} · 깊이 {depth} · 턴 {steps} · 토큰 {tokens} · 문맥 {context} · 보관 {retention} · 정책 {policy}",
                 agents=grant["max_agents"], spawns=grant["max_spawns"], depth=grant["max_depth"],
                 steps=grant["max_steps"], tokens=grant["max_tokens"] or t("무제한"), context=grant["context"],
                 retention=grant["retention"], policy=grant["policy"])
        out.append(f"<section class='card section'><h2>{t('허가')}</h2><ol>" + routes + "</ol>"
                   f"<p class='muted small'>{_e(said)}</p></section>")
    usage = team.run_usage(run)
    used = t("입력 {input} · 출력 {output} · 캐시 {cache} 토큰.", input=f"{usage.get('input', 0):,}",
             output=f"{usage.get('output', 0):,}", cache=f"{usage.get('cache_read', 0):,}")
    out.append(f"<section class='card section'><h2>{t('에이전트')}</h2><p class='muted small'>{used} "
               f"<a href='/agents/runs/{_e(run)}'>{t('새로고침')}</a></p>"
               + (_tree(team.tree(run)) or f"<p class='empty muted'>{t('아직 시작하지 않았습니다.')}</p>")
               + (f"<div class='actions'>{cancel.replace('{label}', t('실행 취소'))}</div>" if r["state"] == "open" else "")
               + "</section>")
    res = team.result(run)
    if res:
        notes = team.carried(res["id"])
        out.append(f"<section class='card section'><h2>{t('결과')} <span class='tag'>{_e(res['attrs'].get('outcome'))}</span></h2>"
                   f"<pre class='wrap'>{_e(res['content'])}</pre>"
                   + "".join(f"<p class='small'>{_e(render_note(n))}</p>" for n in notes) + "</section>")
    board = team.board(run)
    if board:
        out.append(f"<section class='card section'><h2>{t('공유된 노트')}</h2>"
                   + "".join(f"<p class='small'>{_e(render_note(n))}</p>" for n in board[-30:]) + "</section>")
    return "".join(out)


