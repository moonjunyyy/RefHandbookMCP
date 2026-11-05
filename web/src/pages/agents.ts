// The agents' pages over /agents/api/v1: runs (start one from a preset, follow one), API keys, the
// workspace's files (the presets, each a flow, are flows.ts's). Approving a run the model asked for is the approval page's.

import { act, agents, button, dialog, empty, flashNext, form, go, h, help, keys as pageKeys, link, main, menuButton, meta, num, onMenu, pageHead, replace, section, tag, title, values, when } from '/auth/static/site.js';
import type { Child, Json, MenuSection } from '/auth/static/site.js';
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

/** What a run's branch is to each repository (agents/branches.py): its label and its tag's kind. */
function branchState(state: string): [string, string] {
  switch (state) {
    case 'open': return [t('작업 중'), ''];
    case 'merged': return [t('병합됨'), 'ok'];
    case 'kept': return [t('브랜치에 남음'), 'warn'];
    case 'unchanged': return [t('바뀐 것 없음'), ''];
    case 'lost': return [t('사라짐'), 'bad'];
    default: return [t('만들지 못함'), 'bad'];
  }
}

/** The run's branch over the repositories of its read-write mounts: each one's place, what became of it, what git said. */
function branches(b: Json | null): Child {
  if (!b) return false;
  return section(h('span', null, t('브랜치'), ' ', h('code', null, b.branch)),
    b.why && meta(b.why),
    b.repos.length > 0 && h('ul', { class: 'plain branches' }, b.repos.map((r: Json) => {
      const [label, kind] = branchState(r.state);
      return h('li', null, h('code', null, r.repo), ' ', tag(label, kind),
        r.files > 0 && [' ', h('span', { class: 'small' }, t('파일 {n}개', { n: r.files }))],
        r.why && h('pre', { class: 'wrap small' }, r.why));
    })));
}

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
    branches(r.branches),
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

// ── files ───────────────────────────────────────────────────────────────────

const filesHref = (p: string) => (p ? `/agents/files?path=${encodeURIComponent(p)}` : '/agents/files');
const downloadHref = (p: string) => `/agents/api/v1/files/download?path=${encodeURIComponent(p)}`;
const inside = (dir: string, name: string) => (dir ? `${dir}/${name}` : name);
const parentOf = (p: string) => p.slice(0, Math.max(0, p.lastIndexOf('/')));
const trimmed = (p: string) => p.trim().replace(/^\/+|\/+$/g, '');

/** The workspace (/work), the user's only way to the sandbox's files: a folder's entries or a file's text, and what
 * the user does with them — download (a folder as a zip), make a folder, rename or move, delete. An entry's actions
 * are its menu (⋯, the right-click, Shift+F10), as the vault's notes have theirs; several entries are picked by
 * their boxes (Shift-click picks a run of them, the head's box all) and handled together from the bar that picking
 * brings up (download as one zip, move into a folder, delete). Esc lets the pick go; Delete deletes it. */
