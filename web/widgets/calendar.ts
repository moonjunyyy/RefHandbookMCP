// The calendar's widgets on the main page (docs/apps-vault-calendar.md §3.4, §7.3), drawn with the frame's parts
// (docs/frame.md §4.2). One module for all; the frame says which (ctx.widget.id) and how big the cell is (ctx.size).
//   today    — the day at a glance (its events, the to-dos due, the overdue ones), the events as a timeline (all-day
//              first; past muted, the one now, the next), the to-dos due checked off in place; a taller cell adds tomorrow.
//   upcoming — the days ahead (the place's setting: 3, 7 or 14) as a strip (how full each is, in its calendars' colours), then their events by day.
//   month    — the month, each day shaded by how full it is; a day picked shows its events under it; ‹ › move.
//   tasks    — the to-do list (written and checked in place) by when it is due, with how much is done.
// A place's settings (ctx.params): which calendar (today, upcoming, month), how many days and which form — the strip
// and the list, or one of them (upcoming). A form that shades days carries its legend.
// Built by web/ into dist/widgets/calendar.js and declared in the site file as an absolute module path.

import { api, ago, dayKey, dayStrip, fit, h, items, legend, monthGrid, replace, stats } from '/auth/static/site.js';
import type { Item, ItemGroup, WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';
import { dueWord, taskList, Task } from '../src/lib/tasks';

const cal = api('/calendar/api/v1');
interface Calendar { id: string; name: string; color: string }
interface Occurrence { id: string; cal: string; summary: string; location: string; start: string; end: string; allday: boolean }

/** A time the service gives: a day (all-day) at local midnight, else the instant. */
function fromServer(s: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
  return new Date(s);
}
const utc = (d: Date) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const clock = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
const dayHref = (key: string) => `/calendar?d=${key}`;
const WEEK = 7;  // a strip's days; the span of 'upcoming' when a place says none

/** The events of [from, to), with their calendars' colours; `only`: those of one calendar, when it is one the
 * person has (a calendar that is gone means all of them). */
async function occurrences(from: Date, to: Date, only = ''): Promise<{ list: Occurrence[]; colour: (o: Occurrence) => string }> {
  const [cals, evs] = await Promise.all([cal.get('/calendars'), cal.get(`/events?from=${utc(from)}&to=${utc(to)}`)]);
  const colours = new Map((cals.calendars as Calendar[]).map(c => [c.id, c.color]));
  const all = evs.events as Occurrence[];
  return { list: colours.has(only) ? all.filter(o => o.cal === only) : all, colour: o => colours.get(o.cal) ?? '' };
}

/** The days an event covers, as day keys (an all-day event ends the day after its last). */
function daysOf(o: Occurrence): string[] {
  const s = midnight(fromServer(o.start));
  const e = fromServer(o.end);
  const out: string[] = [];
  for (let d = s; d < e || out.length === 0; d = addDays(d, 1)) { out.push(dayKey(d)); if (out.length > 62) break; }
  return out;
}

/** An event as a row: its time (or 종일), its calendar's colour, where; past, now or next against `now`. */
function row(o: Occurrence, colour: string, now: Date, next: Occurrence | undefined): Item {
  const s = fromServer(o.start), e = fromServer(o.end);
  const state = o.allday ? undefined : e <= now ? 'past' : s <= now ? 'now' : o === next ? 'next' : undefined;
  return { text: o.summary || t('(제목 없음)'), href: dayHref(dayKey(s)), title: o.summary, mark: colour,
           lead: o.allday ? t('종일') : clock(s),
           sub: [o.allday ? '' : t('{time}까지', { time: clock(e) }), o.location].filter(Boolean).join(' · '),
           state, aside: state === 'now' ? t('지금') : state === 'next' ? ago(s, now.getTime()) : undefined };
}

/** A day's events in order: all-day first, then by start. */
const inOrder = (list: Occurrence[]) => [...list].sort((a, b) => Number(b.allday) - Number(a.allday) || a.start.localeCompare(b.start));
const onDay = (list: Occurrence[], key: string) => inOrder(list.filter(o => daysOf(o).includes(key)));

/** A day's name in a list: 오늘, 내일, else its weekday and date. */
function dayTitle(d: Date, today: Date): string {
  const diff = Math.round((midnight(d).getTime() - midnight(today).getTime()) / 864e5);
  return diff === 0 ? t('오늘') : diff === 1 ? t('내일') : d.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric', weekday: 'short' });
}

async function today(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  const now = new Date();
  const start = midnight(now);
  const days = ctx.size.rows > 1 ? 2 : 1;
  const [{ list, colour }, r] = await Promise.all([occurrences(start, addDays(start, days), ctx.params?.calendar), cal.get('/tasks')]);
  const key = dayKey(now);
  const todays = onDay(list, key);
  const next = todays.find(o => !o.allday && fromServer(o.start) > now);
  const tasks = (r.tasks as Task[]).filter(x => !x.done && x.due && x.due <= key);
  const late = tasks.filter(x => x.due < key).length;
  const room = fit(ctx);
  const events: ItemGroup[] = [{ title: dayTitle(now, now), aside: String(todays.length), items: todays.slice(0, room).map(o => row(o, colour(o), now, next)) }];
  if (days > 1) {
    const k2 = dayKey(addDays(start, 1));
    const tomorrow = onDay(list, k2);
    events.push({ title: dayTitle(addDays(start, 1), now), aside: String(tomorrow.length), items: tomorrow.slice(0, room).map(o => row(o, colour(o), now, undefined)) });
  }
  const due = h('div', { class: 'widget-tasks' });
  const draw = (open: Task[]) => replace(due, items(open.length ? [{ title: t('할 일'), aside: String(open.length), items: open.slice(0, room).map(x => {
    const box = h('input', { type: 'checkbox', 'aria-label': x.text });
    box.addEventListener('change', () => {
      box.disabled = true;
      void cal.patch(`/tasks/${x.id}`, { done: true }).then(() => draw(open.filter(y => y.id !== x.id))).catch(() => { box.checked = false; box.disabled = false; });
    });
    const when = dueWord(x.due);
    return { text: x.text, lead: box, aside: h('span', { class: `tag small ${when.kind}`.trim() }, when.text) };
  }) }] : [], t('오늘까지 할 일이 없습니다.'), open.length > room ? { href: dayHref(key), n: open.length - room } : undefined));
  draw(tasks);
  replace(host,
    h('div', { class: 'widget-top' }, h('a', { class: 'widget-date', href: dayHref(key) }, now.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'long' })),
      stats([{ n: todays.length, label: t('일정') }, { n: tasks.length - late, label: t('오늘 마감'), tone: tasks.length - late ? 'warn' : '' },
             ...(late ? [{ n: late, label: t('지남'), tone: 'bad' as const }] : [])])),
    h('div', { class: 'today-cols' },
      items(events, t('오늘은 일정이 없습니다.'), todays.length > room ? { href: dayHref(key), n: todays.length - room } : undefined), due));
}

