// The main page's widgets (docs/frame.md §4): an app's piece, drawn into a cell by the module the app
// declared ([[app.widget]] → me.cards[].widgets[].href). The frame imports the module and hands it the
// cell and a context — with the size the person gave the cell; the module calls its own app's API. An app
// with no module, and a module that fails, gets the launcher: the app's mark, name and links.
//
// The parts below are what every widget draws with (§4.2), so a calendar's day, a list of notes and a
// project's members read and behave alike: a list of items (one by one: a lead, a mark, the text, a second
// line, an aside; a row may be past, now or next), the numbers that sum it up, a meter, a strip of days, a
// month, bars and a run of days' activity. Their look is widgets.css (tokens only); how many rows a cell
// holds is theme.css's (--cell-items beside --cell).

import { Child, h, replace } from './dom';
import { Card, Param, Placement, Size, Widget, cellsOf, frame, isUnit, prefs, sizeOf } from './frame';
import { lang, locale, t } from './i18n';
import { api, go } from './parts';

export interface WidgetContext { frame: typeof frame; prefs: typeof prefs; t: typeof t; lang: string; theme: string;
                                 go: typeof go; api: typeof api; card: Card; widget: Widget; size: Size; params: Record<string, string> }
export type WidgetModule = { default: (host: HTMLElement, ctx: WidgetContext) => void | (() => void) | Promise<void | (() => void)> };

/** The widget every app has: a launcher — its mark and name, the way in; an app with more than one page lists
 * them. What the app is and its address are the store's to say (/app/<id>), not the main page's. */
export function launcher(c: Card): HTMLElement {
  const pages = c.links.filter((l, i, all) => l.href && all.findIndex(x => x.href === l.href) === i);
  const more = pages.length > 1 && pages.some(l => l.href !== c.href);
  return h('div', { class: `launcher${more ? '' : ' single'}` },
    h('h2', null, c.icon && h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c.icon),
      c.href ? h('a', { href: c.href }, c.title) : c.title),
    more && h('div', { class: 'links' }, pages.map(l => h('a', { href: l.href }, l.label))));
}

/** A cell of one unit: the app's mark with a name under it — the way in, as a phone's home shows an app. */
export function tile(c: Card, name: string): HTMLElement {
  return h('div', { class: 'launcher tile' }, h('a', { href: c.href || null },
    h('span', { class: 'app-icon big', 'aria-hidden': 'true' }, c.icon || name.slice(0, 1)), h('span', { class: 'tile-name' }, name)));
}

export const LAUNCHER = 'launcher';

/** The widgets an app offers: the launcher first, then the ones it declared. */
export function widgetsOf(c: Card): Widget[] {
  return [{ id: LAUNCHER, title: c.title, description: c.description, href: '', size: sizeOf(undefined).id }, ...c.widgets];
}

/** A cell's place on the grid for a size: the spans, as inline style (no class per size — the sizes are the
 * site's declaration, docs/frame.md §4). */
export function spanStyle(sizeId: string | undefined): string {
  const s = sizeOf(sizeId);
  return `grid-column: span ${s.cols}; grid-row: span ${s.rows};`;
}

/** A place's settings: the widget's declared defaults under what the person kept for this place; a kept value
 * that is no longer one of the declared choices gives way to the default. */
export function paramsOf(w: Widget, p?: Placement): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of w.params ?? []) {
    const kept = p?.params?.[d.id];
    out[d.id] = typeof kept === 'string' && (!d.choices || d.choices.some(c => c.value === kept)) ? kept : d.default;
  }
  return out;
}

const reading = new Map<string, Promise<{ value: string; label: string }[]>>();
/** What a setting may be: its declared choices, or the word for no filter and then the person's own objects, read
 * from the setting's path (askers at the same moment share one read). */
export function choicesOf(d: Param): Promise<{ value: string; label: string }[]> {
  const from = d.from;
  if (!from) return Promise.resolve(d.choices ?? []);
  const key = [from.path, from.list, from.value, from.label].join(' ');
  let list = reading.get(key);
  if (!list) {
    list = api(from.path).get('').then(r => ((r?.[from.list] ?? []) as Record<string, unknown>[])
      .map(x => ({ value: String(x[from.value] ?? ''), label: String(x[from.label] ?? '') })).filter(x => x.value), () => [])
      .finally(() => reading.delete(key));
    reading.set(key, list);
  }
  return list.then(own => [{ value: '', label: d.all ?? '' }, ...own]);
}

/** The words of the settings a place changed from the widget's own: what its head says after the title. */
async function said(w: Widget, params: Record<string, string>): Promise<string[]> {
  const out: string[] = [];
  for (const d of w.params ?? []) {
    if (params[d.id] === d.default) continue;
    const hit = (await choicesOf(d)).find(c => c.value === params[d.id]);
    if (hit) out.push(hit.label);
  }
  return out;
}

