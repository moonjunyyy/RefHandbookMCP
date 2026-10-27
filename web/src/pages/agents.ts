// The agents' pages over /agents/api/v1: runs (start one from a preset, follow one), API keys, the
// workspace's files (the presets, each a flow, are flows.ts's). Approving a run the model asked for is the approval page's.

import { agents, Json } from '../lib/api';
import { Child, h, replace, values } from '../lib/dom';
import { act, buttonLink, empty, flashNext, form, go, link, main, num, pageHead, section, tag, title, when } from '../lib/ui';
import { flowProgress, flowView, presetItem } from './flows';
import { Key, providerName, roleName } from './grant';
import { AGENT_TABS as TABS } from './tabs';

const PHASE: Record<string, [string, string]> = {
  requested: ['승인 대기', 'warn'], approved: ['시작 대기', ''], running: ['실행 중', 'ok'], done: ['완료', 'ok'],
  cancelled: ['취소됨', 'bad'], failed: ['실패', 'bad'],
};
const phase = (p: string) => tag(PHASE[p]?.[0] ?? p, PHASE[p]?.[1] ?? '');

// ── runs ────────────────────────────────────────────────────────────────

/** The runs: the presets to start one from (each with an input), a new one, and every run so far. */
export async function runs(): Promise<void> {
  const [keys, list, presets] = await Promise.all([agents.get('/keys') as Promise<Key[]>, agents.get('/runs') as Promise<Json[]>,
    agents.get('/presets') as Promise<Json[]>]);
  const waiting = list.filter(r => r.phase === 'requested').length;
  const mine = new Set(keys.map(k => k.ref));
  replace(main(),
    pageHead('에이전트', '프리셋을 골라 실행하거나 새로 만들어 실행합니다. 지난 실행은 그 설정 그대로 다시 열 수 있습니다. ' +
      'Claude가 요청한 실행은 승인 화면에서 승인해야 시작됩니다.', TABS),
    !keys.length && h('p', { class: 'flash error' }, '실행하려면 먼저 ', link('/agents/keys', 'API 키'), '를 등록하세요.'),
    waiting > 0 && h('p', { class: 'flash' }, `승인을 기다리는 요청이 ${waiting}건 있습니다. `, h('a', { href: '/approvals' }, '승인 화면으로')),
    section('새 실행',
      h('div', { class: 'actions' },
        buttonLink('/agents/presets/new', '새로 만들어 실행'),
        buttonLink('/agents/presets', '프리셋 관리', true)),
      presets.length ? presets.map(p => presetItem(p, mine))
        : empty('저장한 프리셋이 없습니다. 새로 만들어 실행하고, 이름을 적어 두면 여기서 바로 다시 씁니다.')),
    section(`실행 (${list.length})`, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['실행', '상태', '에이전트', '토큰', '요청', '시작', ''].map(t => h('th', null, t)))),
      h('tbody', null, list.map(r => h('tr', null,
        h('td', { class: 'wrap' }, link(`/agents/runs/${r.id}`, r.title || r.id),
          r.preset && [' · ', link(`/agents/presets/${r.preset}`, h('span', { class: 'muted small' }, r.preset))]),
        h('td', null, phase(r.phase)), h('td', { class: 'num' }, String(r.agents)), h('td', { class: 'num' }, num(r.tokens)),
        h('td', null, r.requested_by === 'model' ? 'Claude' : '나'), h('td', null, when(r.requested)),
        h('td', null, r.phase === 'requested' ? h('a', { href: `/approvals/runs/${r.id}` }, '승인')
          : link(`/agents/presets/new?from=${encodeURIComponent(r.id)}`, '다시'))))))) : empty('아직 실행이 없습니다.')));
}

function tree(nodes: Json[]): Child {
  if (!nodes.length) return null;
  return h('ul', { class: 'tree' }, nodes.map(n => {
    const st = n.status || n.state;
    return h('li', null, h('b', null, n.id.split(':').pop()), ' ', tag(roleName(n.role)), ' ',
      tag(st, ['done', 'running'].includes(st) ? 'ok' : ['cancelled', 'failed'].includes(st) ? 'bad' : 'warn'),
      h('span', { class: 'muted small' }, ` ${n.model} · ${n.steps}턴 · ${num((n.usage.input ?? 0) + (n.usage.output ?? 0))} 토큰`),
      h('div', { class: 'small' }, n.goal), tree(n.children));
  }));
}

function flowSection(r: Json): HTMLElement {
  const { states, taken, path } = flowProgress(r);
  const end = r.flow_end && r.flow_end !== 'end' ? r.flow_end : '';
  return section('순서도',
    h('p', { class: 'small' }, h('b', null, '지나온 길: '), path.length ? path.join(' → ') : '아직 시작하지 않았습니다.'),
    end && h('p', { class: 'flash error' }, `순서도가 중간에 멈췄습니다: ${end}`),
    flowView(r.flow, states, taken),
    r.preset && h('p', { class: 'muted small' }, link(`/agents/presets/${r.preset}`, '이 프리셋 열기')));
}

