// Presets, each a flow: a run drawn as blocks and arrows (agents/flows.py). A block is one agent: a key, a
// model on it and a command. An arrow is a next action with a name; when a block's agent finishes it
// picks one of its arrows by name (one arrow: no choice; none: the flow ends there). Arrows may lead
// back (a review that sends a draft back), up to a number of visits per block.
//
// Blocks move by dragging; an arrow is drawn from a block's right dot to another block (or added from
// the block's panel); the background pans, the wheel zooms. Every preset is a flow (one block is the
// simple case), so this one editor saves, runs and schedules them all; a past run opens here too
// (?from=<run>), to start again as it was or changed. The backend checks a flow and says what is wrong.

import { act, agents, empty, flash, flashNext, form, go, h, link, main, pageHead, replace, section, svg, tag, values, when } from '/auth/static/site.js';
import type { Json } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { grantForm, Key, keyLabel, modelPicker, Options } from './grant';
import { cronHelp, scheduling } from './schedule';
import { agentTabs } from './tabs';

export interface Step { id: string; title: string; key: string; model: string; command: string; team: boolean;
                       x: number; y: number }
export interface Edge { from: string; to: string; label: string }
export interface Flow { steps: Step[]; edges: Edge[]; start: string; max_visits: number }

const W = 220, H = 86, GAP_X = 340, GAP_Y = 140;

/** A flow as kept (or as an earlier version kept it: a goal for a command, no key, unnamed arrows). */
export function normalize(raw: Json): Flow {
  const steps: Step[] = (raw.steps ?? []).map((s: Json) => ({
    id: s.id, title: s.title ?? s.id, key: s.key ?? '', model: s.model ?? '', command: s.command ?? s.goal ?? '',
    team: !!s.team, x: Number(s.x) || 0, y: Number(s.y) || 0 }));
  return { steps, edges: (raw.edges ?? []).map((e: Json) => ({ from: e.from, to: e.to, label: e.label ?? '' })),
           start: raw.start ?? steps[0]?.id ?? '', max_visits: Number(raw.max_visits) || 3 };
}

/** What a block still needs before the flow can be kept, said as a text to show with t() ('' if nothing). */
function lacks(s: Step): string {
  return !s.key ? n_('키를 정하세요') : !s.model ? n_('모델을 정하세요') : !s.command.trim() ? n_('명령을 정하세요') : '';
}

const outsOf = (flow: Flow, id: string) => flow.edges.filter(e => e.from === id);
const titleOf = (flow: Flow, id: string) => flow.steps.find(s => s.id === id)?.title || id;
/** An arrow's name as the model sees it: its own, or the block it leads to. */
const nameOf = (flow: Flow, e: Edge) => e.label.trim() || titleOf(flow, e.to);

// ── drawing (the editor's, and a run's read-only view with each block's state) ──

export type StepState = { state: string; label: string };

/** Lay the blocks out in columns by how far they are from the start (arrows back are not counted). */
export function arrange(flow: Flow): void {
  const depth = new Map<string, number>([[flow.start || flow.steps[0]?.id, 0]]);
  const queue = [...depth.keys()];
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of outsOf(flow, id)) {
      if (!depth.has(e.to)) { depth.set(e.to, depth.get(id)! + 1); queue.push(e.to); }
    }
  }
  const rows = new Map<number, number>();
  for (const s of flow.steps) {
    const d = depth.get(s.id) ?? Math.max(0, ...depth.values()) + 1;  // not reached from the start: after the rest
    const r = rows.get(d) ?? 0;
    rows.set(d, r + 1);
    s.x = 40 + d * GAP_X;
    s.y = 40 + r * GAP_Y;
  }
}

/** An arrow's curve and the middle of it (where its name goes): forward arrows run right, from a block's
 * right side to the next one's left; an arrow back (to a block not to the right) runs below, from the
 * bottom of one to the bottom of the other. */
function geometry(a: Step, b: Step): { d: string; mx: number; my: number } {
  const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
  if (x2 >= x1 + 20) {
    const dx = Math.max(40, (x2 - x1) / 2);
    return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
  }
  const bx1 = a.x + W / 2 + 20, by1 = a.y + H, bx2 = b.x + W / 2 - 20, by2 = b.y + H;
  const low = Math.max(by1, by2) + 60;
  return { d: `M${bx1},${by1} C${bx1},${low} ${bx2},${low} ${bx2},${by2}`,
           mx: (bx1 + bx2) / 2, my: 0.125 * (by1 + by2) + 0.75 * low };
}

