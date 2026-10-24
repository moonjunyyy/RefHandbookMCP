// The flow designer: a run drawn as blocks (steps: one agent each) and arrows (a step's result passed
// to the next). Blocks move by dragging; an arrow is drawn from a block's right dot to another's left
// one; the background pans, the wheel zooms. A flow is kept as a preset (/agents/api/v1/presets), so
// it runs now or on a schedule. The backend checks it (agents/flows.py) and says what is wrong.

import { agents, Json } from '../lib/api';
import { h, replace, svg, values } from '../lib/dom';
import { act, empty, flashNext, form, go, link, main, pageHead, section } from '../lib/ui';
import { grantForm, Key, Options, roleName } from './grant';

export interface Step { id: string; title: string; role: string; model: string; goal: string; x: number; y: number }
export interface Edge { from: string; to: string }
export interface Flow { steps: Step[]; edges: Edge[] }

const TABS = [{ href: '/agents/', label: '실행' }, { href: '/agents/flows', label: '순서도' },
  { href: '/agents/presets', label: '프리셋 · 예약' }, { href: '/agents/keys', label: 'API 키' },
  { href: '/agents/files', label: '파일' }, { href: '/approvals', label: '승인' }];
const W = 210, H = 86, GAP_X = 270, GAP_Y = 120;

// ── drawing (the editor's, and a run's read-only view with each step's state) ──

export type StepState = { state: string; label: string };

function layers(flow: Flow): Map<string, number> {
  const depth = new Map<string, number>();
  const before = (id: string) => flow.edges.filter(e => e.to === id).map(e => e.from);
  const visit = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0;  // a cycle (the backend refuses it): drawn anyway
    seen.add(id);
    const d = Math.max(-1, ...before(id).map(b => visit(b, seen))) + 1;
    depth.set(id, d);
    return d;
  };
  flow.steps.forEach(s => visit(s.id, new Set()));
  return depth;
}

/** Lay the steps out in columns by how many steps come before them. */
export function arrange(flow: Flow): void {
  const depth = layers(flow);
  const rows = new Map<number, number>();
  for (const s of flow.steps) {
    const d = depth.get(s.id) ?? 0;
    const r = rows.get(d) ?? 0;
    rows.set(d, r + 1);
    s.x = 40 + d * GAP_X;
    s.y = 40 + r * GAP_Y;
  }
}

function edgePath(a: Step, b: Step): string {
  const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

function clip(text: string, n: number): string {
  return text.length > n ? text.slice(0, n - 1) + '…' : text;
}

function blockShape(s: Step, opts: { selected?: boolean; state?: StepState }): SVGGElement {
  const st = opts.state;
  return svg('g', { class: `flow-block${opts.selected ? ' selected' : ''}${st ? ' st-' + st.state : ''}`,
                    transform: `translate(${s.x},${s.y})`, 'data-step': s.id },
    svg('rect', { width: W, height: H, rx: 10 }),
    svg('text', { x: 14, y: 26, class: 'flow-title' }, clip(s.title || s.id, 22)),
    svg('text', { x: 14, y: 48, class: 'flow-meta' }, `${roleName(s.role)} · ${clip(s.model || '역할의 첫 경로', 20)}`),
    svg('text', { x: 14, y: 70, class: 'flow-goal' }, clip(st ? st.label : s.goal.replace(/\s+/g, ' '), 28)),
    svg('circle', { class: 'port in', cx: 0, cy: H / 2, r: 6, 'data-port': 'in' }),
    svg('circle', { class: 'port out', cx: W, cy: H / 2, r: 6, 'data-port': 'out' }));
}

function arrowDefs(): SVGDefsElement {
  return svg('defs', null, svg('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7,
                                           markerHeight: 7, orient: 'auto-start-reverse' },
    svg('path', { d: 'M0,0 L10,5 L0,10 z', class: 'flow-arrowhead' })));
}

/** A flow drawn read-only, each step with its state (a run's page). */
export function flowView(flow: Flow, states: Record<string, StepState>): SVGSVGElement {
  const byId = new Map(flow.steps.map(s => [s.id, s]));
  const w = Math.max(...flow.steps.map(s => s.x)) + W + 40, hh = Math.max(...flow.steps.map(s => s.y)) + H + 40;
  return svg('svg', { class: 'flow-canvas view', viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: 'xMinYMin meet' },
    arrowDefs(),
    flow.edges.map(e => byId.get(e.from) && byId.get(e.to) &&
      svg('path', { class: 'flow-edge', d: edgePath(byId.get(e.from)!, byId.get(e.to)!), 'marker-end': 'url(#arrow)' })),
    flow.steps.map(s => blockShape(s, { state: states[s.id] ?? { state: 'waiting', label: '대기' } })));
}

