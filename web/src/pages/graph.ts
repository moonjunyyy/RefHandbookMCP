// The knowledge graph, drawn (/handbook; refhandbook/graph_api.py; docs/entry-graph.md). The overview is the topics
// (the entries) and what joins them: a route from one topic to another, a row two topics both reach, a tag of both,
// the cards. A topic pressed opens into its rows (and closes again); a node pressed says what it is beside the
// drawing. Nodes are laid out by forces (they push each other apart, a link pulls its two ends together), dragged by
// hand, and the whole is moved by dragging the ground and scaled by the wheel, − + and 0. A scale moves the nodes apart
// and leaves what is drawn its size: a mark grows a little and stops, the letters keep their size on the screen, and
// with more room more of the names are written — none over another.
// One file, importing no other page: it can become an app of its own without being written again.

import { api, button, empty, h, keys, main, message, pageHead, replace, title } from '/auth/static/site.js';
import type { Json } from '/auth/static/site.js';
import { t } from '../lib/i18n';

const hb = api('/handbook/api/v1');

interface GNode { id: string; type: string; kind?: string; title: string; label?: string; n?: number; ledger?: string; shared?: boolean;
                  of?: string; x: number; y: number; vx: number; vy: number; held?: boolean }
interface GLink { s: string; t: string; kind: string; n?: number }

/** What each kind of link is: its resting length, and whether it joins topics (drawn heavier). */
const LINK: Record<string, { length: number; joins: boolean }> = {
  route: { length: 240, joins: true }, shared: { length: 130, joins: true }, tag: { length: 120, joins: false },
  card: { length: 100, joins: false }, row: { length: 80, joins: false }, basis: { length: 60, joins: false },
};
const COLOUR: Record<string, string> = { entry: '--accent', tag: '--muted', card: '--ok', row: '--text', shared: '--warn' };
const colourOf = (n: GNode) => COLOUR[n.shared ? 'shared' : n.type] ?? '--text';
const radius = (n: GNode) => n.type === 'entry' ? 10 + Math.min(12, Math.sqrt(n.n ?? 0)) : n.shared ? 7 : n.type === 'row' ? 4.5 : 5.5;
/** The scale's ends: all of it in sight, and a crowded corner pulled apart. */
const SCALES: [number, number] = [.2, 8];
/** How far a mark shrinks and grows with the scale (× its own radius): it stays a mark at both ends. */
const MARK: [number, number] = [.75, 1.6];
/** The letters' size on the screen (px), a topic's and the others': the same at every scale. */
const LETTERS = { entry: 13, other: 12 };
const room = (el: HTMLElement) => Math.max(320, Math.floor(window.innerHeight - el.getBoundingClientRect().top - 24));

