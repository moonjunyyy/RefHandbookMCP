// The agents' pages over /agents/api/v1: runs (start one from a preset, follow one), API keys, the
// workspace's files (the presets, each a flow, are flows.ts's). Approving a run the model asked for is the approval page's.

import { act, agents, empty, flashNext, form, go, h, help, link, main, meta, num, pageHead, replace, section, tag, title, values, when } from '/auth/static/site.js';
import type { Child, Json } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { flowProgress, flowView, presetItem } from './flows';
import { Key, providerName, roleName } from './grant';
import { agentTabs } from './tabs';

const PHASE: Record<string, [string, string]> = {
  requested: [n_('승인 대기'), 'warn'], approved: [n_('시작 대기'), ''], running: [n_('실행 중'), 'ok'], done: [n_('완료'), 'ok'],
  cancelled: [n_('취소됨'), 'bad'], failed: [n_('실패'), 'bad'],
};
const phase = (p: string) => tag(PHASE[p] ? t(PHASE[p][0]) : p, PHASE[p]?.[1] ?? '');

// ── runs ────────────────────────────────────────────────────────────────

/** The runs: the presets to start one from (each with an input), a new one, and every run so far. */
export async function runs(): Promise<void> {
  const [keys, list, presets] = await Promise.all([agents.get('/keys') as Promise<Key[]>, agents.get('/runs') as Promise<Json[]>,
    agents.get('/presets') as Promise<Json[]>]);
  const waiting = list.filter(r => r.phase === 'requested').length;
  const mine = new Set(keys.map(k => k.ref));
  replace(main(),
    pageHead(t('에이전트'), agentTabs()),
    !keys.length && h('p', { class: 'flash error' }, t('실행하려면 먼저 API 키를 등록하세요.'), ' ', link('/agents/keys', t('API 키 등록'))),
    waiting > 0 && h('p', { class: 'flash' }, t('승인을 기다리는 요청이 {n}건 있습니다.', { n: waiting }), ' ', h('a', { href: '/approvals' }, t('승인 화면으로'))),
    section(t('새 실행'),
      h('div', { class: 'actions' },
        link('/agents/presets/new', t('새로 만들어 실행')),
        link('/agents/presets', t('프리셋 관리'))),
      presets.length ? presets.map(p => presetItem(p, mine))
        : empty(t('저장한 프리셋이 없습니다. 새로 만들어 실행하고, 이름을 적어 두면 여기서 바로 다시 씁니다.'))),
    section(t('실행 ({n})', { n: list.length }), list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, [t('실행'), t('상태'), t('에이전트'), t('토큰'), t('요청'), t('시작'), ''].map(x => h('th', null, x)))),
      h('tbody', null, list.map(r => h('tr', null,
        h('td', { class: 'wrap' }, link(`/agents/runs/${r.id}`, r.title || r.id),
          r.preset && [' · ', link(`/agents/presets/${r.preset}`, h('span', { class: 'muted small' }, r.preset))]),
        h('td', null, phase(r.phase)), h('td', { class: 'num' }, String(r.agents)), h('td', { class: 'num' }, num(r.tokens)),
        h('td', null, r.requested_by === 'model' ? 'Claude' : t('나')), h('td', null, when(r.requested)),
        h('td', null, r.phase === 'requested' ? h('a', { href: `/approvals/runs/${r.id}` }, t('승인하기'))
          : link(`/agents/presets/new?from=${encodeURIComponent(r.id)}`, t('다시')))))))) : empty(t('아직 실행이 없습니다.'))));
}

function tree(nodes: Json[]): Child {
  if (!nodes.length) return null;
  return h('ul', { class: 'tree' }, nodes.map(n => {
    const st = n.status || n.state;
    return h('li', null, h('b', null, n.id.split(':').pop()), ' ', tag(roleName(n.role)), ' ',
      tag(st, ['done', 'running'].includes(st) ? 'ok' : ['cancelled', 'failed'].includes(st) ? 'bad' : 'warn'),
      h('span', { class: 'muted small' }, ` ${n.model} · `, t('{n}턴', { n: n.steps }), ' · ', t('{n} 토큰', { n: num((n.usage.input ?? 0) + (n.usage.output ?? 0)) })),
      h('div', { class: 'small' }, n.goal), tree(n.children));
  }));
}

function flowSection(r: Json): HTMLElement {
  const { states, taken, path } = flowProgress(r);
  const end = r.flow_end && r.flow_end !== 'end' ? r.flow_end : '';
  return section(t('순서도'),
    h('p', { class: 'small' }, h('b', null, t('지나온 길:')), ' ', path.length ? path.join(' → ') : t('아직 시작하지 않았습니다.')),
    end && h('p', { class: 'flash error' }, t('순서도가 중간에 멈췄습니다: {reason}', { reason: end })),
    flowView(r.flow, states, taken),
    r.preset && h('p', { class: 'small' }, link(`/agents/presets/${r.preset}`, t('이 프리셋 열기'))));
}

let poll = 0;