/** Draw a widget into its cell: the module when there is one, the launcher otherwise or on failure. `size`: the
 * cell's (the person's own, else the widget's declared one); `p`: the place, for its title and its settings. */
export async function mount(cell: HTMLElement, c: Card, w: Widget, size: Size = sizeOf(w.size), p?: Placement): Promise<void> {
  const unit = isUnit(size);  // one unit: the mark and the name — no head, and the module is not asked
  cell.classList.toggle('unit', unit);
  if (unit) { replace(cell, tile(c, w.id === LAUNCHER ? c.title : p?.title || w.title)); return; }
  const body = h('div', { class: 'widget-body' });
  const params = paramsOf(w, p);
  const words = h('span', { class: 'widget-said' });
  replace(cell, w.id === LAUNCHER ? null : h('div', { class: 'widget-head' },
    c.icon && h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon), h('a', { href: c.href }, c.title), ' · ', p?.title || w.title, words), body);
  if (!p?.title) void said(w, params).then(list => { if (list.length) replace(words, ' — ', list.join(' · ')); });
  if (w.id === LAUNCHER || !w.href) { replace(body, launcher(c)); return; }
  try {
    const mod = (await import(/* @vite-ignore */ w.href)) as WidgetModule;
    if (typeof mod.default !== 'function') throw new Error(`${w.href}: no default export`);
    await mod.default(body, { frame, prefs, t, lang: lang(), theme: frame.theme, go, api, card: c, widget: w, size: cellsOf(size), params });
  } catch (e) {
    console.warn('widget', c.id, w.id, e);  // the person sees the launcher; the console says why
    replace(body, launcher(c));
  }
}

// ── the parts widgets draw with (§4.2) ────────────────────────────────────

/** How many list rows a cell holds: its rows × --cell-items (theme.css, beside --cell). */
export function fit(ctx: { size: Size }): number {
  const per = Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue('--cell-items'), 10);
  return ctx.size.rows * (per > 0 ? per : 1);
}

const pad = (n: number) => String(n).padStart(2, '0');
/** A day as the services name it (YYYY-MM-DD, local time). */
export const dayKey = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** A time as how long ago (or how soon), in the page's language: '3시간 전', '어제', '2일 후'. */
export function ago(when: Date | number, now: number = Date.now()): string {
  const ms = (when instanceof Date ? when.getTime() : when) - now;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [['year', 31536e6], ['month', 2592e6], ['week', 6048e5], ['day', 864e5], ['hour', 36e5], ['minute', 6e4]];
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
  for (const [unit, size] of units) if (Math.abs(ms) >= size) return rtf.format(Math.round(ms / size), unit);
  return rtf.format(0, 'minute');
}

/** A colour the data gives (a calendar's), onto an element as --mark — only a colour CSS reads as one. */
function mark(el: HTMLElement, colour: string | undefined): HTMLElement {
  if (colour && CSS.supports('color', colour)) el.style.setProperty('--mark', colour);
  return el;
}

/** A row of a widget's list. lead: what comes first (a time, a check); mark: the colour of what it belongs to (a dot);
 * sub: a second line; aside: at the end (a date, a count, a tag); state: past (muted), now, next (pointed out). */
export interface Item { text: Child; href?: string; title?: string; lead?: Child; mark?: string; sub?: Child; aside?: Child; state?: 'past' | 'now' | 'next' }
/** Items under a title (a day, a due, a folder), with an aside (their count). */
export interface ItemGroup { title: Child; items: Item[]; aside?: Child }

function itemRow(i: Item): HTMLElement {
  return h('li', { class: 'item', 'data-state': i.state ?? null },
    i.lead !== undefined && i.lead !== null && h('span', { class: 'item-lead' }, i.lead),
    i.mark !== undefined && mark(h('span', { class: 'item-mark', 'aria-hidden': 'true' }), i.mark),
    h('span', { class: 'item-main' },
      i.href ? h('a', { class: 'item-text', href: i.href, title: i.title ?? null }, i.text) : h('span', { class: 'item-text', title: i.title ?? null }, i.text),
      i.sub !== undefined && i.sub !== null && i.sub !== '' && h('span', { class: 'item-sub' }, i.sub)),
    i.aside !== undefined && i.aside !== null && i.aside !== '' && h('span', { class: 'item-aside' }, i.aside));
}

const isGroups = (x: Item[] | ItemGroup[]): x is ItemGroup[] => x.length > 0 && 'items' in x[0];