function clip(text: string, n: number): string {
  return text.length > n ? text.slice(0, n - 1) + '…' : text;
}

const textWidth = (t: string) => [...t].reduce((w, c) => w + (c.charCodeAt(0) > 0x2e80 ? 13 : 7.2), 0);

function blockShape(s: Step, opts: { selected?: boolean; start?: boolean; state?: StepState }): SVGGElement {
  const st = opts.state, missing = !st && lacks(s);
  return svg('g', { class: `flow-block${opts.selected ? ' selected' : ''}${st ? ' st-' + st.state : ''}${missing ? ' incomplete' : ''}`,
                    transform: `translate(${s.x},${s.y})`, 'data-step': s.id },
    svg('rect', { width: W, height: H, rx: 10 }),
    svg('text', { x: 14, y: 26, class: 'flow-title' }, (opts.start ? '▶ ' : '') + clip(s.title || s.id, 20)),
    svg('text', { x: 14, y: 48, class: 'flow-meta' }, (s.team ? t('팀') + ' · ' : '') + (s.model ? clip(s.model, 28) : t('모델 없음'))),
    svg('text', { x: 14, y: 70, class: 'flow-goal' },
      st ? st.label : missing ? t(missing) : clip(s.command.replace(/\s+/g, ' '), 28)),
    svg('circle', { class: 'port in', cx: 0, cy: H / 2, r: 6, 'data-port': 'in' }),
    svg('circle', { class: 'port out', cx: W, cy: H / 2, r: 7, 'data-port': 'out' }));
}

function edgeShape(flow: Flow, e: Edge, a: Step, b: Step, opts: { selected?: boolean; taken?: number; i?: number }): SVGGElement {
  const g = geometry(a, b);
  // a lone arrow named only for where it leads says nothing the drawing does not
  const named = outsOf(flow, e.from).length > 1 || (e.label.trim() !== '' && e.label.trim() !== titleOf(flow, e.to));
  const text = nameOf(flow, e) + (opts.taken ? ` ×${opts.taken}` : '');
  const w = textWidth(text) + 14;
  return svg('g', { class: `flow-edge-g${opts.selected ? ' selected' : ''}${opts.taken ? ' taken' : ''}`,
                    'data-edge': opts.i === undefined ? null : String(opts.i) },
    svg('path', { class: 'flow-edge-hit', d: g.d }),
    svg('path', { class: 'flow-edge', d: g.d, 'marker-end': 'url(#arrow)' }),
    (named || opts.taken) && svg('g', { class: 'flow-label', transform: `translate(${g.mx - w / 2},${g.my - 11})` },
      svg('rect', { width: w, height: 22, rx: 11 }), svg('text', { x: 7, y: 15 }, text)));
}

function arrowDefs(): SVGDefsElement {
  return svg('defs', null, svg('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7,
                                           markerHeight: 7, orient: 'auto-start-reverse' },
    svg('path', { d: 'M0,0 L10,5 L0,10 z', class: 'flow-arrowhead' })));
}

function bounds(flow: Flow): { x0: number; y0: number; x1: number; y1: number } {
  return { x0: Math.min(...flow.steps.map(s => s.x)) - 30, y0: Math.min(...flow.steps.map(s => s.y)) - 30,
           x1: Math.max(...flow.steps.map(s => s.x + W)) + 30, y1: Math.max(...flow.steps.map(s => s.y + H)) + 90 };
}

/** A flow drawn read-only: each block with its state, each arrow with how often it was taken. */
export function flowView(raw: Json, states: Record<string, StepState>, taken: Map<string, number>): SVGSVGElement {
  const flow = normalize(raw);
  const byId = new Map(flow.steps.map(s => [s.id, s]));
  const b = bounds(flow);
  return svg('svg', { class: 'flow-canvas view', viewBox: `${b.x0} ${b.y0} ${b.x1 - b.x0} ${b.y1 - b.y0}`,
                      preserveAspectRatio: 'xMinYMin meet' },
    arrowDefs(),
    flow.edges.map(e => byId.get(e.from) && byId.get(e.to) &&
      edgeShape(flow, e, byId.get(e.from)!, byId.get(e.to)!, { taken: taken.get(`${e.from}>${nameOf(flow, e)}`) })),
    flow.steps.map(s => blockShape(s, { start: s.id === flow.start, state: states[s.id] })));
}

const STATE: Record<string, string> = { done: n_('완료'), running: n_('실행 중'), waiting: n_('기다리는 중'), ready: n_('시작'),
                                        cancelled: n_('취소됨'), failed: n_('실패') };

/** A run's flow: each block's state (its last visit's, with the number of visits), the arrows taken,
 * and the path in words. */