let poll = 0;

export async function run(id: string): Promise<void> {
  window.clearTimeout(poll);
  const r = await agents.get(`/runs/${encodeURIComponent(id)}`);
  const g = r.grant;
  replace(main(),
    pageHead(r.title || r.id, h('span', null, h('code', null, r.id), ' ', phase(r.phase),
      ` · 요청 ${r.requested_by === 'model' ? 'Claude' : '나'}`), TABS),
    r.approve_url && h('p', { class: 'flash' }, 'Claude가 요청한 실행입니다. 키·모델·한도를 정해 ',
      h('a', { href: r.approve_url }, '승인 화면에서 승인'), '하면 시작합니다.'),
    r.error && h('p', { class: 'flash error' }, r.error),
    r.flow ? section('입력', r.input ? h('p', null, r.input) : h('p', { class: 'muted' }, '없음 (블럭의 명령만으로 실행)'))
      : section('목표', h('p', null, r.goal)),
    g && section('허가',
      h('ol', null, g.routes.map((x: Json) => h('li', null, h('b', null, x.key), ` ${x.model} `,
        h('span', { class: 'muted small' }, x.roles.map(roleName).join(', '))))),
      h('p', { class: 'muted small' }, `동시 ${g.max_agents} · 총 ${g.max_spawns} · 깊이 ${g.max_depth} · 턴 ${g.max_steps} · ` +
        `토큰 ${g.max_tokens || '무제한'} · 문맥 ${g.context} · 보관 ${g.retention} · 정책 ${g.policy}`)),
    r.flow && flowSection(r),
    section('에이전트',
      h('p', { class: 'muted small' }, `입력 ${num(r.usage.input)} · 출력 ${num(r.usage.output)} · 캐시 ${num(r.usage.cache_read)} 토큰`),
      tree(r.tree) ?? empty(r.phase === 'requested' ? '승인되면 시작합니다.' : '아직 시작하지 않았습니다.'),
      r.state === 'open' && h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (await act(e.target as HTMLButtonElement, () => agents.post(`/runs/${r.id}/cancel`), '취소를 요청했습니다.')) void run(id);
      } }, '실행 취소'))),
    section('다시 쓰기',
      h('p', { class: 'muted small' }, '이 실행의 순서도·입력·한도를 그대로 씁니다. 처음 순서도가 없던 실행은 블럭 하나(팀)로 엽니다.'),
      h('div', { class: 'actions' },
        buttonLink(`/agents/presets/new?from=${encodeURIComponent(r.id)}`, '열어서 고치고 실행'),
        h('button', { class: 'secondary', disabled: !r.grant, onclick: async (e: Event) => {
          const rc = r.recipe;
          const again = await act(e.target as HTMLButtonElement,
            () => agents.post('/runs', { goal: rc.input, title: rc.title, grant: rc.grant, flow: rc.flow }));
          if (again) { flashNext('ok', '같은 설정으로 다시 시작했습니다.'); go(`/agents/runs/${again.id}`); }
        } }, '바로 다시 실행'),
        form({ class: 'inline' }, async (f, b) => {
          const rc = r.recipe;
          const name = String(values(f).name);
          const p = await act(b, () => agents.put(`/presets/${encodeURIComponent(name)}`,
            { goal: rc.input, title: rc.title, grant: rc.grant, flow: rc.flow }));
          if (p) { flashNext('ok', `프리셋 ${name}으로 저장했습니다. 여기서 예약할 수 있습니다.`); go(`/agents/presets/${name}`); }
        }, h('input', { name: 'name', required: true, pattern: '[a-z0-9][a-z0-9._\\-]*', placeholder: '프리셋 이름' }),
          h('button', { class: 'secondary' }, '프리셋으로 저장')))),
    r.result && section(h('span', null, '결과 ', tag(r.result.outcome)), h('pre', { class: 'wrap' }, r.result.text),
      r.result.notes.map((n: Json) => h('p', { class: 'small' }, `[${n.id}] ${n.text}`))),
    r.board.length > 0 && section('공유된 노트', r.board.map((n: Json) =>
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
    h('label', null, '형식', h('select', { name: 'format' }, (opts.formats as string[]).map(f =>
      h('option', { value: f, selected: f === 'openai-chat' }, FORMAT[f] ?? f)))),
    h('label', null, 'Base URL ', h('span', { class: 'muted small' }, '버전 경로까지 (예: https://openrouter.ai/api/v1)'),
      h('input', { name: 'base_url', placeholder: 'https://…/v1' })));
  const provider = h('select', { name: 'provider', onchange: () => custom.classList.toggle('hidden', provider.value !== 'custom') },
    (opts.providers as string[]).map(p => h('option', { value: p }, p === 'custom' ? 'Custom (표준 형식 서버)' : providerName(p))));
  replace(main(),
    pageHead('API 키', '에이전트가 쓰는 본인의 키입니다. 키는 등록 즉시 암호화되어 에이전트 실행에만 쓰이고, 모델에게는 보이지 않습니다.', TABS),
    section(`등록된 키 (${list.length})`, list.length ? list.map(k => h('div', { class: 'item' },
      h('div', { class: 'item-head' }, h('b', null, k.ref), tag(providerName(k.provider)), h('code', null, k.fingerprint),
        tag(k.status, k.status === 'ok' ? 'ok' : k.status === 'unchecked' ? 'warn' : 'bad'),
        h('span', { class: 'muted small' }, `${FORMAT[k.format] ?? k.format}${k.base_url ? ' · ' + k.base_url : ''} · 마지막 사용 ${when(k.last_used)}`)),
      k.used_by.length > 0 && h('p', { class: 'small' }, '쓰는 프리셋: ',
        k.used_by.map((n: string, i: number) => [i ? ', ' : '', link(`/agents/presets/${n}`, n)])),
      h('details', null, h('summary', null, `모델 ${k.models.length}개${k.models_listed ? '' : ' (제공자 목록 없음: 추천 목록)'}`),
        h('p', { class: 'small' }, k.models.map((m: string) => h('code', null, m, ' ')))),
      h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        const users = k.used_by.length ? `\n이 키를 쓰는 프리셋(${k.used_by.join(', ')})은 블럭의 키를 다시 고를 때까지 실행되지 않습니다.` : '';
        if (!confirm(`${k.ref} 키를 지울까요?${users}`)) return;
        if (await act(e.target as HTMLButtonElement, () => agents.del(`/keys/${k.provider}/${k.label}`), '지웠습니다.')) void keys();
      } }, '삭제')))) : empty('등록한 키가 없습니다.')),
    section('키 등록', h('p', { class: 'muted small' }, '등록할 때 제공자의 모델 목록을 한 번 불러와 키를 확인합니다. 그 목록이 이 키의 모델 선택지가 됩니다.'),
      form({ autocomplete: 'off' }, async (f, b) => {
        const k = await act(b, () => agents.post('/keys', values(f)), (r: Json) => `${r.ref} 등록 · 모델 ${r.models.length}개`);
        if (k) void keys();
      },
        h('div', { class: 'cols' }, h('label', null, '제공자', provider),
          h('label', null, '이름 ', h('span', { class: 'muted small' }, '영문·숫자·.-_ (예: main, work)'),
            h('input', { name: 'label', required: true, pattern: '[A-Za-z0-9._\\-]{1,32}', value: 'main' }))),
        h('label', null, 'API 키 ', h('span', { class: 'muted small' }, 'Custom 서버가 인증을 받지 않으면 비워 두세요'),
          h('input', { name: 'secret', type: 'password', autocomplete: 'new-password' })),
        custom,
        h('div', { class: 'actions' }, h('button', null, '확인하고 등록')))));
}