export async function files(): Promise<void> {
  const path = trimmed(new URLSearchParams(location.search).get('path') ?? '');
  const d = await agents.get(`/files?path=${encodeURIComponent(path)}`);
  const parts = path.split('/').filter(Boolean);
  const crumbs = [link(filesHref(''), '/work'), ...parts.map((p, i) =>
    [' / ', link(filesHref(parts.slice(0, i + 1).join('/')), p)])];
  const redraw = (p: string) => go(filesHref(p));  // the page again, at p (the same page: drawn anew)

  async function makeFolder(dir: string): Promise<void> {
    const name = h('input', { type: 'text', required: true, autofocus: true });
    if (!await dialog(t('새 폴더'), h('div', { class: 'fields' }, h('label', null, t('이름 (폴더/이름)'), name)), { ok: t('만들기') })) return;
    const q = trimmed(name.value);
    if (!q) return;
    await agents.post('/files/mkdir', { path: inside(dir, q) });
    redraw(dir);
  }

  async function move(p: string): Promise<void> {
    const to = h('input', { type: 'text', required: true, value: p, autofocus: true });
    if (!await dialog(t('이름 바꾸기·옮기기'), h('div', { class: 'fields' }, h('label', null, t('새 경로 (폴더/이름)'), to)), { ok: t('옮기기') })) return;
    const q = trimmed(to.value);
    if (!q || q === p) return;
    const r = await agents.post('/files/move', { from: p, to: q });
    redraw(p === path ? r.path : path);  // the open file follows its new name; a row moved away leaves this folder
  }

  async function remove(p: string, kind: string): Promise<void> {
    const what = kind === 'dir' ? t('{name} 폴더와 그 안의 모든 것을 지웁니다. 되돌릴 수 없습니다.', { name: p })
      : t('{name} 을(를) 지웁니다. 되돌릴 수 없습니다.', { name: p });
    if (!await dialog(t('지우기'), h('p', null, what), { ok: t('지우기'), danger: true })) return;
    await agents.del(`/files?path=${encodeURIComponent(p)}`);
    redraw(p === path ? parentOf(p) : path);
  }

  /** An entry's actions, at its row and, for the open file, at its head. */
  const entryMenu = (p: string, kind: string, opened = false): MenuSection[] => {
    const whole = kind === 'dir' || kind === 'file';  // a link or a special file is moved or deleted, never followed
    return [{ title: p, items: [
      ...(whole && !opened ? [{ label: t('열기'), run: () => go(filesHref(p)) }] : []),
      ...(whole ? [{ label: t('내려받기'), detail: kind === 'dir' ? 'zip' : '', run: () => location.assign(downloadHref(p)) }] : []),
      { label: t('이름 바꾸기·옮기기…'), run: () => move(p) },
      { label: t('지우기'), danger: true, run: () => remove(p, kind) } ] }];
  };

  // the pick: entries of this folder handled together (their paths, in the folder's order)
  const entries: Json[] = d.kind === 'dir' ? d.entries : [];
  const picked = new Set<string>();
  let anchor = -1;  // the row a Shift-click picks from
  const boxes: HTMLInputElement[] = [];
  const all = h('input', { type: 'checkbox', 'aria-label': t('모두 고르기'),
                           onchange: () => { entries.forEach(e => (all.checked ? picked.add(e.name) : picked.delete(e.name))); shown(); } });
  const head = h('div', { class: 'actions' });
  const pickedPaths = () => entries.filter(e => picked.has(e.name)).map(e => inside(path, e.name));

  function pick(i: number, on: boolean, run: boolean): void {
    const [a, b] = run && anchor >= 0 ? [Math.min(anchor, i), Math.max(anchor, i)] : [i, i];
    for (let k = a; k <= b; k++) (on ? picked.add(entries[k].name) : picked.delete(entries[k].name));
    anchor = i;
    shown();
  }

  /** The head of the folder: what to do with it, or, while something is picked, with the pick. */
  function shown(): void {
    entries.forEach((e, i) => { if (boxes[i]) { boxes[i].checked = picked.has(e.name); boxes[i].closest('tr')?.classList.toggle('picked', boxes[i].checked); } });
    all.checked = picked.size > 0 && picked.size === entries.length;
    all.indeterminate = picked.size > 0 && picked.size < entries.length;
    replace(head, picked.size
      ? [h('strong', { class: 'picked' }, t('{n}개 고름', { n: picked.size })),
         button(t('내려받기'), () => location.assign(`/agents/api/v1/files/download?${pickedPaths().map(p => `path=${encodeURIComponent(p)}`).join('&')}`)),
         button(t('옮기기…'), () => movePicked(), 'secondary'),
         button(t('지우기'), () => removePicked(), 'danger'),
         button(t('고르기 해제'), () => { picked.clear(); shown(); }, 'link')]
      : [button(t('새 폴더'), () => makeFolder(path), 'secondary'),
         button(t('폴더 내려받기 (zip)'), () => location.assign(downloadHref(path)), 'secondary'),
         path && menuButton(() => entryMenu(path, 'dir', true))]);
  }

  /** What the dialogs name: the picked entries, a few of them by name. */
  const naming = (ps: string[]) => h('ul', { class: 'plain small' }, ps.slice(0, 8).map(p => h('li', null, h('code', null, p))),
    ps.length > 8 && h('li', { class: 'muted' }, t('외 {n}개', { n: ps.length - 8 })));

  async function movePicked(): Promise<void> {
    const ps = pickedPaths();
    const into = h('input', { type: 'text', value: path, autofocus: true });
    if (!await dialog(t('{n}개 옮기기', { n: ps.length }), h('div', { class: 'fields' }, naming(ps),
      h('label', null, t('옮길 폴더 (비우면 /work)'), into)), { ok: t('옮기기') })) return;
    const q = trimmed(into.value);
    if (q === path) return;
    await agents.post('/files/move', { from: ps, into: q });
    redraw(path);
  }

  async function removePicked(): Promise<void> {
    const ps = pickedPaths();
    if (!await dialog(t('{n}개 지우기', { n: ps.length }), h('div', null,
      h('p', null, t('폴더는 그 안의 것과 함께 지워집니다. 되돌릴 수 없습니다.')), naming(ps)),
      { ok: t('지우기'), danger: true })) return;
    await agents.del(`/files?${ps.map(p => `path=${encodeURIComponent(p)}`).join('&')}`);
    redraw(path);
  }

  pageKeys([
    { key: 'Escape', label: t('고르기 해제'), run: () => { picked.clear(); shown(); }, when: () => picked.size > 0 },
    { key: 'Delete', label: t('고른 것 지우기'), run: () => removePicked(), when: () => picked.size > 0 },
  ]);

  const entryRow = (e: Json, i: number) => {
    const p = inside(path, e.name);
    const whole = e.kind === 'dir' || e.kind === 'file';
    const box = boxes[i] = h('input', { type: 'checkbox', 'aria-label': t('{name} 고르기', { name: e.name }) });
    box.addEventListener('click', (ev: MouseEvent) => pick(i, box.checked, ev.shiftKey));
    return onMenu(h('tr', null,
      h('td', { class: 'pick' }, box),
      h('td', { class: 'wrap' }, whole ? link(filesHref(p), e.name + (e.kind === 'dir' ? '/' : ''))
        : [e.name, ' ', tag(e.kind === 'link' ? t('심볼릭 링크') : t('특수 파일'))]),
      h('td', { class: 'muted small num' }, e.kind === 'file' ? `${num(e.size)} B` : ''),
      h('td', { class: 'actions' }, menuButton(() => entryMenu(p, e.kind)))), () => entryMenu(p, e.kind));
  };

  title(t('파일'));
  replace(main(),
    pageHead(t('파일'), agentTabs()), meta(h('code', null, '/work'), help([t('샌드박스에서 스크립트와 에이전트가 쓰는 작업 공간입니다.'), ' ',
      t('에이전트 실행은 각자 이 폴더에서 일합니다:'), ' ', h('code', null, '/work/runs/<run>'), ' ',
      t('줄마다 ⋯(또는 오른쪽 클릭)으로 내려받고, 이름을 바꾸거나 옮기고, 지웁니다.')])),
    d.kind === 'dir'
      ? section(crumbs, head,
          entries.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'files' },
            h('thead', null, h('tr', null, h('th', { class: 'pick' }, all), h('th', null, t('이름')), h('th', { class: 'num' }, t('크기')), h('th'))),
            h('tbody', null, entries.map(entryRow))))
            : empty(t('비어 있습니다.')))
      : section(crumbs,
          h('div', { class: 'actions' },
            button(t('내려받기'), () => location.assign(downloadHref(path))),
            menuButton(() => entryMenu(path, 'file', true))),
          d.text === null ? empty(t('텍스트가 아닌 파일입니다 ({size} B).', { size: num(d.size) }))
            : [meta(`${num(d.size)} B`), h('pre', { class: 'wrap' }, d.text)]));
  if (d.kind === 'dir') shown();
}