export async function run(id: string): Promise<void> {
  window.clearTimeout(poll);
  const r = await agents.get(`/runs/${encodeURIComponent(id)}`);
  const g = r.grant;
  replace(main(),
    pageHead(r.title || r.id, agentTabs()), meta(h('code', null, r.id), ' ', phase(r.phase),
      ' · ', t('요청 {who}', { who: r.requested_by === 'model' ? 'Claude' : t('나') })),
    r.approve_url && h('p', { class: 'flash' }, t('Claude가 요청한 실행입니다. 승인 화면에서 키·모델·한도를 정해 승인하면 시작합니다.'), ' ',
      h('a', { href: r.approve_url }, t('승인 화면으로'))),
    r.error && h('p', { class: 'flash error' }, r.error),
    r.flow ? section(t('입력'), r.input ? h('p', null, r.input) : empty(t('없음 (블럭의 명령만으로 실행)')))
      : section(t('목표'), h('p', null, r.goal)),
    g && section(t('허가'),
      h('ol', null, g.routes.map((x: Json) => h('li', null, h('b', null, x.key), ` ${x.model} `,
        h('span', { class: 'muted small' }, x.roles.map(roleName).join(', '))))),
      meta(t('동시 {agents} · 총 {spawns} · 깊이 {depth} · 턴 {steps} · 토큰 {tokens} · 문맥 {context} · 보관 {retention} · 정책 {policy}',
        { agents: g.max_agents, spawns: g.max_spawns, depth: g.max_depth, steps: g.max_steps, tokens: g.max_tokens || t('무제한'),
          context: g.context, retention: g.retention, policy: g.policy }))),
    r.flow && flowSection(r),
    section(t('에이전트'),
      meta(t('입력 {input} · 출력 {output} · 캐시 {cache} 토큰',
        { input: num(r.usage.input), output: num(r.usage.output), cache: num(r.usage.cache_read) })),
      tree(r.tree) ?? empty(r.phase === 'requested' ? t('승인되면 시작합니다.') : t('아직 시작하지 않았습니다.')),
      r.state === 'open' && h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (await act(e.target as HTMLButtonElement, () => agents.post(`/runs/${r.id}/cancel`))) void run(id);
      } }, t('실행 취소')))),
    section([t('다시 쓰기'), help(t('이 실행의 순서도·입력·한도를 그대로 씁니다. 처음 순서도가 없던 실행은 블럭 하나(팀)로 엽니다.'))],
      h('div', { class: 'actions' },
        link(`/agents/presets/new?from=${encodeURIComponent(r.id)}`, t('열어서 고치고 실행')),
        h('button', { class: 'secondary', disabled: !r.grant, onclick: async (e: Event) => {
          const rc = r.recipe;
          const again = await act(e.target as HTMLButtonElement,
            () => agents.post('/runs', { goal: rc.input, title: rc.title, grant: rc.grant, flow: rc.flow }));
          if (again) { flashNext('ok', t('같은 설정으로 다시 시작했습니다.')); go(`/agents/runs/${again.id}`); }
        } }, t('바로 다시 실행')),
        form({ class: 'inline' }, async (f, b) => {
          const rc = r.recipe;
          const name = String(values(f).name);
          const p = await act(b, () => agents.put(`/presets/${encodeURIComponent(name)}`,
            { goal: rc.input, title: rc.title, grant: rc.grant, flow: rc.flow }));
          if (p) { flashNext('ok', t('프리셋 {name}(으)로 저장했습니다. 여기서 예약할 수 있습니다.', { name })); go(`/agents/presets/${name}`); }
        }, h('input', { name: 'name', required: true, pattern: '[a-z0-9][a-z0-9._\\-]*', placeholder: t('프리셋 이름') }),
          h('button', { class: 'secondary' }, t('프리셋으로 저장'))))),
    r.result && section(h('span', null, t('결과'), ' ', tag(r.result.outcome)), h('pre', { class: 'wrap' }, r.result.text),
      r.result.notes.map((n: Json) => h('p', { class: 'small' }, `[${n.id}] ${n.text}`))),
    r.board.length > 0 && section(t('공유된 노트'), r.board.map((n: Json) =>
      h('p', { class: 'small' }, tag(n.state, n.state === 'verified' ? 'ok' : ''), ` ${n.text}`))));
  if (r.state === 'open' && location.pathname === `/agents/runs/${id}`) {
    poll = window.setTimeout(() => { if (location.pathname === `/agents/runs/${id}`) void run(id); }, 5000);
  }
}

// ── keys ────────────────────────────────────────────────────────────────

const FORMAT: Record<string, string> = {
  anthropic: 'Anthropic Messages', openai: 'OpenAI Responses',
  'openai-chat': 'OpenAI Chat Completions (vLLM, Ollama, OpenRouter …)', gemini: 'Gemini generateContent',
};