// ── the list ────────────────────────────────────────────────────────────

export async function flows(name?: string): Promise<void> {
  if (name) return editor(name === 'new' ? null : name);
  const list = ((await agents.get('/presets')) as Json[]).filter(p => p.flow);
  replace(main(),
    pageHead('순서도', '에이전트 단계를 블럭으로 놓고 화살표로 이어, 실행이 그 흐름을 따르게 합니다. 순서도는 프리셋으로 저장되어 ' +
      '바로 실행하거나 예약할 수 있습니다.', TABS),
    section(`순서도 (${list.length})`,
      h('div', { class: 'actions' }, link('/agents/flows/new', h('span', { class: 'button' }, '새 순서도'))),
      list.length ? list.map(p => h('div', { class: 'item' },
        h('div', { class: 'item-head' }, link(`/agents/flows/${p.name}`, h('b', null, p.title)), h('code', null, p.name),
          h('span', { class: 'muted small' }, `단계 ${p.flow.steps.length} · 화살표 ${p.flow.edges.length}` +
            (p.schedules.length ? ` · 예약 ${p.schedules.length}` : ''))),
        h('p', { class: 'small' }, p.goal))) : empty('아직 순서도가 없습니다.')));
}

// ── the editor ──────────────────────────────────────────────────────────

