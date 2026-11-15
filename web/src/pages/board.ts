// The public board (docs/board.md): the administrators' notices, what people share with each other — an agents'
// preset or a sandbox layer, each a copy that whoever takes it makes their own (a preset's keys never travel: its
// blocks run on the taker's own keys of the same providers; a layer is built again in the taker's sandbox, under
// their policy) — and the projects one has not joined yet. The chips narrow it to one kind, the search to some
// words. Nothing else is posted: no comment, no post of one's own besides a share (docs/board.md "What is not
// here"). The kinds and the limits are the board's (GET / says them); the projects are the account service's.

import { account, act, api, button, choice, dialog, empty, flash, go, h, help, link, main, menuButton, message, meta, pageHead, replace,
         section, tag, title, when } from '/auth/static/site.js';
import type { Json, MenuSection } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { flowView } from './flows';
import { POLICIES } from './projects';

const board = api('/board/api/v1');
const P = '/board';
const ALL = '';
const NOTICES = 'notice';
const PROJECTS = 'project';
/** What each kind of share is called; where a taken one lands, when it has a page of its own. */
const KIND: Record<string, string> = { preset: n_('프리셋'), layer: n_('레이어') };
const HOME: Record<string, (name: string) => string> = { preset: name => `/agents/presets/${encodeURIComponent(name)}` };
const kindName = (k: string) => t(KIND[k] ?? k);

type Render = (text: string) => string;

interface Board { me: { uid: string; admin: boolean }; kinds: string[]; limits: { title: number; about: number; notice: number };
                  shares: Json[]; notices: Json[] }

/** The words a search looks in. */
const words = (...parts: unknown[]) => parts.filter(Boolean).join(' ').toLowerCase();

export async function boardPage(): Promise<void> {
  title(t('공개 보드'));
  const params = new URLSearchParams(location.search);
  const [d, projects] = await Promise.all([
    board.get('/') as Promise<Board>,
    account().get('/projects').then((r: Json) => (r.projects as Json[]).filter(p => !p.member && !p.archived), (e: unknown) => e as Error),
  ]);
  // a notice is markdown, rendered without HTML (the notes' renderer: loaded only when there is a notice to show)
  const render: Render = d.notices.length ? (await import('../lib/markdown')).renderer({ note: () => null, raw: p => p }) : s => s;
  const reload = () => boardPage();
  let view = params.get('view') ?? ALL;
  if (![ALL, NOTICES, PROJECTS, ...d.kinds].includes(view)) view = ALL;

  const search = h('input', { type: 'search', value: params.get('q') ?? '', placeholder: t('보드에서 찾기'), 'aria-label': t('보드에서 찾기'),
                              oninput: () => { draw(); remember(); } });
  const chips = choice([[ALL, t('전체')], [NOTICES, t('공지')], ...d.kinds.map(k => [k, kindName(k)] as [string, string]), [PROJECTS, t('프로젝트')]],
                       view, v => { view = v; draw(); remember(); }, { 'aria-label': t('보드의 갈래') });
  const body = h('div');

  function remember(): void {
    const q = new URLSearchParams();
    if (search.value) q.set('q', search.value);
    if (view) q.set('view', view);
    history.replaceState(null, '', q.toString() ? `${P}?${q}` : P);
  }

  const found = (text: string) => { const q = search.value.trim().toLowerCase(); return !q || text.includes(q); };
  const showing = (which: string) => view === ALL || view === which;

  function draw(): void {
    const notices = d.notices.filter(n => found(words(n.title, n.body)));
    const shares = d.shares.filter(s => showing(s.kind) && found(words(s.title, s.about, s.name, s.author, kindName(s.kind))));
    const open = Array.isArray(projects) ? projects.filter(p => found(words(p.title, p.description, p.cn))) : projects;
    const narrowed = !!search.value.trim();
    replace(body,
      showing(NOTICES) && (notices.length || view === NOTICES) && section(t('공지'),
        notices.length ? h('div', { class: 'notices' }, notices.map(n => noticeItem(n, d, render, reload)))
          : empty(narrowed ? t('찾는 공지가 없습니다.') : t('공지가 없습니다.'))),
      (view === ALL || d.kinds.includes(view)) && section(view === ALL ? t('공유') : kindName(view),
        shares.length ? h('div', { class: 'store' }, shares.map(s => shareCard(s, d, reload)))
          : empty(narrowed ? t('찾는 공유가 없습니다.') : t('아직 공유된 것이 없습니다. 내 프리셋이나 레이어를 공유해 보세요.'))),
      showing(PROJECTS) && (view === PROJECTS || !Array.isArray(open) || open.length > 0) && section(t('들어갈 수 있는 프로젝트'),
        !Array.isArray(open) ? empty(message(open))
          : open.length ? h('div', { class: 'store' }, open.map(projectCard))
            : empty(narrowed ? t('찾는 프로젝트가 없습니다.') : t('들어갈 수 있는 다른 프로젝트가 없습니다.'))));
  }

  draw();
  replace(main(), pageHead(t('공개 보드')),
    h('div', { class: 'board-tools' }, search,
      h('div', { class: 'actions' }, button(t('공유하기'), () => shareDialog(d, reload)),
        d.me.admin && button(t('공지 쓰기'), () => noticeDialog(d, null, reload), 'secondary'))),
    chips, body);
}