export async function graph(): Promise<void> {
  title(t('지식 그래프'));
  const canvas = h('canvas', { class: 'kg-canvas', role: 'img', 'aria-label': t('지식 그래프'), tabindex: '0' }) as HTMLCanvasElement;
  const side = h('aside', { class: 'kg-side', 'aria-live': 'polite' });
  const legend = h('div', { class: 'kg-legend' }, ...([['entry', t('주제')], ['shared', t('여러 주제가 닿는 행')], ['row', t('행')], ['tag', t('태그')], ['card', t('카드')]] as const)
    .map(([k, label]) => h('span', { class: 'kg-key' }, h('span', { class: 'dot', style: `--ev: var(${COLOUR[k]})`, 'aria-hidden': 'true' }), label)));
  const tools = h('div', { class: 'kg-tools', role: 'group', 'aria-label': t('보기 크기') });
  const stage = h('div', { class: 'kg-stage' }, canvas, tools);
  replace(main(), pageHead(t('지식 그래프')), legend, h('div', { class: 'kg' }, stage, side));

  let nodes: GNode[] = [], links: GLink[] = [];
  const byId = new Map<string, GNode>();
  const open = new Set<string>();
  let scale = 1, tx = 0, ty = 0, heat = 1, running = false;
  let selected: GNode | null = null, hover: GNode | null = null;
  const ctx = canvas.getContext('2d')!;

  function add(raw: Json, near?: GNode): GNode {
    const old = byId.get(raw.id);
    if (old) return old;
    const a = Math.random() * Math.PI * 2, r = near ? 40 + Math.random() * 40 : 120 + Math.random() * 260;
    const n: GNode = { ...raw, x: (near?.x ?? 0) + Math.cos(a) * r, y: (near?.y ?? 0) + Math.sin(a) * r, vx: 0, vy: 0, of: near?.id };
    nodes.push(n);
    byId.set(n.id, n);
    return n;
  }
  function join(l: GLink): void {
    if (byId.has(l.s) && byId.has(l.t) && !links.some(x => x.s === l.s && x.t === l.t && x.kind === l.kind)) links.push(l);
  }

  // ── the layout: every pair pushes apart, a link pulls its ends to its length, all are drawn gently to the middle ──
  function step(): void {
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
        if (d2 > 250000) continue;
        const f = 2600 / d2, d = Math.sqrt(d2);
        a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
      }
      a.vx -= a.x * .004; a.vy -= a.y * .004;
    }
    for (const l of links) {
      const a = byId.get(l.s)!, b = byId.get(l.t)!;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - (LINK[l.kind]?.length ?? 100)) * .02;
      a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    for (const n of nodes) {
      if (n.held) { n.vx = n.vy = 0; continue; }
      n.vx *= .82; n.vy *= .82;
      n.x += Math.max(-30, Math.min(30, n.vx * heat)); n.y += Math.max(-30, Math.min(30, n.vy * heat));
    }
    heat *= .985;
  }
  function run(): void {
    if (running) return;
    running = true;
    const tick = (): void => {
      if (!canvas.isConnected) { running = false; window.removeEventListener('resize', size); return; }
      step();
      draw();
      if (heat > .03) requestAnimationFrame(tick); else running = false;
    };
    requestAnimationFrame(tick);
  }
  const warm = (to = .6): void => { heat = Math.max(heat, to); run(); };

  // ── the drawing ──
  const css = (name: string) => getComputedStyle(canvas).getPropertyValue(name).trim() || getComputedStyle(canvas).color;
  function size(): void {
    const ratio = window.devicePixelRatio || 1, height = room(stage);
    stage.style.height = `${height}px`;
    canvas.width = Math.floor(stage.clientWidth * ratio);
    canvas.height = Math.floor(height * ratio);
    draw();
  }
  /** A mark's radius on the screen: its own, a little smaller far out and a little larger close in. */
  const mark = (n: GNode) => radius(n) * Math.max(MARK[0], Math.min(MARK[1], Math.sqrt(scale)));
  /** How much of a name is written: more of it as the scale gives it room. */
  const letters = () => Math.round(Math.max(14, Math.min(64, 22 * scale + 6)));
  /** The names written in the last drawing, each with its box on the screen (from the drawing's middle). */
  let written: { id: string; text: string; box: [number, number, number, number]; px: number }[] = [];
  function draw(): void {
    const ratio = window.devicePixelRatio || 1, w = canvas.width / ratio, hgt = canvas.height / ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, hgt);
    ctx.translate(w / 2 + tx, hgt / 2 + ty);  // the scale is applied to the places below, not to the pen
    const line = css('--line'), accent = css('--accent'), text = css('--text');
    for (const l of links) {
      const a = byId.get(l.s)!, b = byId.get(l.t)!, joins = LINK[l.kind]?.joins;
      const lit = selected && (selected.id === l.s || selected.id === l.t);
      ctx.beginPath(); ctx.moveTo(a.x * scale, a.y * scale); ctx.lineTo(b.x * scale, b.y * scale);
      ctx.strokeStyle = joins || lit ? accent : line;
      ctx.globalAlpha = lit ? 1 : joins ? .75 : .9;
      ctx.lineWidth = joins ? 2.2 : 1;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    for (const n of nodes) {
      ctx.beginPath(); ctx.arc(n.x * scale, n.y * scale, mark(n), 0, Math.PI * 2);
      ctx.fillStyle = css(colourOf(n));
      ctx.fill();
      if (n === selected || open.has(n.id)) { ctx.lineWidth = 2; ctx.strokeStyle = text; ctx.stroke(); }
    }
    // the names: the selected and the pointed-at first, then the topics (the larger first), then the rest as the
    // scale lets them in; a name that would lie over one already written is left out until there is room
    ctx.textAlign = 'center';
    ctx.fillStyle = text;
    written = [];
    const most = letters();
    const rank = (n: GNode) => n === selected ? 0 : n === hover ? 1 : n.type === 'entry' ? 2 : n.shared ? 3 : 4;
    const wanted = nodes.filter(n => n.type === 'entry' || n === selected || n === hover || scale > 1.5 || (n.shared && scale > .8))
      .sort((a, b) => rank(a) - rank(b) || (b.n ?? 0) - (a.n ?? 0));
    for (const n of wanted) {
      const px = n.type === 'entry' ? LETTERS.entry : LETTERS.other;
      ctx.font = `${n.type === 'entry' ? '600 ' : ''}${px}px system-ui, sans-serif`;
      const whole = n.type === 'row' ? n.title : n.title.split(' · ')[0];
      const label = whole.length > most ? whole.slice(0, most - 1) + '…' : whole;
      const x = n.x * scale, y = n.y * scale + mark(n) + px + 1, half = ctx.measureText(label).width / 2;
      const box: [number, number, number, number] = [x - half, y - px, x + half, y + 3];
      if (rank(n) > 1 && written.some(o => box[0] < o.box[2] && o.box[0] < box[2] && box[1] < o.box[3] && o.box[1] < box[3])) continue;
      ctx.fillText(label, x, y);
      written.push({ id: n.id, text: label, box, px });
    }
  }

  // ── what is pressed ──
  const at = (ev: PointerEvent | WheelEvent): [number, number] => {
    const b = canvas.getBoundingClientRect();
    return [(ev.clientX - b.left - b.width / 2 - tx) / scale, (ev.clientY - b.top - b.height / 2 - ty) / scale];
  };
  const under = (x: number, y: number): GNode | null => {
    for (let i = nodes.length - 1; i >= 0; i--) { const n = nodes[i], r = (mark(n) + 4) / scale; if ((n.x - x) ** 2 + (n.y - y) ** 2 <= r * r) return n; }
    return null;
  };
  function zoom(by: number, cx = 0, cy = 0): void {
    const next = Math.max(SCALES[0], Math.min(SCALES[1], scale * by));
    tx -= cx * (next - scale); ty -= cy * (next - scale);
    scale = next;
    draw();
  }
  function fit(): void {
    if (!nodes.length) return;
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const w = Math.max(...xs) - Math.min(...xs) + 160, hgt = Math.max(...ys) - Math.min(...ys) + 160;
    scale = Math.max(SCALES[0], Math.min(1.6, Math.min(stage.clientWidth / w, stage.clientHeight / hgt)));
    tx = -(Math.max(...xs) + Math.min(...xs)) / 2 * scale; ty = -(Math.max(...ys) + Math.min(...ys)) / 2 * scale;
    draw();
  }
  let drag: { node: GNode | null; x: number; y: number; moved: boolean } | null = null;
  canvas.addEventListener('pointerdown', ev => {
    const [x, y] = at(ev);
    drag = { node: under(x, y), x: ev.clientX, y: ev.clientY, moved: false };
    if (drag.node) drag.node.held = true;
    canvas.setPointerCapture(ev.pointerId);
  });
  canvas.addEventListener('pointermove', ev => {
    const [x, y] = at(ev);
    if (!drag) { const n = under(x, y); if (n !== hover) { hover = n; canvas.style.cursor = n ? 'pointer' : 'grab'; draw(); } return; }
    if (Math.abs(ev.clientX - drag.x) + Math.abs(ev.clientY - drag.y) > 3) drag.moved = true;
    if (drag.node) { drag.node.x = x; drag.node.y = y; warm(.3); }
    else if (drag.moved) { tx += ev.clientX - drag.x; ty += ev.clientY - drag.y; drag.x = ev.clientX; drag.y = ev.clientY; draw(); }
  });
  canvas.addEventListener('pointerup', () => {
    const d = drag;
    drag = null;
    if (!d) return;
    if (d.node) d.node.held = false;
    if (!d.moved) void pick(d.node);
  });
  canvas.addEventListener('wheel', ev => { ev.preventDefault(); const [x, y] = at(ev); zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15, x, y); }, { passive: false });

  /** A node pressed: it is said beside the drawing; a topic also opens into its rows, or closes. */
  async function pick(n: GNode | null): Promise<void> {
    selected = n;
    draw();
    if (!n) { replace(side, empty(t('주제를 누르면 그 행으로 펼쳐지고, 노드를 누르면 여기에 내용이 보입니다'))); return; }
    try {
      if (n.type === 'entry') {
        if (open.has(n.id)) {
          open.delete(n.id);
          const gone = new Set(nodes.filter(x => x.of === n.id).map(x => x.id));
          nodes = nodes.filter(x => !gone.has(x.id));
          gone.forEach(id => byId.delete(id));
          links = links.filter(l => !gone.has(l.s) && !gone.has(l.t));
        } else {
          const got = await hb.get(`/graph/entry?id=${encodeURIComponent(n.id)}`);
          open.add(n.id);
          for (const raw of got.nodes) { const row = add(raw, n); if (row.type === 'row') join({ s: n.id, t: row.id, kind: 'row' }); }
          for (const l of got.links) join(l);
        }
        warm();
      }
      const one = await hb.get(`/node?id=${encodeURIComponent(n.id)}`);
      if (selected !== n) return;
      const count = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${k} ${v}`).join(' · ') || '—';
      replace(side,
        h('h2', null, one.title),
        h('p', { class: 'kg-meta' }, [one.type, one.state, one.name, n.type === 'entry' ? t('행 {n}개', { n: String(n.n ?? 0) }) : '', n.ledger ? t('원장 {l}', { l: n.ledger }) : '']
          .filter(Boolean).join(' · ')),
        one.content && one.content !== one.title ? h('pre', { class: 'kg-text' }, one.content + (one.cut ? ' …' : '')) : false,
        h('dl', { class: 'kg-links' }, h('dt', null, t('나가는 연결')), h('dd', null, count(one.out)), h('dt', null, t('들어오는 연결')), h('dd', null, count(one.in))));
    } catch (e) {
      replace(side, h('p', null, message(e)));
    }
  }

  const tool = (label: string, name: string, fn: () => void) => { const b = button(label, fn, 'link'); b.title = name; b.setAttribute('aria-label', name); return b; };
  replace(tools, tool('−', t('축소'), () => zoom(1 / 1.25)), tool('+', t('확대'), () => zoom(1.25)), tool('⌂', t('전체 보기'), fit));
  keys([
    { key: '-', label: t('축소'), run: () => zoom(1 / 1.25) },
    { key: '+', label: t('확대'), run: () => zoom(1.25) },
    { key: '0', label: t('전체 보기'), run: fit },
    { key: 'Escape', label: t('선택 풀기'), run: () => pick(null) },
  ]);

  const seen = await hb.get('/graph');
  if (!seen.nodes.length) { replace(main(), pageHead(t('지식 그래프')), empty(t('아직 그릴 것이 없습니다. 원장이 입구가 되면 여기에 보입니다.'))); return; }
  for (const raw of seen.nodes) add(raw);
  for (const l of seen.links) join(l);
  canvas.dataset.nodes = String(nodes.length);
  window.addEventListener('resize', size);
  size();
  for (let i = 0; i < 260; i++) step();  // settled before it is first seen
  heat = .15;
  fit();
  void pick(null);
  run();
  // what a test (and a reader of the page's state) can ask without reading pixels
  (canvas as unknown as { graph: unknown }).graph = { nodes: () => nodes.map(n => ({ id: n.id, type: n.type, x: n.x, y: n.y })), links: () => links.length,
    scale: () => scale, letters, written: () => written, mark: (id: string) => { const n = byId.get(id); return n ? mark(n) : 0; },
    point: (id: string) => { const n = byId.get(id), b = canvas.getBoundingClientRect(); return n ? [b.left + b.width / 2 + tx + n.x * scale, b.top + b.height / 2 + ty + n.y * scale] : null; } };
}
