// The agents' pages over /agents/api/v1: runs (start one, follow one), presets and their schedules,
// API keys, the workspace's files. Approving a run the model asked for is the approval page's.

import { agents, Json } from '../lib/api';
import { Child, h, replace, values } from '../lib/dom';
import { act, empty, flashNext, form, go, link, main, num, pageHead, section, tag, title, when } from '../lib/ui';
import { grantForm, Key, Options, providerName, roleName } from './grant';

const TABS = [{ href: '/agents/', label: '실행' }, { href: '/agents/flows', label: '순서도' },
  { href: '/agents/presets', label: '프리셋 · 예약' }, { href: '/agents/keys', label: 'API 키' },
  { href: '/agents/files', label: '파일' }, { href: '/approvals', label: '승인' }];
const PHASE: Record<string, [string, string]> = {
  requested: ['승인 대기', 'warn'], approved: ['시작 대기', ''], running: ['실행 중', 'ok'], done: ['완료', 'ok'],
  cancelled: ['취소됨', 'bad'], failed: ['실패', 'bad'],
};
const phase = (p: string) => tag(PHASE[p]?.[0] ?? p, PHASE[p]?.[1] ?? '');

async function basics(): Promise<{ keys: Key[]; opts: Options }> {
  const [keys, opts] = await Promise.all([agents.get('/keys'), agents.get('/options')]);
  return { keys, opts };
}

// ── runs ────────────────────────────────────────────────────────────────

export async function runs(): Promise<void> {
  const [{ keys, opts }, list] = await Promise.all([basics(), agents.get('/runs') as Promise<Json[]>]);
  const waiting = list.filter(r => r.phase === 'requested').length;
  const gf = grantForm(keys, opts);
  replace(main(),
    pageHead('에이전트', '목표와 한도를 정해 에이전트 팀을 띄웁니다. Claude가 요청한 실행은 승인 화면에서 승인해야 시작됩니다.', TABS),
    waiting > 0 && h('p', { class: 'flash' }, `승인을 기다리는 요청이 ${waiting}건 있습니다. `, h('a', { href: '/approvals' }, '승인 화면으로')),
    section(`실행 (${list.length})`, list.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['실행', '상태', '에이전트', '토큰', '요청', '시작'].map(t => h('th', null, t)))),
      h('tbody', null, list.map(r => h('tr', null,
        h('td', { class: 'wrap' }, link(`/agents/runs/${r.id}`, r.title || r.id), r.preset && h('span', { class: 'muted small' }, ` · ${r.preset}`)),
        h('td', null, phase(r.phase)), h('td', { class: 'num' }, String(r.agents)), h('td', { class: 'num' }, num(r.tokens)),
        h('td', null, r.requested_by === 'model' ? 'Claude' : '나'), h('td', null, when(r.requested)))))))
      : empty('아직 실행이 없습니다.')),
    section('새 실행', form({}, async (f, b) => {
      const v = values(f);
      const r = await act(b, () => agents.post('/runs', { goal: v.goal, title: v.title, save_as: v.save_as, grant: gf.grant() }));
      if (r) { flashNext('ok', '시작했습니다. 곧 리드 에이전트가 일을 시작합니다.'); go(`/agents/runs/${r.id}`); }
    },
      h('label', null, '목표 ', h('span', { class: 'muted small' }, '무엇을 이루면 끝인지까지'), h('textarea', { name: 'goal', rows: 4, required: true })),
      h('div', { class: 'cols' }, h('label', null, '제목', h('input', { name: 'title' })),
        h('label', null, '프리셋으로도 저장 ', h('span', { class: 'muted small' }, '이름을 적으면 같은 설정을 남깁니다'),
          h('input', { name: 'save_as', pattern: '[a-z0-9][a-z0-9._\\-]*', placeholder: '예: daily-report' }))),
      gf.el,
      h('div', { class: 'actions' }, h('button', { disabled: !keys.length }, '시작')))));
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
    section('목표', h('p', null, r.goal)),
    g && section('허가',
      h('ol', null, g.routes.map((x: Json) => h('li', null, h('b', null, x.key), ` ${x.model} `,
        h('span', { class: 'muted small' }, x.roles.map(roleName).join(', '))))),
      h('p', { class: 'muted small' }, `동시 ${g.max_agents} · 총 ${g.max_spawns} · 깊이 ${g.max_depth} · 턴 ${g.max_steps} · ` +
        `토큰 ${g.max_tokens || '무제한'} · 문맥 ${g.context} · 보관 ${g.retention} · 정책 ${g.policy}`)),
    section('에이전트',
      h('p', { class: 'muted small' }, `입력 ${num(r.usage.input)} · 출력 ${num(r.usage.output)} · 캐시 ${num(r.usage.cache_read)} 토큰`),
      tree(r.tree) ?? empty(r.phase === 'requested' ? '승인되면 시작합니다.' : '아직 시작하지 않았습니다.'),
      r.state === 'open' && h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (await act(e.target as HTMLButtonElement, () => agents.post(`/runs/${r.id}/cancel`), '취소를 요청했습니다.')) void run(id);
      } }, '실행 취소'))),
    r.result && section(h('span', null, '결과 ', tag(r.result.outcome)), h('pre', { class: 'wrap' }, r.result.text),
      r.result.notes.map((n: Json) => h('p', { class: 'small' }, `[${n.id}] ${n.text}`))),
    r.board.length > 0 && section('공유된 노트', r.board.map((n: Json) =>
      h('p', { class: 'small' }, tag(n.state, n.state === 'verified' ? 'ok' : ''), ` ${n.text}`))));
  if (r.state === 'open' && location.pathname === `/agents/runs/${id}`) {
    poll = window.setTimeout(() => { if (location.pathname === `/agents/runs/${id}`) void run(id); }, 5000);
  }
}