// ── notices ─────────────────────────────────────────────────────────────

function noticeItem(n: Json, d: Board, render: Render, reload: () => void): HTMLElement {
  const text = h('div', { class: 'note-body' });
  text.innerHTML = render(n.body);  // markdown without HTML (markdown-it, html: false)
  const menuOf = (): MenuSection[] => [{ title: n.title, items: [
    { label: t('고치기'), run: () => noticeDialog(d, n, reload) },
    { label: n.pinned ? t('고정 풀기') : t('맨 위에 고정'), run: async () => { await board.patch(`/notices/${n.id}`, { pinned: !n.pinned }); reload(); } },
    { label: t('지우기'), danger: true, run: async () => {
      if (await dialog(t('{title} 지우기', { title: n.title }), h('p', null, t('공지를 지웁니다. 되돌릴 수 없습니다.')), { ok: t('지우기'), danger: true })) {
        await board.del(`/notices/${n.id}`);
        reload();
      }
    } }] }];
  return h('article', { class: `notice${n.pinned ? ' pinned' : ''}`, 'data-notice': n.id },
    h('div', { class: 'item-head' }, n.pinned && tag(t('고정'), 'ok'), h('b', null, n.title),
      h('span', { class: 'muted small' }, when(n.updated)),
      d.me.admin && menuButton(menuOf, t('{title} 메뉴', { title: n.title }))),
    text);
}

async function noticeDialog(d: Board, n: Json | null, reload: () => void): Promise<void> {
  const head = h('input', { name: 'title', required: true, maxlength: d.limits.title, value: n?.title ?? '', autocomplete: 'off' });
  const text = h('textarea', { name: 'body', required: true, rows: 8, maxlength: d.limits.notice }, n?.body ?? '');
  const pin = h('input', { type: 'checkbox', name: 'pinned', checked: !!n?.pinned });
  const ok = await dialog(n ? t('공지 고치기') : t('공지 쓰기'), h('div', null,
    h('label', null, t('제목'), head),
    h('label', null, t('내용'), help(t('마크다운으로 씁니다. HTML 은 글자 그대로 보입니다.')), text),
    h('label', { class: 'check' }, pin, ' ', t('맨 위에 고정'))), { ok: n ? t('저장') : t('올리기') });
  if (!ok) return;
  const v = { title: head.value, body: text.value, pinned: pin.checked };
  if (await act(null, () => n ? board.patch(`/notices/${n.id}`, v) : board.post('/notices', v))) reload();
}

// ── shares ──────────────────────────────────────────────────────────────