/** The title a group of rows goes under (a day, a due, a folder), with its count. */
export function groupHead(title: Child, aside?: Child): HTMLElement {
  return h('p', { class: 'items-group' }, h('span', null, title), aside !== undefined && aside !== null && h('span', { class: 'items-count' }, aside));
}

/** What an empty list says: a line, or a line and the way to its first item. */
export type None = string | { text: string; href: string; label: string };

/** A widget's list, one item a row — or its groups, each under its title. `none`: what an empty list says;
 * `more`: the rest that did not fit, as a link. */
export function items(list: Item[] | ItemGroup[], none: None, more?: { href: string; n: number }): HTMLElement {
  const groups = isGroups(list) ? list.filter(g => g.items.length) : [];
  if (!groups.length && (isGroups(list) || !list.length)) {
    return h('p', { class: 'items-none muted small' }, typeof none === 'string' ? none : [none.text, ' ', h('a', { href: none.href }, none.label)]);
  }
  return h('div', { class: 'items' },
    groups.length ? groups.map(g => [groupHead(g.title, g.aside), h('ul', { class: 'items-list' }, g.items.map(itemRow))])
      : h('ul', { class: 'items-list' }, (list as Item[]).map(itemRow)),
    more && more.n > 0 && h('a', { class: 'items-more small', href: more.href }, t('{n}개 더', { n: more.n })));
}

/** A list inside a widget: the simple form (a link and an aside per row). */
export function widgetList(list: { href: string; text: Child; aside?: Child }[], none: string): HTMLElement {
  return items(list.map(i => ({ href: i.href, text: i.text, aside: i.aside })), none);
}

/** A number that sums a widget up, with its word; a tone (warn, bad, ok) when it asks for attention. */
export interface Stat { n: number | string; label: string; tone?: '' | 'ok' | 'warn' | 'bad'; href?: string }

/** The numbers at the head of a widget: what it holds at a glance. */
export function stats(list: Stat[]): HTMLElement {
  return h('div', { class: 'stats' }, list.map(s => {
    const body = [h('b', { class: 'stat-n' }, String(s.n)), h('span', { class: 'stat-label' }, s.label)];
    return s.href ? h('a', { class: 'stat', href: s.href, 'data-tone': s.tone || null }, body)
      : h('span', { class: 'stat', 'data-tone': s.tone || null }, body);
  }));
}

