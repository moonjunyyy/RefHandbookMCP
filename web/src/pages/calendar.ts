// The calendar (/calendar): the person's own calendar and one for each of their projects, on one month
// grid (docs/apps-vault-calendar.md §3.3). The head is one row: the month and its arrows, today, a chip
// per calendar (off: hidden on this browser), and the subscription address. A day pressed opens below the
// grid: its events, and "+ 일정". An event is written in a dialog, and changed or removed from the same
// one. Times are kept in UTC by the service (docs/calendar.md) and shown in the browser's own.

import { api, button, dialog, empty, flash, frame, h, link, main, message, pageHead, primaryLink, replace, title } from '/auth/static/site.js';
import type { Json } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';

const cal = api('/calendar/api/v1');
const HIDDEN = 'cal.hidden';  // the calendars this browser keeps off the grid
const REPEATS: [string, string][] = [['', n_('반복 없음')], ['FREQ=DAILY', n_('매일')], ['FREQ=WEEKLY', n_('매주')],
                                     ['FREQ=MONTHLY', n_('매달')], ['FREQ=YEARLY', n_('매년')]];

// ── time, in the browser's zone ───────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, '0');
/** A local date as YYYY-MM-DD. */
export const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
/** A local instant as the service keeps it: UTC, seconds, Z. */
const toUtc = (d: Date) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
/** What the service gave (an instant or a date) as a local Date. */
export function fromServer(s: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
  return new Date(s);
}
const localInput = (d: Date) => `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;  // for datetime-local
const hm = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

/** The days an event's occurrence covers, as local keys (an all-day end is exclusive). */
export function daysOf(o: Json): string[] {
  const out: string[] = [];
  const start = fromServer(o.start);
  const end = fromServer(o.end);
  const last = o.allday ? new Date(end.getTime() - 1) : new Date(Math.max(end.getTime() - 1, start.getTime()));
  for (const d = new Date(start.getFullYear(), start.getMonth(), start.getDate()); d <= last; d.setDate(d.getDate() + 1)) out.push(dayKey(d));
  return out;
}

function hidden(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(HIDDEN) ?? '[]')); } catch { return new Set(); }
}
function keepHidden(s: Set<string>): void {
  try { localStorage.setItem(HIDDEN, JSON.stringify([...s])); } catch { /* storage may be off */ }
}

// ── the event dialog ──────────────────────────────────────────────────────

/** Write an event (a new one on `day`, or `ev` to change): true when kept. */
async function editEvent(calendars: Json[], day: string, ev?: Json): Promise<boolean> {
  const start0 = ev ? fromServer(ev.start) : (() => { const d = fromServer(day); d.setHours(new Date().getHours() + 1, 0, 0, 0); return d; })();
  const end0 = ev ? fromServer(ev.end) : new Date(start0.getTime() + 3600_000);
  const allday = h('input', { type: 'checkbox', checked: !!ev?.allday });
  const summary = h('input', { type: 'text', name: 'summary', required: true, maxlength: 200, value: ev?.summary ?? '', autofocus: true });
  const startAt = h('input', { type: 'datetime-local', value: localInput(start0), required: true });
  const endAt = h('input', { type: 'datetime-local', value: localInput(end0), required: true });
  const startDay = h('input', { type: 'date', value: dayKey(start0), required: true });
  const endDay = h('input', { type: 'date', value: ev?.allday ? dayKey(new Date(end0.getTime() - 1)) : dayKey(end0), required: true });
  const which = h('select', { name: 'cal' }, calendars.map(c => h('option', { value: c.id, selected: c.id === (ev?.cal ?? calendars[0]?.id) }, c.name)));
  const repeat = h('select', { name: 'rrule' }, REPEATS.map(([v, label]) =>
    h('option', { value: v, selected: v === (ev?.rrule ?? '').split(';').filter((x: string) => x.startsWith('FREQ='))[0] }, t(label))));
  const where = h('input', { type: 'text', name: 'location', maxlength: 200, value: ev?.location ?? '' });
  const note = h('textarea', { name: 'description', rows: 3 }, ev?.description ?? '');
  const timed = h('div', { class: 'cols' }, h('label', null, t('시작'), startAt), h('label', null, t('끝'), endAt));
  const dated = h('div', { class: 'cols' }, h('label', null, t('시작'), startDay), h('label', null, t('끝'), endDay));
  const swap = () => { timed.hidden = allday.checked; dated.hidden = !allday.checked; };
  allday.addEventListener('change', swap);
  swap();
  let remove = false;
  const body = h('div', { class: 'fields' },
    h('label', null, t('제목'), summary),
    h('label', { class: 'check' }, allday, t('종일')),
    timed, dated,
    h('div', { class: 'cols' }, h('label', null, t('캘린더'), which), h('label', null, t('반복'), repeat)),
    h('label', null, t('장소'), where),
    h('label', null, t('메모'), note),
    ev && h('p', { class: 'actions' }, button(t('지우기'), (b: HTMLButtonElement) => { remove = true; b.closest('dialog')?.querySelector<HTMLButtonElement>('button[type=submit]')?.click(); }, 'danger')));
  const ok = await dialog(ev ? t('일정') : t('새 일정'), body, { ok: t('저장') });
  if (!ok) return false;
  if (remove) {
    if (!await dialog(t('일정 지우기'), h('p', null, ev.summary), { ok: t('지우기'), danger: true })) return false;
    await cal.del(`/events/${ev.id}`);
    return true;
  }
  const all = allday.checked;
  const after = fromServer(endDay.value);  // the service's all-day end is exclusive: the day after the last
  after.setDate(after.getDate() + 1);
  const payload = {
    cal: which.value, summary: summary.value.trim(), allday: all, location: where.value.trim(), description: note.value,
    rrule: repeat.value,
    start: all ? startDay.value : toUtc(new Date(startAt.value)),
    end: all ? dayKey(after) : toUtc(new Date(endAt.value)),
  };
  if (!payload.summary) { flash('error', t('제목을 적으세요.')); return false; }
  if (ev) await cal.patch(`/events/${ev.id}`, payload);
  else await cal.post('/events', payload);
  return true;
}

/** The subscription address: made once, shown with a copy, taken back from here too. */
async function subscription(): Promise<void> {
  let feeds: Json[] = (await cal.get('/feeds')).feeds;
  if (!feeds.length) feeds = [await cal.post('/feeds', { name: t('구독') })];
  const f = feeds[0];
  const field = h('input', { type: 'text', readonly: true, value: f.url, onfocus: (ev: Event) => (ev.target as HTMLInputElement).select() });
  let revoke = false;
  const body = h('div', { class: 'fields' },
    h('label', null, t('구독 주소'), field),
    h('p', { class: 'actions' },
      button(t('복사'), async () => { await navigator.clipboard?.writeText(f.url); flash('ok', t('복사했습니다.')); }, 'secondary'),
      button(t('거두기'), (b: HTMLButtonElement) => { revoke = true; b.closest('dialog')?.querySelector<HTMLButtonElement>('button[type=submit]')?.click(); }, 'link')));
  const ok = await dialog(t('폰 캘린더에 넣기'), body, { ok: t('닫기'), cancel: t('취소') });
  if (ok && revoke) {
    if (await dialog(t('구독 주소 거두기'), h('p', null, f.url), { ok: t('거두기'), danger: true })) await cal.del(`/feeds/${f.token}`);
  }
}

// ── the page ──────────────────────────────────────────────────────────────

export async function calendar(): Promise<void> {
  title(t('캘린더'));
  if (!frame.uid) {
    replace(main(), pageHead(t('캘린더')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/calendar`, t('로그인'))));
    return;
  }
  const params = new URLSearchParams(location.search);
  const today = dayKey(new Date());
  let selected = params.get('d') || '';
  let shown = (params.get('m') || (selected || today).slice(0, 7)).split('-').map(Number);  // [year, month]
  const off = hidden();
  let calendars: Json[] = [];
  let events: Json[] = [];
  const head = h('div', { class: 'cal-head' });
  const grid = h('div', { class: 'cal-grid', role: 'grid' });
  const panel = h('div', { class: 'cal-day-panel' });
  const byCal = () => Object.fromEntries(calendars.map(c => [c.id, c]));

  function remember(): void {
    const q = new URLSearchParams();
    const m = `${shown[0]}-${pad(shown[1])}`;
    if (m !== today.slice(0, 7)) q.set('m', m);
    if (selected) q.set('d', selected);
    history.replaceState(null, '', q.toString() ? `/calendar?${q}` : '/calendar');
  }

  /** The grid's span: whole weeks (Monday first) around the month. */
  function span(): [Date, Date] {
    const first = new Date(shown[0], shown[1] - 1, 1);
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    const end = new Date(start); end.setDate(start.getDate() + 42);
    return [start, end];
  }

  async function load(): Promise<void> {
    const [a, b] = span();
    const r = await cal.get(`/events?from=${toUtc(a)}&to=${toUtc(b)}`);
    events = r.events;
  }

  function perDay(): Record<string, Json[]> {
    const out: Record<string, Json[]> = {};
    for (const o of events) {
      if (off.has(o.cal)) continue;
      for (const k of daysOf(o)) (out[k] ??= []).push(o);
    }
    return out;
  }

  function chip(o: Json, full = false): HTMLElement {
    const c = byCal()[o.cal];
    const start = fromServer(o.start);
    return h('button', { type: 'button', class: 'cal-ev', style: c?.color ? `--ev: ${c.color}` : null, title: o.summary,
                         onclick: async () => { if (await editEvent(calendars, selected || today, o).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
      !o.allday && h('span', { class: 'cal-time' }, hm(start)), full ? o.summary : h('span', { class: 'cal-title' }, o.summary),
      full && c && h('span', { class: 'muted small' }, ' · ', c.name));
  }

  function drawHead(): void {
    const name = new Date(shown[0], shown[1] - 1, 1).toLocaleDateString(undefined, { year: 'numeric', month: 'long' });
    replace(head,
      h('div', { class: 'cal-nav' },
        button('‹', () => move(-1), 'link'), h('h1', null, name), button('›', () => move(1), 'link'),
        link(`/calendar?d=${today}`, t('오늘'))),
      h('div', { class: 'chips cal-sources', role: 'group', 'aria-label': t('캘린더') }, calendars.map(c =>
        h('button', { type: 'button', class: 'chip', 'aria-pressed': off.has(c.id) ? 'false' : 'true', style: c.color ? `--ev: ${c.color}` : null,
                      onclick: () => { if (off.has(c.id)) off.delete(c.id); else off.add(c.id); keepHidden(off); drawGrid(); drawPanel(); } },
          h('span', { class: 'dot', 'aria-hidden': 'true' }), c.name))),
      h('div', { class: 'actions' }, button(t('폰에 구독'), () => subscription().catch(e => flash('error', message(e))), 'secondary')));
  }

  function drawGrid(): void {
    const [start] = span();
    const days = perDay();
    const names = [...Array(7)].map((_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d.toLocaleDateString(undefined, { weekday: 'short' }); });
    const cells: HTMLElement[] = names.map(n => h('div', { class: 'cal-wd', role: 'columnheader' }, n));
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const k = dayKey(d);
      const list = days[k] ?? [];
      cells.push(h('div', { class: `cal-day${d.getMonth() !== shown[1] - 1 ? ' other' : ''}${k === today ? ' today' : ''}${k === selected ? ' selected' : ''}`,
                            role: 'gridcell', tabindex: 0, 'aria-label': d.toLocaleDateString(), 'data-day': k,
                            onclick: () => { selected = k; remember(); drawGrid(); drawPanel(); },
                            onkeydown: (ev: KeyboardEvent) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); selected = k; remember(); drawGrid(); drawPanel(); } } },
        h('span', { class: 'cal-num' }, String(d.getDate())),
        list.slice(0, 3).map(o => chip(o)),
        list.length > 3 && h('span', { class: 'cal-more muted small' }, t('+{n}', { n: list.length - 3 }))));
    }
    replace(grid, cells);
  }

  function drawPanel(): void {
    if (!selected) { replace(panel); return; }
    const list = (perDay()[selected] ?? []).sort((a, b) => Number(!!b.allday) - Number(!!a.allday) || a.start.localeCompare(b.start));
    replace(panel,
      h('div', { class: 'section-head' },
        h('h2', null, fromServer(selected).toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'long' })),
        h('span', { class: 'actions' }, button(t('+ 일정'), async () => {
          if (await editEvent(calendars, selected).catch(e => { flash('error', message(e)); return false; })) await refresh();
        }, 'secondary'))),
      list.length ? h('div', { class: 'day-list' }, list.map(o => chip(o, true))) : empty(t('일정 없음')));
  }

  async function refresh(): Promise<void> {
    await load();
    drawGrid();
    drawPanel();
  }

  async function move(by: number): Promise<void> {
    const d = new Date(shown[0], shown[1] - 1 + by, 1);
    shown = [d.getFullYear(), d.getMonth() + 1];
    remember();
    drawHead();
    await refresh();
  }

  calendars = (await cal.get('/calendars')).calendars;
  await load();
  replace(main(), head, grid, panel);
  drawHead();
  drawGrid();
  drawPanel();
}