function shareCard(s: Json, d: Board, reload: () => void): HTMLElement {
  const mine = s.author === d.me.uid;
  const menuOf = (): MenuSection[] => [{ title: s.title, items: [
    ...(mine ? [{ label: t('다시 공유'), detail: t('지금의 내 {kind}로 새 판을 올립니다', { kind: kindName(s.kind) }), run: () => shareDialog(d, reload, s) }] : []),
    ...(d.me.admin ? [s.hidden ? { label: t('다시 보이기'), run: async () => { await board.post(`/shares/${s.id}/show`); reload(); } }
                               : { label: t('숨기기'), run: () => hideDialog(s, d, reload) }] : []),
    { label: t('내리기'), danger: true, run: async () => {
      if (await dialog(t('{title} 내리기', { title: s.title }), h('p', null, t('보드에서 지웁니다. 이미 가져간 사람의 것은 그대로 남습니다.')),
                       { ok: t('내리기'), danger: true })) {
        await board.del(`/shares/${s.id}`);
        reload();
      }
    } }] }];
  return h('article', { class: 'store-card share', 'data-share': s.id, 'data-hidden': s.hidden ? 'true' : null },  // not .hidden: that class hides
    h('div', { class: 'store-text' },
      h('h3', null, h('button', { type: 'button', class: 'link', onclick: () => void act(null, () => openShare(s, reload)) }, s.title)),
      s.about && h('p', { class: 'desc' }, s.about),
      h('p', { class: 'tags' }, tag(kindName(s.kind)), mine && tag(t('내 공유'), 'ok'), s.hidden && tag(t('숨김: {why}', { why: s.hidden_why }), 'bad')),
      meta([h('code', null, s.author), t('판 {n}', { n: s.version }), t('{n}번 가져감', { n: s.imports }), when(s.updated)]
        .flatMap((x, i) => [i > 0 && ' · ', h('span', null, x)]))),
    h('div', { class: 'app-tools' }, !mine && button(t('가져오기'), () => openShare(s, reload), 'secondary'),
      (mine || d.me.admin) && menuButton(menuOf, t('{title} 메뉴', { title: s.title }))));
}

/** What a preset copy runs: its blocks drawn as the presets page draws them, then each block's command; the run's limits. */
function presetPreview(copy: Json): HTMLElement {
  const steps = (copy.flow?.steps ?? []) as Json[];
  return h('div', { class: 'share-preview' },
    copy.goal && h('p', null, h('span', { class: 'muted' }, t('입력')), ' ', copy.goal),
    h('div', { class: 'flow-preview' }, flowView({ ...copy.flow, steps: steps.map(s => ({ ...s, key: s.provider })) }, {}, new Map())),
    h('ol', { class: 'share-steps' }, steps.map(s => h('li', null, h('b', null, s.title || s.id), ' ',
      h('span', { class: 'muted small' }, [s.provider, s.model, s.team && t('팀')].filter(Boolean).join(' · ')), h('pre', null, s.command)))),
    Object.keys(copy.limits ?? {}).length > 0 && h('dl', null, Object.entries(copy.limits as Record<string, unknown>).map(([k, v]) =>
      [h('dt', null, h('code', null, k)), h('dd', null, typeof v === 'object' ? JSON.stringify(v) : String(v))])));
}

/** What a layer copy builds: the shared layers it stands on, its env, its script. */
function layerPreview(copy: Json): HTMLElement {
  const env = Object.entries((copy.env ?? {}) as Record<string, string>);
  return h('div', { class: 'share-preview' },
    h('dl', null,
      h('dt', null, t('바탕')), h('dd', null, (copy.parents ?? []).length ? (copy.parents as string[]).map(p => tag(p)) : '-'),
      env.length > 0 && [h('dt', null, t('환경')), h('dd', null, env.map(([k, v]) => h('div', null, h('code', null, `${k}=${v}`))))]),
    h('pre', { class: 'share-script' }, copy.script || ''));
}

async function openShare(s: Json, reload: () => void): Promise<void> {
  const full = await board.get(`/shares/${s.id}`);
  const take = await dialog(full.title, h('div', { class: 'share-detail' },
    full.about && h('p', null, full.about),
    meta(kindName(full.kind), ' · ', h('code', null, full.author), ' · ', t('판 {n}', { n: full.version }), ' · ', when(full.updated)),
    full.kind === 'preset' ? presetPreview(full.payload) : layerPreview(full.payload)),
    { ok: t('가져오기'), cancel: t('닫기') });
  if (take) await takeDialog(full, reload);
}