/** How much of a whole is done: a bar, its words beside it. */
export function meter(value: number, max: number, label: string): HTMLElement {
  const bar = h('span', { class: 'meter-bar' });
  bar.style.setProperty('--v', String(max > 0 ? Math.min(1, value / max) : 0));
  return h('div', { class: 'meter' },
    h('span', { class: 'meter-track', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': max, 'aria-valuenow': value, 'aria-label': label }, bar),
    h('span', { class: 'meter-label small muted' }, label));
}

/** The levels a day (or a bar) is drawn at by its count, against the largest: widgets.css has a look per level. */
const LEVELS = 3;
const level = (n: number, max: number) => (n <= 0 || max <= 0 ? 0 : Math.max(1, Math.ceil((LEVELS * n) / max)));

/** A day of a strip or a month: its count, the colours of what falls on it, where it leads. */
export interface Day { date: Date; n: number; marks?: string[]; href?: string }

/** A run of days (a week ahead): each its weekday, its date and its count as dots in the colours of what falls on it. */
export function dayStrip(days: Day[], today: Date = new Date()): HTMLElement {
  const max = Math.max(0, ...days.map(d => d.n));
  const now = dayKey(today);
  return h('ol', { class: 'day-strip' }, days.map(d => {
    const label = `${d.date.toLocaleDateString(locale(), { month: 'long', day: 'numeric', weekday: 'long' })} · ${t('{n}개', { n: d.n })}`;
    const dots = h('span', { class: 'day-dots', 'aria-hidden': 'true' },
      [...new Set(d.marks?.length ? d.marks : d.n ? [''] : [])].slice(0, LEVELS).map(c => mark(h('span', { class: 'day-dot' }), c || undefined)));
    const inner = [h('span', { class: 'day-wd' }, d.date.toLocaleDateString(locale(), { weekday: 'narrow' })),
                   h('span', { class: 'day-num' }, String(d.date.getDate())), dots];
    return h('li', { class: 'day', 'data-today': dayKey(d.date) === now ? '' : null, 'data-level': level(d.n, max) },
      d.href ? h('a', { href: d.href, 'aria-label': label, title: label }, inner) : h('span', { 'aria-label': label, title: label }, inner));
  }));
}

/** A month: its days on a grid of weeks (Monday first, as the calendar draws them), each at the level of its
 * count, today ringed, the picked one marked; ‹ › move the month, a day is picked in place, and the month's name is
 * a button when `open` is given (a year of months: the name opens the month). */
export interface Month { year: number; month: number; counts: Map<string, number>; today?: Date; picked?: string;
                         pick?: (key: string) => void; move?: (by: number) => void; open?: () => void }
export function monthGrid(m: Month): HTMLElement {
  const first = new Date(m.year, m.month, 1);
  const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
  const days = [...Array(42)].map((_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  const weeks = days[35].getMonth() === m.month ? 6 : 5;
  const max = Math.max(0, ...m.counts.values());
  const now = dayKey(m.today ?? new Date());
  const names = days.slice(0, 7).map(d => d.toLocaleDateString(locale(), { weekday: 'narrow' }));
  const nav = (by: number, text: string, label: string) => m.move && h('button', { type: 'button', class: 'month-nav', 'aria-label': label, onclick: () => m.move?.(by) }, text);
  return h('div', { class: 'month' },
    h('div', { class: 'month-head' }, nav(-1, '‹', t('이전 달')),
      h(m.open ? 'button' : 'span', m.open ? { type: 'button', class: 'month-title', onclick: () => m.open?.() } : { class: 'month-title' },
        first.toLocaleDateString(locale(), { year: 'numeric', month: 'long' })), nav(1, '›', t('다음 달'))),
    h('div', { class: 'month-grid', role: 'grid' },
      names.map(n => h('span', { class: 'month-wd', 'aria-hidden': 'true' }, n)),
      days.slice(0, weeks * 7).map(d => {
        const k = dayKey(d);
        const n = m.counts.get(k) ?? 0;
        return h('button', { type: 'button', class: 'month-day', 'data-level': level(n, max), 'data-today': k === now ? '' : null,
                             'data-out': d.getMonth() !== m.month ? '' : null, 'aria-pressed': m.picked ? String(k === m.picked) : null,
                             'aria-label': `${d.toLocaleDateString(locale(), { month: 'long', day: 'numeric', weekday: 'short' })} · ${t('{n}개', { n })}`,
                             onclick: () => m.pick?.(k) }, String(d.getDate()));
      })));
}

/** Counts by label, as bars against the largest (a vault's tags). */
export interface Bar { label: Child; n: number; href?: string }
export function bars(list: Bar[], none: string): HTMLElement {
  if (!list.length) return h('p', { class: 'items-none muted small' }, none);
  const max = Math.max(...list.map(b => b.n));
  return h('ul', { class: 'bars' }, list.map(b => {
    const fill = h('span', { class: 'bar-fill' });
    fill.style.setProperty('--v', String(max > 0 ? b.n / max : 0));
    const inner = [h('span', { class: 'bar-label' }, b.label), h('span', { class: 'bar-track', 'aria-hidden': 'true' }, fill), h('span', { class: 'bar-n' }, String(b.n))];
    return h('li', null, b.href ? h('a', { href: b.href }, inner) : h('span', null, inner));
  }));
}

/** What a form shows, in words under it — a form with no words is a picture to guess at. `scale`: for a form that
 * draws counts as shades (a strip of days, a month), the shades from few to many in that form's own colours. */
export function legend(text: string, scale?: 'days' | 'month'): HTMLElement {
  return h('div', { class: 'form-said' }, h('span', null, text),
    scale && h('span', { class: `form-scale scale-${scale}`, 'aria-hidden': 'true' },
      t('적음'), [...Array(LEVELS)].map((_, i) => h('i', { 'data-level': String(i + 1) })), t('많음')));
}

/** A run of days' counts as columns (what was done each day), the last today — with its ends and its words under it. */
export function activity(days: { date: Date; n: number }[], label: string): HTMLElement {
  const max = Math.max(0, ...days.map(d => d.n));
  const short = (d: Date) => d.toLocaleDateString(locale(), { month: 'numeric', day: 'numeric' });
  const last = days.length ? days[days.length - 1].date : null;
  return h('div', { class: 'form' },
    h('div', { class: 'activity', role: 'img', 'aria-label': label }, days.map(d => {
      const col = h('span', { class: 'act', 'data-level': level(d.n, max), title: `${short(d.date)} · ${d.n}` });
      col.style.setProperty('--v', String(max > 0 ? d.n / max : 0));
      return col;
    })),
    last && h('div', { class: 'form-ends', 'aria-hidden': 'true' }, h('span', null, short(days[0].date)),
      h('span', null, dayKey(last) === dayKey(new Date()) ? t('오늘') : short(last))),
    legend(max > 0 ? `${label} · ${t('가장 많은 날 {n}', { n: max })}` : label));
}

export const openWord = () => t('열기');