// ── files ───────────────────────────────────────────────────────────────

export async function files(): Promise<void> {
  const path = new URLSearchParams(location.search).get('path') ?? '';
  const d = await agents.get(`/files?path=${encodeURIComponent(path)}`);
  const parts = path.split('/').filter(Boolean);
  const crumbs = [link('/agents/files', '/work'), ...parts.map((p, i) =>
    [' / ', link(`/agents/files?path=${encodeURIComponent(parts.slice(0, i + 1).join('/'))}`, p)])];
  title('파일');
  replace(main(),
    pageHead('파일', ['샌드박스의 ', h('code', null, '/work'), ': 스크립트와 에이전트가 쓰는 작업 공간입니다(읽기 전용). 에이전트 실행은 ',
      h('code', null, '/work/runs/<실행>'), '에서 일합니다.'], TABS),
    section(crumbs, d.kind === 'dir'
      ? (d.entries.length ? h('div', { class: 'table-wrap' }, h('table', null, h('tbody', null, d.entries.map((e: Json) => h('tr', null,
          h('td', { class: 'wrap' }, link(`/agents/files?path=${encodeURIComponent((path ? path + '/' : '') + e.name)}`,
            e.name + (e.kind === 'dir' ? '/' : ''))),
          h('td', { class: 'muted small num' }, e.kind === 'dir' ? '' : `${num(e.size)} B`))))))
        : empty('비어 있습니다.'))
      : d.text === null ? h('p', { class: 'muted' }, `텍스트가 아닌 파일입니다 (${num(d.size)} B).`)
        : [h('p', { class: 'muted small' }, `${num(d.size)} B`), h('pre', { class: 'wrap' }, d.text)]));
}