async function takeDialog(s: Json, reload: () => void): Promise<void> {
  const name = h('input', { name: 'as', required: true, value: s.name, autocomplete: 'off', spellcheck: false });
  const providers = [...new Set(((s.payload?.flow?.steps ?? []) as Json[]).map(x => x.provider))].join(', ');
  const ok = await dialog(t('{title} 가져오기', { title: s.title }), h('div', null,
    h('label', null, t('내 {kind}의 이름', { kind: kindName(s.kind) }), name),
    help(s.kind === 'preset' ? t('블럭마다 내 {providers} 키로 돌아갑니다 — 키는 공유되지 않습니다.', { providers })
      : t('내 샌드박스에서, 내 기본 정책으로 다시 빌드합니다.'))), { ok: t('가져오기') });
  if (!ok) return;
  const r = await act(null, () => board.post(`/shares/${s.id}/import`, { as: name.value.trim() }));
  if (!r) return;
  const home = HOME[r.kind];
  flash('ok', t('내 {kind} {name}(으)로 가져왔습니다.', { kind: kindName(r.kind), name: r.name }), home && { label: t('열기'), run: () => go(home(r.name)) });
  reload();
}

async function shareDialog(d: Board, reload: () => void, again?: Json): Promise<void> {
  const mine = await board.get('/mine') as Record<string, Json[]>;
  const kind = h('select', { name: 'kind', disabled: !!again }, d.kinds.map(k => h('option', { value: k, selected: k === (again?.kind ?? d.kinds[0]) }, kindName(k))));
  const item = h('select', { name: 'name', required: true, disabled: !!again });
  const blocked = h('div');
  const head = h('input', { name: 'title', maxlength: d.limits.title, value: again?.title ?? '', autocomplete: 'off' });
  const about = h('textarea', { name: 'about', rows: 2, maxlength: d.limits.about }, again?.about ?? '');
  function fill(): void {
    const list = mine[kind.value] ?? [];
    const free = list.filter(x => !x.why);
    replace(item, free.length ? free.map(x => h('option', { value: x.name, selected: x.name === again?.name }, x.title && x.title !== x.name ? `${x.title} (${x.name})` : x.name))
      : h('option', { value: '' }, t('공유할 수 있는 {kind}가 없습니다', { kind: kindName(kind.value) })));
    if (again && !free.some(x => x.name === again.name)) item.append(h('option', { value: again.name, selected: true }, again.name));
    replace(blocked, list.length > free.length && h('ul', { class: 'plain small muted' },
      list.filter(x => x.why).map(x => h('li', null, h('code', null, x.name), ' — ', x.why))));
    pick();
  }
  function pick(): void {
    head.placeholder = (mine[kind.value] ?? []).find(x => x.name === item.value)?.title ?? '';
  }
  kind.addEventListener('change', fill);
  item.addEventListener('change', pick);
  fill();
  const ok = await dialog(again ? t('{title} 다시 공유', { title: again.title }) : t('공유하기'), h('div', null,
    h('div', { class: 'cols' }, h('label', null, t('무엇을'), kind), h('label', null, t('내 것 중에'), item)),
    blocked,
    h('label', null, t('제목'), help(t('비우면 그 이름 그대로입니다.')), head),
    h('label', null, t('한 줄 설명'), about),
    help(t('지금의 모습이 복사되어 올라갑니다 — 나중에 고친 것은 다시 공유해야 보입니다. API 키와 실행 기록은 함께 가지 않습니다.'))),
    { ok: again ? t('다시 공유') : t('공유') });
  if (!ok || !item.value) return;
  if (await act(null, () => board.post('/shares', { kind: kind.value, name: item.value, title: head.value, about: about.value }))) reload();
}

async function hideDialog(s: Json, d: Board, reload: () => void): Promise<void> {
  const why = h('input', { name: 'why', required: true, maxlength: d.limits.about, autocomplete: 'off' });
  const ok = await dialog(t('{title} 숨기기', { title: s.title }), h('div', null,
    h('label', null, t('까닭'), help(t('올린 사람에게 이 까닭이 보입니다. 다른 사람에게는 공유가 보이지 않습니다.')), why)),
    { ok: t('숨기기'), danger: true });
  if (ok && await act(null, () => board.post(`/shares/${s.id}/hide`, { why: why.value }))) reload();
}

// ── projects ────────────────────────────────────────────────────────────

function projectCard(p: Json): HTMLElement {
  return h('article', { class: 'store-card', 'data-project': p.cn },
    h('div', { class: 'store-text' },
      h('h3', null, link(`/projects/${p.cn}`, p.title)),
      p.description && h('p', { class: 'desc' }, p.description),
      meta(t(POLICIES[p.join_policy] ?? p.join_policy), ' · ', t('구성원 {n}명', { n: p.members.length }),
        p.requested && [' ', tag(t('신청 중'), 'warn')])));
}