// ── presets and schedules ───────────────────────────────────────────────

export async function presets(): Promise<void> {
  const [{ keys, opts }, list] = await Promise.all([basics(), agents.get('/presets') as Promise<Json[]>]);
  const fresh = grantForm(keys, opts);
  replace(main(),
    pageHead('프리셋 · 예약', '자주 하는 실행을 목표와 허가째로 저장해 두고, 한 번에 실행하거나 정해진 때 저절로 실행되게 합니다. ' +
      '예약은 미리 해 둔 승인입니다: 때가 되면 이 설정 그대로 실행이 시작됩니다.', TABS),
    section(`프리셋 (${list.length})`,
      h('p', { class: 'muted small' }, '예약은 cron 다섯 칸(분 시 일 월 요일, 서버 시간)입니다. 예: ', h('code', null, '0 9 * * mon-fri'),
        ' 평일 9시, ', h('code', null, '@daily'), ' 매일. 목표에 ', h('code', null, '{date}'), '·', h('code', null, '{time}'),
        '을 쓰면 실행한 때로 바뀝니다. 앞 실행이 아직 돌고 있으면 그 회차는 건너뜁니다.'),
      list.length ? list.map(p => presetItem(p, keys, opts)) : empty('아직 프리셋이 없습니다.')),
    section('새 프리셋', form({}, async (f, b) => {
      const v = values(f);
      const p = await act(b, () => agents.put(`/presets/${encodeURIComponent(String(v.name))}`,
        { goal: v.goal, title: v.title, grant: fresh.grant() }), '저장했습니다.');
      if (p) void presets();
    },
      h('div', { class: 'cols' },
        h('label', null, '이름 ', h('span', { class: 'muted small' }, '영문 소문자·숫자·.-_'),
          h('input', { name: 'name', required: true, pattern: '[a-z0-9][a-z0-9._\\-]*' })),
        h('label', null, '제목', h('input', { name: 'title' }))),
      h('label', null, '목표', h('textarea', { name: 'goal', rows: 3, required: true })),
      fresh.el, h('div', { class: 'actions' }, h('button', { disabled: !keys.length }, '저장')))));
}