async function upcoming(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  const now = new Date();
  const start = midnight(now);
  const n = Number(ctx.params?.days) || WEEK;
  const { list, colour } = await occurrences(start, addDays(start, n), ctx.params?.calendar);
  const span = [...Array(n)].map((_, i) => addDays(start, i));
  const byDay = span.map(d => ({ date: d, key: dayKey(d), list: onDay(list, dayKey(d)) }));
  const room = fit(ctx);
  let left = room;
  const groups: ItemGroup[] = [];
  for (const d of byDay) {
    if (!d.list.length || left <= 0) continue;
    const next = d.key === dayKey(now) ? d.list.find(o => !o.allday && fromServer(o.start) > now) : undefined;
    groups.push({ title: dayTitle(d.date, now), aside: String(d.list.length), items: d.list.slice(0, left).map(o => row(o, colour(o), now, next)) });
    left -= d.list.length;
  }
  const total = byDay.reduce((n, d) => n + d.list.length, 0);
  const strips: HTMLElement[] = [];  // a strip is a week long: a longer span is a strip per week
  for (let i = 0; i < byDay.length; i += WEEK) strips.push(dayStrip(byDay.slice(i, i + WEEK).map(d => ({ date: d.date, n: d.list.length, marks: d.list.map(colour), href: dayHref(d.key) })), now));
  const form = ctx.params?.form || 'both';  // the place's form: the strip and the list, or one of them
  replace(host, form !== 'list' && [strips, legend(t('점은 그 날의 일정 · 진할수록 일정이 많은 날'), 'days')],
    form !== 'strip' && items(groups, { text: t('앞으로 {n}일 동안 일정이 없습니다.', { n }), href: '/calendar', label: t('일정 만들기') }, total > room ? { href: '/calendar', n: total - room } : undefined));
}

async function month(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  const now = new Date();
  let year = now.getFullYear(), mon = now.getMonth();
  let picked = dayKey(now);
  let list: Occurrence[] = [];
  let colour: (o: Occurrence) => string = () => '';
  const counts = new Map<string, number>();
  const agenda = h('div', { class: 'month-agenda' });
  const grid = h('div');
  const room = Math.max(1, fit(ctx) - ctx.size.rows * 2);  // the month takes most of the cell: the picked day's list gets the rest
  function drawAgenda(): void {
    const day = onDay(list, picked);
    const d = fromServer(picked);
    const next = picked === dayKey(now) ? day.find(o => !o.allday && fromServer(o.start) > now) : undefined;
    replace(agenda, items([{ title: dayTitle(d, now), aside: String(day.length), items: day.slice(0, room).map(o => row(o, colour(o), now, next)) }],
      t('이 날은 일정이 없습니다.'), { href: dayHref(picked), n: Math.max(0, day.length - room) }));
  }
  function drawGrid(): void {
    replace(grid, monthGrid({ year, month: mon, counts, today: now, picked,
      pick: k => { picked = k; drawGrid(); drawAgenda(); },
      move: by => { const d = new Date(year, mon + by, 1); year = d.getFullYear(); mon = d.getMonth(); void load(); } }));
  }
  async function load(): Promise<void> {
    const first = new Date(year, mon, 1);
    const from = addDays(first, -((first.getDay() + 6) % 7));
    const r = await occurrences(from, addDays(from, 42), ctx.params?.calendar);
    list = r.list; colour = r.colour;
    counts.clear();
    for (const o of list) for (const k of daysOf(o)) counts.set(k, (counts.get(k) ?? 0) + 1);
    if (fromServer(picked).getMonth() !== mon) picked = dayKey(first);
    drawGrid(); drawAgenda();
  }
  replace(host, grid, legend(t('진할수록 일정이 많은 날'), 'month'), agenda);
  await load();
}

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  replace(host, h('p', { class: 'muted small' }, '…'));
  if (ctx.widget.id === 'tasks') { await taskList(host, { grouped: true }); return; }
  if (ctx.widget.id === 'upcoming') { await upcoming(host, ctx); return; }
  if (ctx.widget.id === 'month') { await month(host, ctx); return; }
  await today(host, ctx);
}