export function flowProgress(run: Json): { states: Record<string, StepState>; taken: Map<string, number>; path: string[] } {
  const flow = normalize(run.flow);
  const byAgent = new Map<string, Json>();
  const walk = (nodes: Json[]) => nodes.forEach(n => { byAgent.set(n.id, n); walk(n.children); });
  walk(run.tree ?? []);
  const states: Record<string, StepState> = {}, visits = new Map<string, number>(), taken = new Map<string, number>();
  const path: string[] = [];
  for (const x of run.flow_path ?? []) {
    visits.set(x.step, (visits.get(x.step) ?? 0) + 1);
    const n = x.agent ? byAgent.get(x.agent) : null;
    const st = n ? (n.status || n.state || 'running') : 'waiting';
    const k = visits.get(x.step)!;
    states[x.step] = { state: st, label: (STATE[st] ? t(STATE[st]) : st) + (k > 1 ? ' · ' + t('{k}번째', { k }) : '') };
    if (x.next) {
      const key = `${x.step}>${x.next}`;
      taken.set(key, (taken.get(key) ?? 0) + 1);
    }
    path.push(titleOf(flow, x.step) + (x.next && outsOf(flow, x.step).length > 1 ? ` (${x.next})` : ''));
  }
  const over = run.state === 'closed' || run.phase === 'done' || run.phase === 'cancelled' || run.phase === 'failed';
  for (const s of flow.steps) {
    if (!states[s.id]) states[s.id] = over ? { state: 'skipped', label: t('거치지 않음') } : { state: 'idle', label: t('대기') };
  }
  return { states, taken, path };
}

// ── the list ────────────────────────────────────────────────────────────

/** The presets: each a flow, run now (with an input) or on its schedules, or opened to change. */
export async function presets(name?: string): Promise<void> {
  if (name) return editor(name === 'new' ? null : name);
  const [list, keys] = await Promise.all([agents.get('/presets') as Promise<Json[]>, agents.get('/keys') as Promise<Key[]>]);
  const mine = new Set(keys.map(k => k.ref));
  replace(main(),
    pageHead(t('프리셋'), agentTabs()),
    section(t('프리셋 ({n})', { n: list.length }),
      h('div', { class: 'actions' }, link('/agents/presets/new', t('새 프리셋'))),
      list.length ? list.map(p => presetItem(p, mine)) : empty(t('아직 프리셋이 없습니다. 새 프리셋으로 블럭 하나부터 시작하세요.'))));
}

/** One preset: what it runs, what it lacks, its schedules; run it with an input, or open it. */
export function presetItem(p: Json, mine: Set<string>): HTMLElement {
  const f = normalize(p.flow ?? {});
  const todo = f.steps.filter(s => lacks(s) || !mine.has(s.key)).length;
  const on = (p.schedules ?? []).filter((s: Json) => s.enabled);
  const input = h('input', { name: 'input', placeholder: p.goal ? t('입력 (비우면: {goal})', { goal: clip(p.goal, 30) }) : t('입력 (선택)') });
  return h('div', { class: 'item' },
    h('div', { class: 'item-head' }, link(`/agents/presets/${p.name}`, h('b', null, p.title)), h('code', null, p.name),
      h('span', { class: 'muted small' }, f.steps.length === 1 ? f.steps[0].model + (f.steps[0].team ? ' · ' + t('팀') : '')
        : t('블럭 {n}개', { n: f.steps.length }) + ' · ' + f.steps.map(s => s.title).join(' → ')),
      on.length > 0 && tag(t('예약 {n} · 다음 {when}', { n: on.length, when: when(Math.min(...on.map((s: Json) => s.next_at || Infinity))) }), 'ok'),
      todo > 0 && tag(t('블럭 {n}개 고칠 것 (키·모델·명령)', { n: todo }), 'warn')),
    form({ class: 'launch' }, async (_f, b) => {
      const body = input.value.trim() ? { goal: input.value } : undefined;
      const r = await act(b, () => body ? agents.post('/runs', { ...body, title: p.title, flow: p.flow, grant: p.grant })
        : agents.post(`/presets/${encodeURIComponent(p.name)}/run`));
      if (r) { flashNext('ok', t('{title}: 실행을 시작했습니다.', { title: p.title })); go(`/agents/runs/${r.id}`); }
    }, input, h('button', { disabled: todo > 0 }, t('실행')),
      link(`/agents/presets/${p.name}`, t('열기 · 예약'))));
}

// ── the editor ──────────────────────────────────────────────────────────