function presetItem(p: Json, keys: Key[], opts: Options): HTMLElement {
  const g = p.grant;
  const edit = grantForm(keys, opts, g);
  const preview = h('span', { class: 'muted small' });
  const cron = h('input', { name: 'cron', required: true, placeholder: '0 9 * * mon-fri', class: 'cron', oninput: () => {
    window.clearTimeout(Number(cron.dataset.t));
    cron.dataset.t = String(window.setTimeout(async () => {
      if (!cron.value.trim()) { preview.textContent = ''; return; }
      try {
        const r = await agents.post('/cron', { cron: cron.value });
        preview.textContent = `다음: ${r.next.slice(0, 3).map(when).join(', ')}`;
      } catch (e) { preview.textContent = (e as Error).message; }
    }, 300));
  } });
  return h('div', { class: 'item' },
    h('div', { class: 'item-head' }, h('b', null, p.title), h('code', null, p.name),
      h('span', { class: 'muted small' }, `${g.routes.map((r: Json) => `${r.model} (${r.roles.map(roleName).join('/')})`).join(', ')} · ` +
        `동시 ${g.max_agents} · 턴 ${g.max_steps}`)),
    h('p', { class: 'small' }, p.goal),
    h('div', { class: 'actions' },
      h('button', { onclick: async (e: Event) => {
        const r = await act(e.target as HTMLButtonElement, () => agents.post(`/presets/${p.name}/run`));
        if (r) { flashNext('ok', '시작했습니다.'); go(`/agents/runs/${r.id}`); }
      } }, '지금 실행'),
      form({ class: 'inline' }, async (_f, b) => {
        if (await act(b, () => agents.post(`/presets/${p.name}/schedules`, { cron: cron.value }), '예약을 추가했습니다.')) void presets();
      }, cron, h('button', { class: 'secondary' }, '예약 추가')),
      h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (!confirm(`프리셋 ${p.name}과 그 예약을 지울까요?`)) return;
        if (await act(e.target as HTMLButtonElement, () => agents.del(`/presets/${p.name}`), '지웠습니다.')) void presets();
      } }, '삭제')),
    preview,
    p.schedules.length > 0 && h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['cron', '상태', '다음', '마지막', '메모', ''].map(t => h('th', null, t)))),
      h('tbody', null, p.schedules.map((s: Json) => h('tr', null,
        h('td', null, h('code', null, s.cron)), h('td', null, s.enabled ? tag('켜짐', 'ok') : tag('꺼짐')),
        h('td', null, when(s.next_at)),
        h('td', null, when(s.last_at), s.last_run && [' ', link(`/agents/runs/${s.last_run}`, '실행')]),
        h('td', { class: 'wrap muted small' }, s.note),
        h('td', null,
          h('button', { class: 'secondary', onclick: async (e: Event) => {
            if (await act(e.target as HTMLButtonElement, () => agents.patch(`/schedules/${s.id}`, { enabled: !s.enabled }))) void presets();
          } }, s.enabled ? '끄기' : '켜기'), ' ',
          h('button', { class: 'secondary', onclick: async (e: Event) => {
            if (await act(e.target as HTMLButtonElement, () => agents.del(`/schedules/${s.id}`), '예약을 지웠습니다.')) void presets();
          } }, '삭제'))))))),
    h('details', { class: 'panel' }, h('summary', null, '설정 고치기'), form({}, async (f, b) => {
      const v = values(f);
      if (await act(b, () => agents.put(`/presets/${p.name}`, { goal: v.goal, title: v.title, grant: edit.grant() }), '저장했습니다.')) {
        void presets();
      }
    },
      h('label', null, '제목', h('input', { name: 'title', value: p.title })),
      h('label', null, '목표', h('textarea', { name: 'goal', rows: 3, required: true }, p.goal)),
      edit.el, h('div', { class: 'actions' }, h('button', null, '저장')))));
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
      h('details', null, h('summary', null, `모델 ${k.models.length}개${k.models_listed ? '' : ' (제공자 목록 없음: 추천 목록)'}`),
        h('p', { class: 'small' }, k.models.map((m: string) => h('code', null, m, ' ')))),
      h('div', { class: 'actions' }, h('button', { class: 'secondary', onclick: async (e: Event) => {
        if (!confirm(`${k.ref} 키를 지울까요? 이 키를 쓰는 실행은 다음 경로로 넘어갑니다.`)) return;
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