export async function keys(): Promise<void> {
  const [list, opts] = await Promise.all([agents.get('/keys') as Promise<Json[]>, agents.get('/options')]);
  const custom = h('div', { class: 'cols hidden' },
    h('label', null, t('형식'), h('select', { name: 'format' }, (opts.formats as string[]).map(f =>
      h('option', { value: f, selected: f === 'openai-chat' }, FORMAT[f] ?? f)))),
    h('label', null, 'Base URL ', h('span', { class: 'muted small' }, t('버전 경로까지 (예: https://openrouter.ai/api/v1)')),
      h('input', { name: 'base_url', placeholder: 'https://…/v1' })));
  const provider = h('select', { name: 'provider', onchange: () => custom.classList.toggle('hidden', provider.value !== 'custom') },
    (opts.providers as string[]).map(p => h('option', { value: p }, p === 'custom' ? t('Custom (표준 형식 서버)') : providerName(p))));
  replace(main(),
    pageHead(t('API 키'), agentTabs()),
    section(t('등록된 키 ({n})', { n: list.length }), list.length ? list.map(k => h('div', { class: 'item' },
      h('div', { class: 'item-head' }, h('b', null, k.ref), tag(providerName(k.provider)), h('code', null, k.fingerprint),
        tag(k.status, k.status === 'ok' ? 'ok' : k.status === 'unchecked' ? 'warn' : 'bad'),
        h('span', { class: 'muted small' }, `${FORMAT[k.format] ?? k.format}${k.base_url ? ' · ' + k.base_url : ''} · ${t('마지막 사용 {when}', { when: when(k.last_used) })}`)),
      k.used_by.length > 0 && h('p', { class: 'small' }, t('쓰는 프리셋:'), ' ',
        k.used_by.map((n: string, i: number) => [i ? ', ' : '', link(`/agents/presets/${n}`, n)])),
      h('details', null, h('summary', null, k.models_listed ? t('모델 {n}개', { n: k.models.length }) : t('모델 {n}개 (제공자 목록 없음: 추천 목록)', { n: k.models.length })),
        h('p', { class: 'small' }, k.models.map((m: string) => h('code', null, m, ' ')))),
      h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        const users = k.used_by.length ? '\n' + t('이 키를 쓰는 프리셋({names})은 블럭의 키를 다시 고를 때까지 실행되지 않습니다.', { names: k.used_by.join(', ') }) : '';
        if (!confirm(t('{key} 키를 지울까요?', { key: k.ref }) + users)) return;
        if (await act(e.target as HTMLButtonElement, () => agents.del(`/keys/${k.provider}/${k.label}`))) void keys();
      } }, t('삭제'))))) : empty(t('등록한 키가 없습니다.'))),
    section([t('키 등록'), help(t('등록할 때 제공자의 모델 목록을 한 번 불러와 키를 확인합니다. 그 목록이 이 키의 모델 선택지가 됩니다.'))],
      form({ autocomplete: 'off' }, async (f, b) => {
        const k = await act(b, () => agents.post('/keys', values(f)));
        if (k) void keys();
      },
        h('div', { class: 'cols' }, h('label', null, t('제공자'), provider),
          h('label', null, t('이름'), ' ', h('span', { class: 'muted small' }, t('영문·숫자·.-_ (예: main, work)')),
            h('input', { name: 'label', required: true, pattern: '[A-Za-z0-9._\\-]{1,32}', value: 'main' }))),
        h('label', null, t('API 키'), ' ', h('span', { class: 'muted small' }, t('Custom 서버가 인증을 받지 않으면 비워 두세요')),
          h('input', { name: 'secret', type: 'password', autocomplete: 'new-password' })),
        custom,
        h('div', { class: 'actions' }, h('button', null, t('확인하고 등록'))))));
}

// ── files ───────────────────────────────────────────────────────────────

export async function files(): Promise<void> {
  const path = new URLSearchParams(location.search).get('path') ?? '';
  const d = await agents.get(`/files?path=${encodeURIComponent(path)}`);
  const parts = path.split('/').filter(Boolean);
  const crumbs = [link('/agents/files', '/work'), ...parts.map((p, i) =>
    [' / ', link(`/agents/files?path=${encodeURIComponent(parts.slice(0, i + 1).join('/'))}`, p)])];
  title(t('파일'));
  replace(main(),
    pageHead(t('파일'), agentTabs()), meta(h('code', null, '/work'), help([t('샌드박스에서 스크립트와 에이전트가 쓰는 작업 공간입니다(읽기 전용).'), ' ',
      t('에이전트 실행은 각자 이 폴더에서 일합니다:'), ' ', h('code', null, '/work/runs/<run>')])),
    section(crumbs, d.kind === 'dir'
      ? (d.entries.length ? h('div', { class: 'table-wrap' }, h('table', null, h('tbody', null, d.entries.map((e: Json) => h('tr', null,
          h('td', { class: 'wrap' }, link(`/agents/files?path=${encodeURIComponent((path ? path + '/' : '') + e.name)}`,
            e.name + (e.kind === 'dir' ? '/' : ''))),
          h('td', { class: 'muted small num' }, e.kind === 'dir' ? '' : `${num(e.size)} B`))))))
        : empty(t('비어 있습니다.')))
      : d.text === null ? empty(t('텍스트가 아닌 파일입니다 ({size} B).', { size: num(d.size) }))
        : [meta(`${num(d.size)} B`), h('pre', { class: 'wrap' }, d.text)]));
}