function starter(keys: Key[], example = false): Flow {
  const k = keys[0];
  const b = (id: string, title: string, command: string, x: number, y: number): Step =>
    ({ id, title, key: k?.ref ?? '', model: k?.models[0] ?? '', command, team: false, x, y });
  if (!example) return { steps: [b('s1', t('실행'), '', 40, 60)], edges: [], start: 's1', max_visits: 3 };
  return {
    steps: [b('s1', t('작성'), t('입력에 맞는 초안을 쓴다.'), 40, 60),
            b('s2', t('검토'), t('받은 초안을 검토한다. 고칠 점이 있으면 무엇을 고칠지 적고 "{fix}"를, 충분하면 "{pass}"를 고른다.',
              { fix: t('고쳐'), pass: t('통과') }), 40 + GAP_X, 60),
            b('s3', t('정리'), t('통과한 초안을 최종 결과로 정리한다.'), 40 + 2 * GAP_X, 60)],
    edges: [{ from: 's1', to: 's2', label: '' }, { from: 's2', to: 's1', label: t('고쳐') }, { from: 's2', to: 's3', label: t('통과') }],
    start: 's1', max_visits: 3,
  };
}

async function editor(name: string | null): Promise<void> {
  const from = name ? null : new URLSearchParams(location.search).get('from');  // a past run, to start again
  const [keys, opts, list, past] = await Promise.all([agents.get('/keys') as Promise<Key[]>, agents.get('/options') as Promise<Options>,
    name ? agents.get('/presets') as Promise<Json[]> : Promise.resolve([]),
    from ? agents.get(`/runs/${encodeURIComponent(from)}`) : Promise.resolve(null)]);
  const preset = name ? list.find(p => p.name === name) : null;
  if (name && !preset) throw new Error(t('프리셋 {name}이(가) 없습니다.', { name }));
  // what the page starts from: the preset, or a past run's recipe (always a flow), or one empty block
  const recipe = past?.recipe;
  const start = preset ? { flow: preset.flow, input: preset.goal, title: preset.title, grant: preset.grant }
    : recipe ? { flow: recipe.flow, input: recipe.input, title: recipe.title.replace(/ · \d\d-\d\d \d\d:\d\d$/, ''), grant: recipe.grant }
      : null;
  let flow: Flow = start?.flow ? normalize(start.flow) : starter(keys);
  if (recipe && !flow.steps.some(s => s.x || s.y)) arrange(flow);
  const byRef = new Map(keys.map(k => [k.ref, k]));
  const gf = grantForm(opts, start?.grant);
  let sel: { kind: 'step' | 'edge'; id: string } | null = null;
  let dirty = !preset;
  const view = { x: 0, y: 0, k: 1 };

  const canvas = svg('svg', { class: 'flow-canvas', tabindex: 0 });
  const world = svg('g');
  canvas.append(arrowDefs(), world);
  const panel = h('div', { class: 'flow-panel' });
  const unsaved = h('span', { class: 'muted small' });
  const changed = () => { dirty = true; unsaved.textContent = t('저장하지 않은 변경이 있습니다'); };
  if (dirty) changed();

  const step = (id: string) => flow.steps.find(s => s.id === id);
  const edgeId = (e: Edge) => `${e.from}>${e.to}`;

  function drawShapes(): void {  // the blocks and arrows (the panel keeps its focus while one types in it)
    world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
    const byId = new Map(flow.steps.map(s => [s.id, s]));
    replace(world,
      flow.edges.map((e, i) => {
        const a = byId.get(e.from), b = byId.get(e.to);
        return a && b && edgeShape(flow, e, a, b, { selected: sel?.kind === 'edge' && sel.id === edgeId(e), i });
      }),
      flow.steps.map(s => blockShape(s, { selected: sel?.kind === 'step' && sel.id === s.id, start: s.id === flow.start })));
  }

  function draw(): void {
    drawShapes();
    drawPanel();
  }

  const field = (label: string, hint: string, el: HTMLElement) =>
    h('label', null, label, hint && [' ', h('span', { class: 'muted small' }, hint)], el);

  function nextActions(s: Step): HTMLElement {
    const out = outsOf(flow, s.id);
    const others = flow.steps.filter(o => o.id !== s.id && !out.some(e => e.to === o.id));
    const pick = h('select', null, h('option', { value: '' }, t('다음 블럭 고르기…')),
      others.map(o => h('option', { value: o.id }, o.title)), h('option', { value: '+' }, '+ ' + t('새 블럭')));
    pick.addEventListener('change', () => {
      let to = pick.value;
      if (!to) return;
      if (to === '+') to = addStep(s).id;
      flow.edges.push({ from: s.id, to, label: '' });
      changed();
      sel = { kind: 'step', id: s.id };
      draw();
    });
    return h('div', { class: 'next-actions' },
      h('h3', null, t('다음 동작')),
      h('p', { class: 'muted small' }, out.length > 1
        ? t('이 블럭의 모델이 끝날 때 결과를 보고 아래 이름 중 하나를 고릅니다. 명령에 언제 무엇을 고를지 적어 두세요.')
        : out.length === 1 ? t('끝나면 언제나 {next}(으)로 결과를 넘깁니다.', { next: titleOf(flow, out[0].to) })
          : t('여기서 끝납니다. 이 블럭의 결과가 실행의 결과가 됩니다.')),
      out.map(e => h('div', { class: 'next-row' },
        h('input', { value: e.label, placeholder: titleOf(flow, e.to), maxlength: 60, 'aria-label': t('이름'),
                     oninput: (ev: Event) => { e.label = (ev.target as HTMLInputElement).value; changed(); drawShapes(); } }),
        h('span', { class: 'small' }, `→ ${titleOf(flow, e.to)}`),
        h('button', { type: 'button', class: 'link danger-text', title: t('이 동작 빼기'), onclick: () => {
          flow.edges = flow.edges.filter(x => x !== e);
          changed();
          draw();
        } }, '✕'))),
      h('div', { class: 'actions' }, pick));
  }

  function drawPanel(): void {
    if (sel?.kind === 'edge') {
      const e = flow.edges.find(x => edgeId(x) === sel!.id);
      if (!e) { sel = null; return drawPanel(); }
      replace(panel, h('h3', null, t('화살표')),
        h('p', { class: 'small' }, `${titleOf(flow, e.from)} → ${titleOf(flow, e.to)}`),
        field(t('이름'), t('모델이 고를 때 쓰는 이름'), h('input', { value: e.label, placeholder: titleOf(flow, e.to), maxlength: 60,
          oninput: (ev: Event) => { e.label = (ev.target as HTMLInputElement).value; changed(); drawShapes(); } })),
        h('p', { class: 'muted small' }, t('앞 블럭의 결과 글과 노트가 다음 블럭의 명령 뒤에 붙어 넘어갑니다.')),
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary', onclick: removeSelected }, t('화살표 지우기'))));
      return;
    }
    const s = sel?.kind === 'step' ? step(sel.id) : null;
    if (!s) {
      replace(panel, h('h3', null, t('사용법')),
        h('p', { class: 'muted small' }, t('블럭을 누르면 여기서 키·모델·명령과 다음 동작을 정합니다. 블럭 오른쪽의 점을 다른 블럭으로 끌어도 화살표가 생깁니다. 빈 곳을 끌면 화면이 움직이고, 휠로 확대합니다. 선택한 것은 Delete 키로 지웁니다.')),
        h('p', { class: 'muted small' }, t('▶ 표시가 시작 블럭입니다. 실행의 입력은 시작 블럭이 받고, 화살표가 없는 블럭에서 끝납니다.')));
      return;
    }
    const k = byRef.get(s.key);
    replace(panel,
      h('h3', null, t('블럭')),
      field(t('이름'), '', h('input', { value: s.title, maxlength: 80, oninput: (e: Event) => {
        s.title = (e.target as HTMLInputElement).value; changed(); drawShapes(); } })),
      keys.length
        ? field(t('키'), '', h('select', { onchange: (e: Event) => {
            s.key = (e.target as HTMLSelectElement).value;
            s.model = byRef.get(s.key)?.models[0] ?? '';  // the models are the key's own
            changed(); draw();
          } },
            !k && h('option', { value: '', selected: true }, s.key ? t('{key} (등록되지 않은 키)', { key: s.key }) : t('키 고르기…')),
            keys.map(x => h('option', { value: x.ref, selected: x.ref === s.key }, keyLabel(x)))))
        : h('p', { class: 'flash error' }, t('먼저 API 키를 등록하세요.'), ' ', link('/agents/keys', t('API 키 등록'))),
      k && field(t('모델'), t('이 키의 모델'), modelPicker(k.models, s.model, m => {
        if (m !== s.model) { s.model = m; changed(); drawShapes(); } })),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: s.team, onchange: (e: Event) => {
        s.team = (e.target as HTMLInputElement).checked; changed(); drawShapes(); } }), t('팀으로 실행')),
      h('p', { class: 'muted small' }, t('켜면 이 블럭의 에이전트가 일을 나눠 하위 에이전트에게 맡기고 결과를 모읍니다.')),
      field(t('명령'), t('이 블럭이 할 일'), h('textarea', { rows: 7, oninput: (e: Event) => {
        s.command = (e.target as HTMLTextAreaElement).value; changed(); drawShapes(); } }, s.command)),
      h('p', { class: 'muted small' }, s.id === flow.start
        ? t('시작 블럭: 명령과 함께 실행의 입력을 받습니다.')
        : t('앞 블럭의 결과가 이 명령 뒤에 붙어 전달됩니다.')),
      nextActions(s),
      h('div', { class: 'actions' },
        s.id !== flow.start && h('button', { type: 'button', class: 'secondary', onclick: () => {
          flow.start = s.id; changed(); draw(); } }, t('여기서 시작')),
        h('button', { type: 'button', class: 'secondary', onclick: removeSelected }, t('블럭 지우기'))));
  }

  function removeSelected(): void {
    if (!sel) return;
    if (sel.kind === 'step') {
      const id = sel.id;
      flow.steps = flow.steps.filter(s => s.id !== id);
      flow.edges = flow.edges.filter(e => e.from !== id && e.to !== id);
      if (flow.start === id) flow.start = flow.steps[0]?.id ?? '';
    } else {
      flow.edges = flow.edges.filter(e => edgeId(e) !== sel!.id);
    }
    sel = null;
    changed();
    draw();
  }

  /** A new block, after `after` (to its right) or below the chosen one, in the first free place. */
  function addStep(after?: Step): Step {
    let n = flow.steps.length + 1;
    while (step(`s${n}`)) n++;
    const at = after ?? (sel?.kind === 'step' ? step(sel.id) : undefined) ?? flow.steps[flow.steps.length - 1];
    const x = at ? at.x + (after ? GAP_X : 0) : 40;
    let y = at ? at.y + (after ? 0 : GAP_Y) : 60;
    while (flow.steps.some(o => Math.abs(o.x - x) < W && Math.abs(o.y - y) < H + 10)) y += GAP_Y;
    const base = (at && byRef.get(at.key)) ?? keys[0];
    const s: Step = { id: `s${n}`, title: t('블럭 {n}', { n }), key: at?.key || base?.ref || '', model: at?.model || base?.models[0] || '',
                      command: '', team: false, x, y };
    flow.steps.push(s);
    if (!flow.start) flow.start = s.id;
    sel = { kind: 'step', id: s.id };
    changed();
    draw();
    fit(false);
    return s;
  }

  /** Bring every block into view (zoomed out if need be, never in past 1). `always`: even if they are. */
  function fit(always = true): void {
    if (!flow.steps.length) return;
    const r = canvas.getBoundingClientRect();
    const { x0, y0, x1, y1 } = bounds(flow);
    const inside = x0 * view.k + view.x >= 0 && y0 * view.k + view.y >= 0 &&
      x1 * view.k + view.x <= r.width && y1 * view.k + view.y <= r.height;
    if (inside && !always) return;
    view.k = Math.min(1, r.width / (x1 - x0), r.height / (y1 - y0));
    view.x = (r.width - (x1 - x0) * view.k) / 2 - x0 * view.k;
    view.y = (r.height - (y1 - y0) * view.k) / 2 - y0 * view.k;
    drawShapes();
  }

  // ── pointer: move a block, draw an arrow, pan; the wheel zooms ──
  const toWorld = (ev: PointerEvent | WheelEvent) => {
    const r = canvas.getBoundingClientRect();
    return { x: (ev.clientX - r.left - view.x) / view.k, y: (ev.clientY - r.top - view.y) / view.k };
  };
  let drag: { kind: 'move'; step: Step; dx: number; dy: number; moved: boolean }
    | { kind: 'link'; from: Step; line: SVGPathElement } | { kind: 'pan'; x: number; y: number; vx: number; vy: number } | null = null;

  canvas.addEventListener('pointerdown', ev => {
    const target = ev.target as Element;
    const block = target.closest('[data-step]');
    const edge = target.closest('[data-edge]');
    const p = toWorld(ev);
    canvas.setPointerCapture(ev.pointerId);
    if (block) {
      const s = step(block.getAttribute('data-step')!)!;
      if (target.getAttribute('data-port') === 'out') {
        const line = svg('path', { class: 'flow-edge drawing' });
        world.append(line);
        drag = { kind: 'link', from: s, line };
      } else {
        drag = { kind: 'move', step: s, dx: p.x - s.x, dy: p.y - s.y, moved: false };
        if (sel?.kind !== 'step' || sel.id !== s.id) { sel = { kind: 'step', id: s.id }; draw(); }
      }
    } else if (edge) {
      const e = flow.edges[Number(edge.getAttribute('data-edge'))];
      sel = { kind: 'edge', id: edgeId(e) };
      draw();
    } else {
      drag = { kind: 'pan', x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y };
      canvas.classList.add('panning');
    }
  });
  canvas.addEventListener('pointermove', ev => {
    if (!drag) return;
    const p = toWorld(ev);
    if (drag.kind === 'move') {
      drag.step.x = Math.round(p.x - drag.dx);
      drag.step.y = Math.round(p.y - drag.dy);
      if (!drag.moved) { drag.moved = true; changed(); }
      drawShapes();
    } else if (drag.kind === 'link') {
      const a = drag.from;
      drag.line.setAttribute('d', `M${a.x + W},${a.y + H / 2} L${p.x},${p.y}`);
    } else {
      view.x = drag.vx + ev.clientX - drag.x;
      view.y = drag.vy + ev.clientY - drag.y;
      world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
    }
  });
  canvas.addEventListener('pointerup', ev => {
    if (drag?.kind === 'link') {
      drag.line.remove();
      const over = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('[data-step]');
      const to = over?.getAttribute('data-step');
      const from = drag.from.id;
      if (to && to !== from && !flow.edges.some(e => e.from === from && e.to === to)) {
        flow.edges.push({ from, to, label: '' });
        changed();
        sel = { kind: 'step', id: from };  // its panel: the new next action, to name
      }
      draw();
    }
    canvas.classList.remove('panning');
    drag = null;
  });
  canvas.addEventListener('wheel', ev => {
    ev.preventDefault();
    const r = canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const k = Math.min(2, Math.max(0.3, view.k * (ev.deltaY < 0 ? 1.1 : 1 / 1.1)));
    view.x = mx - (mx - view.x) * (k / view.k);
    view.y = my - (my - view.y) * (k / view.k);
    view.k = k;
    world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  }, { passive: false });
  canvas.addEventListener('keydown', ev => {
    if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel) { ev.preventDefault(); removeSelected(); }
  });

  // ── saving, running, scheduling ──
  /** What is missing, said here before the server is asked (and the block that lacks it chosen). */
  function problems(): string | null {
    if (!flow.steps.length) return t('블럭이 하나도 없습니다.');
    for (const s of flow.steps) {
      const what = lacks(s);
      if (what) { sel = { kind: 'step', id: s.id }; draw(); return t('블럭 「{title}」: {what}', { title: s.title, what: t(what) }); }
      const out = outsOf(flow, s.id).map(e => nameOf(flow, e).toLowerCase());
      if (new Set(out).size !== out.length) {
        sel = { kind: 'step', id: s.id }; draw();
        return t('블럭 「{title}」의 다음 동작 이름이 겹칩니다. 서로 다른 이름을 붙이세요.', { title: s.title });
      }
    }
    return null;
  }

  async function save(b: HTMLButtonElement | null, f: HTMLFormElement, then: 'stay' | 'run' | 'once'): Promise<void> {
    const bad = problems();
    if (bad) { flash('error', bad); return; }
    const v = values(f);
    if (then === 'once') {  // run as it is on the page, keeping nothing
      const r = await act(b, () => agents.post('/runs', { goal: v.goal, title: v.title || (preset?.title ?? ''), grant: gf.grant(), flow }));
      if (r) { flashNext('ok', t('실행을 시작했습니다.')); go(`/agents/runs/${r.id}`); }
      return;
    }
    if (!name && !String(v.name).trim()) { flash('error', t('저장하려면 이름을 적으세요 (저장 없이 실행만 해도 됩니다).')); return; }
    const id = name ?? String(v.name);
    const body = { goal: v.goal, title: v.title, grant: gf.grant(), flow };
    const p = await act(b, () => agents.put(`/presets/${encodeURIComponent(id)}`, body));
    if (!p) return;  // refused: everything stays as it was typed
    dirty = false;
    unsaved.textContent = '';
    if (then === 'run') {
      const r = await act(b, () => agents.post(`/presets/${encodeURIComponent(id)}/run`));
      if (r) { flashNext('ok', t('순서도대로 실행을 시작했습니다.')); go(`/agents/runs/${r.id}`); }
    } else if (!name) {
      flashNext('ok', t('저장했습니다. 이제 바로 실행하거나 예약할 수 있습니다.'));
      go(`/agents/presets/${p.name}`);
    }
  }

  const visits = h('input', { type: 'number', min: 1, max: 20, value: flow.max_visits, class: 'short', oninput: () => {
    flow.max_visits = Math.max(1, Math.min(20, Math.round(Number(visits.value) || 3))); changed(); } });
  const head = form({}, async (f, b) => save(b, f, (b?.value as 'stay' | 'run' | 'once') ?? 'stay'),
    past && h('p', { class: 'flash ok' }, t('지난 실행의 설정을 불러왔습니다:'), ' ', link(`/agents/runs/${past.id}`, past.title || past.id), '. ',
      t('그대로 또는 고쳐서 실행하고, 이름을 적으면 프리셋으로 남깁니다.')),
    h('div', { class: 'cols' },
      h('label', null, t('이름'), ' ', h('span', { class: 'muted small' }, name ? '' : t('영문 소문자·숫자·.-_ (저장할 때만)')),
        h('input', { name: 'name', pattern: '[a-z0-9][a-z0-9._\\-]*', value: preset?.name ?? '', readonly: !!name })),
      h('label', null, t('제목'), h('input', { name: 'title', value: start?.title ?? '', oninput: changed }))),
    h('label', null, t('입력'), ' ', h('span', { class: 'muted small' }, t('실행마다 시작 블럭에 주는 내용 (없어도 됩니다).'), ' ',
      t('입력과 명령의 {date}·{time}은 실행한 때로 바뀝니다')),
      h('textarea', { name: 'goal', rows: 2, oninput: changed }, start?.input ?? '')),
    h('div', { class: 'actions' },
      h('button', { value: 'stay' }, t('저장')),
      h('button', { value: 'run', class: 'secondary' }, t('저장하고 실행')),
      h('button', { value: 'once', class: 'secondary' }, t('저장 없이 실행')),
      unsaved));

  const schedules = h('div');
  async function drawSchedules(): Promise<void> {
    const p = name ? ((await agents.get('/presets')) as Json[]).find(x => x.name === name) : null;
    if (!p) { replace(schedules, h('p', { class: 'muted small' }, t('저장하면 여기서 예약할 수 있습니다.'))); return; }
    const s = scheduling(p.name, p.schedules, drawSchedules);
    replace(schedules, h('p', { class: 'muted small' }, cronHelp()), s.add, s.list);
  }

  replace(main(),
    pageHead(preset ? preset.title : past ? t('지난 실행으로 새 실행') : t('새 프리셋'), agentTabs()), h('p', { class: 'muted' }, [link('/agents/presets', t('프리셋 목록')),
      ' · ', t('블럭마다 키·모델·명령을 정하고, 끝난 뒤 어디로 갈지를 다음 동작(화살표)으로 잇습니다.')]),
    !keys.length && h('p', { class: 'flash error' }, t('블럭에 쓸 API 키가 없습니다. 먼저 등록하세요.'), ' ', link('/agents/keys', t('API 키 등록'))),
    section(t('순서도'), head),
    section(t('흐름'),
      h('div', { class: 'actions' },
        h('button', { type: 'button', onclick: () => addStep() }, t('블럭 추가')),
        h('button', { type: 'button', class: 'secondary', onclick: () => { arrange(flow); changed(); draw(); fit(); } }, t('자동 정렬')),
        h('button', { type: 'button', class: 'secondary', onclick: () => fit() }, t('전체 보기')),
        !preset && !past && h('button', { type: 'button', class: 'secondary', onclick: () => {
          if (flow.steps.some(s => s.command.trim()) && !confirm(t('지금 블럭을 지우고 작성·검토 예시로 바꿀까요?'))) return;
          flow = starter(keys, true); sel = null; changed(); draw(); fit();
        } }, t('예시: 작성 → 검토 반복')),
        h('label', { class: 'inline-field' }, t('한 블럭 최대 반복 (회)'), ' ', visits)),
      h('div', { class: 'flow-editor' }, canvas, panel)),
    section(t('예약'), schedules),
    h('details', { class: 'panel' }, h('summary', null, t('한도 · 실행 환경')),
      h('p', { class: 'muted small' }, t('라우팅은 블럭의 키·모델로 정해집니다. 여기서는 턴·토큰 한도와 샌드박스 정책을 정합니다.')), gf.el));
  gf.el.addEventListener('input', changed);
  gf.el.addEventListener('change', changed);
  draw();
  void drawSchedules();
  // once the canvas has its size, and whenever it changes (a narrow window, a turned phone)
  let width = 0;
  new ResizeObserver(() => {
    const w = canvas.getBoundingClientRect().width;
    if (w && Math.abs(w - width) > 1) { width = w; fit(); }
  }).observe(canvas);
}