async function editor(name: string | null): Promise<void> {
  const [keys, opts, presets] = await Promise.all([agents.get('/keys') as Promise<Key[]>, agents.get('/options') as Promise<Options>,
    name ? agents.get('/presets') as Promise<Json[]> : Promise.resolve([])]);
  const preset = name ? presets.find(p => p.name === name) : null;
  if (name && !preset) throw new Error(`순서도 ${name}이(가) 없습니다.`);
  const flow: Flow = preset?.flow
    ? { steps: preset.flow.steps.map((s: Step) => ({ ...s })), edges: preset.flow.edges.map((e: Edge) => ({ ...e })) }
    : { steps: [{ id: 's1', title: '계획', role: 'lead', model: '', goal: '할 일을 나누어 정리한다', x: 40, y: 60 },
                { id: 's2', title: '실행', role: 'worker', model: '', goal: '정리된 할 일을 한다', x: 40 + GAP_X, y: 60 }],
        edges: [{ from: 's1', to: 's2' }] };
  const gf = grantForm(keys, opts, preset?.grant);
  let sel: { kind: 'step' | 'edge'; id: string } | null = flow.steps.length ? { kind: 'step', id: flow.steps[0].id } : null;
  const view = { x: 0, y: 0, k: 1 };

  const canvas = svg('svg', { class: 'flow-canvas', tabindex: 0 });
  const world = svg('g');
  canvas.append(arrowDefs(), world);
  const panel = h('div', { class: 'flow-panel' });

  // ── what the grant's routes offer each role (the model choices of a block) ──
  const modelsFor = (role: string): string[] =>
    [...new Set((gf.grant().routes as Json[]).filter(r => r.roles.includes(role)).map(r => r.model as string))];

  function drawShapes(): void {  // the blocks and arrows (the panel keeps its focus while one types in it)
    world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
    const byId = new Map(flow.steps.map(s => [s.id, s]));
    replace(world,
      flow.edges.map((e, i) => {
        const a = byId.get(e.from), b = byId.get(e.to);
        if (!a || !b) return null;
        return svg('g', { class: `flow-edge-g${sel?.kind === 'edge' && sel.id === `${e.from}>${e.to}` ? ' selected' : ''}`,
                          'data-edge': String(i) },
          svg('path', { class: 'flow-edge-hit', d: edgePath(a, b) }),
          svg('path', { class: 'flow-edge', d: edgePath(a, b), 'marker-end': 'url(#arrow)' }));
      }),
      flow.steps.map(s => blockShape(s, { selected: sel?.kind === 'step' && sel.id === s.id })));
  }

  function draw(): void {
    drawShapes();
    drawPanel();
  }

  function drawPanel(): void {
    const s = sel?.kind === 'step' ? flow.steps.find(x => x.id === sel!.id) : null;
    if (sel?.kind === 'edge') {
      const [a, b] = sel.id.split('>');
      replace(panel, h('h3', null, '화살표'),
        h('p', { class: 'small' }, `${flow.steps.find(x => x.id === a)?.title} → ${flow.steps.find(x => x.id === b)?.title}`),
        h('p', { class: 'muted small' }, '앞 단계의 결과 글과 노트가 다음 단계로 넘어갑니다.'),
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary', onclick: removeSelected }, '화살표 지우기')));
      return;
    }
    if (!s) {
      replace(panel, h('p', { class: 'muted small' }, '블럭을 누르면 여기서 고칩니다. 블럭의 오른쪽 점에서 다른 블럭의 왼쪽 점으로 ' +
        '끌면 화살표가 생깁니다. 빈 곳을 끌면 화면이 움직이고, 휠로 확대합니다. 선택한 것은 Delete 키로 지웁니다.'));
      return;
    }
    const models = modelsFor(s.role);
    replace(panel,
      h('h3', null, '블럭'),
      h('label', null, '이름', h('input', { value: s.title, maxlength: 80, oninput: (e: Event) => { s.title = (e.target as HTMLInputElement).value; drawShapes(); } })),
      h('label', null, '역할', h('select', { onchange: (e: Event) => { s.role = (e.target as HTMLSelectElement).value;
          if (s.model && !modelsFor(s.role).includes(s.model)) s.model = ''; draw(); } },
        opts.roles.map(r => h('option', { value: r, selected: r === s.role }, roleName(r))))),
      h('label', null, '모델 ', h('span', { class: 'muted small' }, '이 역할을 맡는 경로의 모델'),
        h('select', { onchange: (e: Event) => { s.model = (e.target as HTMLSelectElement).value; drawShapes(); } },
          h('option', { value: '', selected: !s.model }, '역할의 첫 경로'),
          models.map(m => h('option', { value: m, selected: m === s.model }, m)))),
      !models.length && h('p', { class: 'flash error' }, `허가의 라우팅에 ${roleName(s.role)} 역할이 없습니다.`),
      h('label', null, '목표', h('textarea', { rows: 6, oninput: (e: Event) => { s.goal = (e.target as HTMLTextAreaElement).value; drawShapes(); } }, s.goal)),
      h('p', { class: 'muted small' }, `앞 단계: ${flow.edges.filter(e => e.to === s.id).map(e => flow.steps.find(x => x.id === e.from)?.title).join(', ') || '없음 (처음 단계)'}`),
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary', onclick: removeSelected }, '블럭 지우기')));
  }

  function removeSelected(): void {
    if (!sel) return;
    if (sel.kind === 'step') {
      const id = sel.id;
      flow.steps = flow.steps.filter(s => s.id !== id);
      flow.edges = flow.edges.filter(e => e.from !== id && e.to !== id);
    } else {
      flow.edges = flow.edges.filter(e => `${e.from}>${e.to}` !== sel!.id);
    }
    sel = null;
    draw();
  }

  function addStep(): void {
    let n = flow.steps.length + 1;
    while (flow.steps.some(s => s.id === `s${n}`)) n++;
    // below the chosen block (or the first column), in the first free place of that column
    const at = (sel?.kind === 'step' && flow.steps.find(x => x.id === sel!.id)) || flow.steps[0];
    const x = at ? at.x : 40;
    let y = at ? at.y + GAP_Y : 60;
    while (flow.steps.some(o => Math.abs(o.x - x) < W && Math.abs(o.y - y) < H + 10)) y += GAP_Y;
    const s: Step = { id: `s${n}`, title: `단계 ${n}`, role: 'worker', model: '', goal: '', x, y };
    flow.steps.push(s);
    sel = { kind: 'step', id: s.id };
    draw();
    fit(false);
  }

  /** Bring every block into view (zoomed out if need be, never in past 1). `always`: even if they are. */
  function fit(always = true): void {
    if (!flow.steps.length) return;
    const r = canvas.getBoundingClientRect();
    const x0 = Math.min(...flow.steps.map(s => s.x)) - 30, y0 = Math.min(...flow.steps.map(s => s.y)) - 30;
    const x1 = Math.max(...flow.steps.map(s => s.x + W)) + 30, y1 = Math.max(...flow.steps.map(s => s.y + H)) + 30;
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
  let drag: { kind: 'move'; step: Step; dx: number; dy: number } | { kind: 'link'; from: Step; line: SVGPathElement }
    | { kind: 'pan'; x: number; y: number; vx: number; vy: number } | null = null;

  canvas.addEventListener('pointerdown', ev => {
    const target = ev.target as Element;
    const block = target.closest('[data-step]');
    const edge = target.closest('[data-edge]');
    const p = toWorld(ev);
    canvas.setPointerCapture(ev.pointerId);
    if (block) {
      const step = flow.steps.find(s => s.id === block.getAttribute('data-step'))!;
      if (target.getAttribute('data-port') === 'out') {
        const line = svg('path', { class: 'flow-edge drawing' });
        world.append(line);
        drag = { kind: 'link', from: step, line };
      } else {
        drag = { kind: 'move', step, dx: p.x - step.x, dy: p.y - step.y };
        if (sel?.kind !== 'step' || sel.id !== step.id) { sel = { kind: 'step', id: step.id }; draw(); }
      }
    } else if (edge) {
      const e = flow.edges[Number(edge.getAttribute('data-edge'))];
      sel = { kind: 'edge', id: `${e.from}>${e.to}` };
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
        flow.edges.push({ from, to });
        sel = { kind: 'edge', id: `${from}>${to}` };
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
    const k = Math.min(2, Math.max(0.4, view.k * (ev.deltaY < 0 ? 1.1 : 1 / 1.1)));
    view.x = mx - (mx - view.x) * (k / view.k);
    view.y = my - (my - view.y) * (k / view.k);
    view.k = k;
    world.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
  }, { passive: false });
  canvas.addEventListener('keydown', ev => {
    if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel) { ev.preventDefault(); removeSelected(); }
  });

  // ── saving and running ──
  async function save(b: HTMLButtonElement | null, f: HTMLFormElement, then: 'stay' | 'run'): Promise<void> {
    const v = values(f);
    const id = name ?? String(v.name);
    const body = { goal: v.goal, title: v.title, grant: gf.grant(), flow };
    const p = await act(b, () => agents.put(`/presets/${encodeURIComponent(id)}`, body), then === 'stay' ? '저장했습니다.' : undefined);
    if (!p) return;
    if (then === 'run') {
      const r = await act(b, () => agents.post(`/presets/${encodeURIComponent(id)}/run`));
      if (r) { flashNext('ok', '순서도대로 실행을 시작했습니다.'); go(`/agents/runs/${r.id}`); }
    } else if (!name) {
      flashNext('ok', '저장했습니다.');
      go(`/agents/flows/${p.name}`);
    }
  }

  const head = form({}, async (f, b) => save(b, f, (b?.value as 'stay' | 'run') ?? 'stay'),
    h('div', { class: 'cols' },
      h('label', null, '이름 ', h('span', { class: 'muted small' }, '영문 소문자·숫자·.-_'),
        h('input', { name: 'name', required: true, pattern: '[a-z0-9][a-z0-9._\\-]*', value: preset?.name ?? '', readonly: !!name })),
      h('label', null, '제목', h('input', { name: 'title', value: preset?.title ?? '' }))),
    h('label', null, '전체 목표 ', h('span', { class: 'muted small' }, '실행의 목표: 결과를 받는 사람이 읽는 맥락'),
      h('textarea', { name: 'goal', rows: 2, required: true }, preset?.goal ?? '')),
    h('div', { class: 'actions' },
      h('button', { value: 'stay' }, '저장'),
      h('button', { value: 'run', class: 'secondary' }, '저장하고 실행'),
      name && link('/agents/presets', '예약은 프리셋 · 예약에서')));

  replace(main(),
    pageHead(preset ? preset.title : '새 순서도', '블럭이 단계(에이전트 하나), 화살표가 결과가 넘어가는 길입니다. 앞 단계가 모두 끝나야 다음 단계가 ' +
      '시작하고, 앞 단계가 실패하면 그 뒤는 건너뜁니다.', TABS),
    section('순서도', head),
    section('흐름',
      h('div', { class: 'actions' },
        h('button', { type: 'button', onclick: addStep }, '블럭 추가'),
        h('button', { type: 'button', class: 'secondary', onclick: () => { arrange(flow); draw(); fit(); } }, '자동 정렬'),
        h('button', { type: 'button', class: 'secondary', onclick: () => fit() }, '전체 보기')),
      h('div', { class: 'flow-editor' }, canvas, panel)),
    h('details', { class: 'panel' }, h('summary', null, '허가 (라우팅 · 한도)'), gf.el));
  // the grant's routes decide each block's model choices: redraw the panel when they change
  gf.el.addEventListener('change', () => drawPanel());
  draw();
  requestAnimationFrame(() => fit());  // once the canvas has its size
}

/** The run's page: its flow with each step's state, when the run has one. */
export function flowStates(run: Json): Record<string, StepState> {
  const out: Record<string, StepState> = {};
  const byAgent = new Map<string, Json>();
  const walk = (nodes: Json[]) => nodes.forEach(n => { byAgent.set(n.id, n); walk(n.children); });
  walk(run.tree);
  for (const [sid, why] of Object.entries(run.flow_skipped ?? {})) out[sid] = { state: 'skipped', label: `건너뜀: ${why}` };
  for (const [sid, aid] of Object.entries(run.flow_agents ?? {})) {
    const n = byAgent.get(aid as string);
    const st = n?.status || n?.state || 'running';
    out[sid] = { state: st, label: { done: '완료', running: '실행 중', waiting: '기다리는 중', ready: '시작',
                                     cancelled: '취소됨', failed: '실패' }[st as string] ?? st };
  }
  return out;
}

