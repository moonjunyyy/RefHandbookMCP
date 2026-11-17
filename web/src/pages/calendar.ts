// The calendar (/calendar): the person's own calendar and one for each of their projects, on one axis of
// time with its levels (docs/calendar.md): the year (twelve months, each day at the level of its events),
// the month (a column of weeks that scrolls on: the title and the address follow the month in view), the
// week and the day (hours on a grid), and the list (the days ahead that have events). Moving along time is
// scrolling the month, a swipe or a sideways wheel on the hours, ‹ › and ← →; the title goes up one level
// and a day goes down to its day (the picked day's title in the month, a day's head in the week); g goes to a date. The head is one row: what is pressed first (the arrows, today, the views, the scale) and the title after it, so that nothing pressed moves when the title's length changes; then today,
// the view, a chip per calendar (off: hidden on this browser), and the subscription address. In the month,
// a day pressed opens below the grid: its events, and "+ 일정". On the hours, a slot pressed is a small card
// there: a title and Enter make an hour's event at that time, and 자세히 takes it to the dialog. An event
// pressed shows its card (what, when, whose; 편집, 지우기, its menu). An event is written, changed or
// removed in the dialog, and moved by
// dragging it onto another day (or, on the hours, another time); a repeating event is not dragged — its
// series is changed in the dialog. Times are kept in UTC by the service (docs/calendar.md) and shown in
// the browser's own.
// Every object has its menu where it is (docs/apps-vault-calendar.md §7.4, R10): an event (open, copy,
// move or copy to another calendar, delete), a day (new event, the week), a calendar's chip (rename and
// recolour, hide, only this one, its own subscription address, delete), and the chips' ⋯ (new calendar,
// show all, the phone subscription, connecting a device over CalDAV with a device password — §8.3). The day
// panel also lists the to-dos due that day (§7.3).

import { act, api, button, choice, dialog, empty, flash, form, frame, go, groupHead, h, keys, link, main, menu, menuButton, message, monthGrid, onMenu, pageHead, peek, primaryLink, replace, title, when } from '/auth/static/site.js';
import type { Json, MenuSection } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { copyText } from '../lib/clipboard';
import { taskList } from '../lib/tasks';

const cal = api('/calendar/api/v1');
const HIDDEN = 'cal.hidden';  // the calendars this browser keeps off the grid
const REPEATS: [string, string][] = [['', n_('반복 없음')], ['FREQ=DAILY', n_('매일')], ['FREQ=WEEKLY', n_('매주')],
                                     ['FREQ=MONTHLY', n_('매달')], ['FREQ=YEARLY', n_('매년')]];
let HOUR = 44;        // px per hour on the hours: the room there is over the hours shown (drawWeek)
const HOURS_SHOWN = [24, 16, 12, 8, 6];  // the hours' scale: how many hours the room shows; 24 is the whole day, with nothing to scroll
const WEEKS_SHOWN = [8, 6, 5, 4];        // the month's scale: how many weeks the room shows
const SCALE = 'cal.scale';               // the scale this browser keeps
const SNAP = 30;      // minutes a dropped or pressed time snaps to
const DAY_MS = 86400_000;
const WEEKS_BEFORE = 16;   // the month's scroller holds this many weeks before the shown month's first week…
const WEEKS_AFTER = 36;    // …and this many from it on: 52 weeks, one events query (the service answers up to 400 days)
const MONTH_ROWS = 6;      // the weeks a month can take
const EDGE_ROWS = 4;       // this near an end of the weeks it holds, the scroller is drawn again around the month in view
const LIST_DAYS = 30;      // the list reads this many days at a time…
const LIST_MAX = 360;      // …up to this many (one events query)
const SWIPE = 60;          // px a sideways swipe travels before it moves the range
const WHEEL_PAUSE = 600;   // ms after a sideways wheel moved the range before another may: one range a gesture

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
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const minutesOf = (d: Date) => d.getHours() * 60 + d.getMinutes();

/** The days an event's occurrence covers, as local keys (an all-day end is exclusive). */
export function daysOf(o: Json): string[] {
  const out: string[] = [];
  const start = fromServer(o.start);
  const end = fromServer(o.end);
  const last = o.allday ? new Date(end.getTime() - 1) : new Date(Math.max(end.getTime() - 1, start.getTime()));
  for (const d = new Date(start.getFullYear(), start.getMonth(), start.getDate()); d <= last; d.setDate(d.getDate() + 1)) out.push(dayKey(d));
  return out;
}

/** An event's start and end moved by whole days (and, for a timed one, to a time of day when given). */
function moved(o: Json, days: number, minutes?: number): { start: string; end: string } {
  const s = fromServer(o.start), e = fromServer(o.end);
  const len = e.getTime() - s.getTime();
  const ns = addDays(s, days);
  if (!o.allday && minutes !== undefined) ns.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
  const ne = new Date(ns.getTime() + len);
  return o.allday ? { start: dayKey(ns), end: dayKey(ne) } : { start: toUtc(ns), end: toUtc(ne) };
}

function hidden(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(HIDDEN) ?? '[]')); } catch { return new Set(); }
}
function keepHidden(s: Set<string>): void {
  try { localStorage.setItem(HIDDEN, JSON.stringify([...s])); } catch { /* storage may be off */ }
}
type Scale = { hours: number; weeks: number };
function scaleKept(): Scale {
  let s: Partial<Scale> = {};
  try { s = JSON.parse(localStorage.getItem(SCALE) ?? '{}') ?? {}; } catch { /* storage may be off */ }
  return { hours: HOURS_SHOWN.includes(s.hours ?? 0) ? s.hours! : 24, weeks: WEEKS_SHOWN.includes(s.weeks ?? 0) ? s.weeks! : 6 };
}
/** The room there is for a grid that starts where `el` does: down to the window's lower edge. */
const room = (el: HTMLElement) => Math.max(240, Math.floor(window.innerHeight - el.getBoundingClientRect().top - 24));

// ── the event dialog ──────────────────────────────────────────────────────

/** Write an event (a new one on `day`, at `minutes` of it when given — all-day when `wholeDay` — or `ev` to
 * change): true when kept. A new one starts with `seed` (the title and the calendar a quick card had). */
async function editEvent(calendars: Json[], day: string, ev?: Json, minutes?: number, wholeDay = false, seed: { summary?: string; cal?: string } = {}): Promise<boolean> {
  const start0 = ev ? fromServer(ev.start) : (() => {
    const d = fromServer(day);
    if (minutes !== undefined) d.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
    else d.setHours(new Date().getHours() + 1, 0, 0, 0);
    return d;
  })();
  const end0 = ev ? fromServer(ev.end) : new Date(start0.getTime() + 3600_000);
  const allday = h('input', { type: 'checkbox', checked: ev ? !!ev.allday : wholeDay });
  const summary = h('input', { type: 'text', name: 'summary', required: true, maxlength: 200, value: ev?.summary ?? seed.summary ?? '', autofocus: true });
  const startAt = h('input', { type: 'datetime-local', value: localInput(start0), required: true });
  const endAt = h('input', { type: 'datetime-local', value: localInput(end0), required: true });
  const startDay = h('input', { type: 'date', value: dayKey(start0), required: true });
  const endDay = h('input', { type: 'date', value: ev?.allday ? dayKey(new Date(end0.getTime() - 1)) : dayKey(end0), required: true });
  const which = h('select', { name: 'cal' }, calendars.map(c => h('option', { value: c.id, selected: c.id === (ev?.cal ?? seed.cal ?? calendars[0]?.id) }, c.name)));
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

/** The subscription address: made once (for everything, or for one calendar), shown with a copy, taken
 * back from here too. */
async function subscription(only?: Json): Promise<void> {
  const cals = only ? [only.id] : [];
  let feeds: Json[] = ((await cal.get('/feeds')).feeds as Json[]).filter(f => JSON.stringify(f.cals) === JSON.stringify(cals));
  if (!feeds.length) feeds = [await cal.post('/feeds', { name: only ? only.name : t('구독'), cals })];
  const f = feeds[0];
  const field = h('input', { type: 'text', readonly: true, value: f.url, onfocus: (ev: Event) => (ev.target as HTMLInputElement).select() });
  let revoke = false;
  const body = h('div', { class: 'fields' },
    h('label', null, t('구독 주소'), field),
    h('p', { class: 'actions' },
      button(t('복사'), () => copyText(f.url), 'secondary'),
      button(t('거두기'), (b: HTMLButtonElement) => { revoke = true; b.closest('dialog')?.querySelector<HTMLButtonElement>('button[type=submit]')?.click(); }, 'link')));
  const ok = await dialog(only ? t('{name} 구독 주소', { name: only.name }) : t('폰 캘린더에 넣기'), body, { ok: t('닫기'), cancel: t('취소') });
  if (ok && revoke) {
    if (await dialog(t('구독 주소 거두기'), h('p', null, f.url), { ok: t('거두기'), danger: true })) await cal.del(`/feeds/${f.token}`);
  }
}

/** Devices (CalDAV): the server address and the username to put in a phone's calendar app, a password made
 * per device and shown once, the devices made so far and their revocation — one sheet, kept as it goes. */
async function devices(): Promise<void> {
  const list = h('ul', { class: 'plain devices' });
  const made = h('div', { class: 'device-made' });
  const name = h('input', { type: 'text', name: 'device', maxlength: 60, placeholder: t('기기 이름 (폰, 노트북…)'), autocomplete: 'off' });
  const address = h('input', { type: 'text', readonly: true, onfocus: (ev: Event) => (ev.target as HTMLInputElement).select() });
  const user = h('input', { type: 'text', readonly: true });
  const copy = (value: string) => button(t('복사'), () => copyText(value), 'secondary');
  async function load(): Promise<void> {
    const r = await cal.get('/devices');
    address.value = r.url; user.value = r.username;
    replace(list, (r.devices as Json[]).length ? (r.devices as Json[]).map(d => h('li', null,
      h('span', { class: 'text' }, d.name), ' ', h('span', { class: 'muted small' }, d.last_used ? t('마지막 사용 {when}', { when: when(d.last_used) }) : t('아직 안 씀')),
      button(t('거두기'), async () => { await cal.del(`/devices/${d.id}`); await load(); }, 'link')))
      : h('li', { class: 'muted small' }, t('연결한 기기가 없습니다.')));
  }
  const add = form({ class: 'inline devices-add' }, async () => {
    const n = name.value.trim();
    if (!n) return;
    const r = await cal.post('/devices', { name: n }).catch(e => { flash('error', message(e)); return null; });
    if (!r) return;
    name.value = '';
    const pw = h('input', { type: 'text', readonly: true, value: r.password, class: 'mono', onfocus: (ev: Event) => (ev.target as HTMLInputElement).select() });
    replace(made, h('label', null, t('{name} 의 비밀번호', { name: r.name }), h('span', { class: 'muted small' }, t('(지금만 보입니다)')), pw), h('p', { class: 'actions' }, copy(r.password)));
    pw.focus();
    await load();
  }, name, h('button', { type: 'submit', class: 'secondary' }, t('만들기')));
  await load();
  await dialog(t('기기 연결'), h('div', { class: 'fields' },
    h('label', null, t('서버 주소'), address), h('p', { class: 'actions' }, copy(address.value)),
    h('label', null, t('사용자명'), user),
    h('h3', { class: 'small' }, t('기기 비밀번호')), list, add, made), { justClose: true });
}

/** A calendar's name and colour (a new one of the person's or of a project when `c` is not given). */
async function editCalendar(projects: string[], c?: Json): Promise<Json | null> {
  const name = h('input', { type: 'text', name: 'name', required: true, maxlength: 60, value: c?.name ?? '' });
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();  // the theme's token, as the default
  const color = h('input', { type: 'color', name: 'color', value: c?.color || accent });
  const group = h('select', { name: 'group' }, h('option', { value: '' }, t('내 것')), projects.map(g => h('option', { value: g }, t('프로젝트 {g}', { g }))));
  const ok = await dialog(c ? t('캘린더 설정') : t('새 캘린더'), h('div', { class: 'fields' },
    h('label', null, t('이름'), name), h('label', null, t('색'), color),
    !c && projects.length > 0 && h('label', null, t('누구의'), group)), { ok: t('저장') });
  if (!ok || !name.value.trim()) return null;
  if (c) return cal.patch(`/calendars/${c.id}`, { name: name.value.trim(), color: color.value });
  return cal.post('/calendars', { name: name.value.trim(), color: color.value, group: group.value });
}

/** Another calendar for an event: move it there, or put a copy there. */
async function toCalendar(calendars: Json[], o: Json, copy: boolean): Promise<boolean> {
  const others = calendars.filter(c => c.id !== o.cal);
  const which = h('select', { name: 'cal' }, others.map(c => h('option', { value: c.id }, c.name)));
  const ok = await dialog(copy ? t('다른 캘린더에 복사') : t('다른 캘린더로 옮기기'),
    h('div', { class: 'fields' }, h('p', null, o.summary), h('label', null, t('캘린더'), which)), { ok: copy ? t('복사') : t('옮기기') });
  if (!ok) return false;
  if (copy) await duplicate(o, which.value);
  else await cal.patch(`/events/${o.id}`, { cal: which.value });
  return true;
}

/** A copy of an event (the series, when it repeats) in `into` (its own calendar when not given). */
async function duplicate(o: Json, into?: string): Promise<void> {
  const e = await cal.get(`/events/${o.id}`);
  await cal.post('/events', { cal: into ?? e.cal, summary: e.summary, description: e.description, location: e.location,
                             start: e.start, end: e.end, allday: e.allday, rrule: e.rrule, exdates: e.exdates });
}

// ── the page ──────────────────────────────────────────────────────────────

type View = 'year' | 'month' | 'week' | 'day' | 'list';
const VIEWS: View[] = ['year', 'month', 'week', 'day', 'list'];  // the levels of time, widest first, and the list
const UP: Partial<Record<View, View>> = { day: 'week', week: 'month', month: 'year', list: 'month' };  // the title goes up one level

export async function calendar(): Promise<void> {
  title(t('캘린더'));
  keys([]);
  if (!frame.uid) {
    replace(main(), pageHead(t('캘린더')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/calendar`, t('로그인'))));
    return;
  }
  const params = new URLSearchParams(location.search);
  const today = dayKey(new Date());
  let view: View = (VIEWS as string[]).includes(params.get('v') ?? '') ? params.get('v') as View : 'month';
  let selected = params.get('d') || '';
  let shown = (params.get('m') || (selected || today).slice(0, 7)).split('-').map(Number);  // [year, month]
  let anchor = fromServer(selected || today);  // the week shown holds this day
  let first = new Date();                // Monday of the first week the month's scroller holds (windowFor, below)
  let pendingTop: string | null = null;  // the week (its Monday) to bring under the weekday names at the next draw
  let listDays = LIST_DAYS;
  const off = hidden();
  let calendars: Json[] = [];
  let projects: string[] = [];
  let events: Json[] = [];
  const head = h('div', { class: 'cal-head' });
  const scale = scaleKept();
  const grid = h('div', { class: 'cal-grid', role: 'grid' });
  const week = h('div', { class: 'wk' });
  const wds = h('div', { class: 'cal-wds', role: 'row' });
  const weeksBox = h('div', { class: 'cal-weeks', role: 'rowgroup' });
  const list = h('div', { class: 'cal-list' });
  const year = h('div', { class: 'cal-year' });
  const titleBox = h('h1');
  // on the hours, a sideways swipe or wheel moves the range: once a gesture
  let touchX = 0, touchY = 0, wheeled = 0;
  week.addEventListener('touchstart', ev => { touchX = ev.touches[0].clientX; touchY = ev.touches[0].clientY; }, { passive: true });
  week.addEventListener('touchend', ev => {
    const dx = ev.changedTouches[0].clientX - touchX, dy = ev.changedTouches[0].clientY - touchY;
    if (Math.abs(dx) > SWIPE && Math.abs(dx) > 2 * Math.abs(dy)) void move(dx < 0 ? 1 : -1);
  }, { passive: true });
  week.addEventListener('wheel', ev => {
    if (Math.abs(ev.deltaX) <= Math.abs(ev.deltaY) || Math.abs(ev.deltaX) < SWIPE / 2) return;
    ev.preventDefault();
    if (Date.now() - wheeled < WHEEL_PAUSE) return;
    wheeled = Date.now();
    void move(ev.deltaX > 0 ? 1 : -1);
  }, { passive: false });
  const status = h('div', { role: 'status', class: 'muted small' });
  let rangeVersion = 0, displayedRange = '';
  const panel = h('div', { class: 'cal-day-panel' });
  const byCal = () => Object.fromEntries(calendars.map(c => [c.id, c]));

  function remember(): void {
    const q = new URLSearchParams();
    if (view !== 'month') { q.set('v', view); q.set('d', dayKey(anchor)); }
    else {
      const m = `${shown[0]}-${pad(shown[1])}`;
      if (m !== today.slice(0, 7)) q.set('m', m);
      if (selected) q.set('d', selected);
    }
    history.replaceState(null, '', q.toString() ? `/calendar?${q}` : '/calendar');
  }

  /** Monday of the week that holds `d`. */
  const monday = (d: Date) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };

  const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const monthKey = () => `${shown[0]}-${pad(shown[1])}`;
  /** Monday of the week a month begins in: the month's first row. */
  const monthRow = (y: number, m: number) => monday(new Date(y, m - 1, 1));
  /** The first week the scroller holds when (y, m) is the month shown. */
  const windowFor = (y: number, m: number) => addDays(monthRow(y, m), -WEEKS_BEFORE * 7);
  first = windowFor(shown[0], shown[1]);

  /** What is read: the weeks the month's scroller holds, the week, the day, the list's days, the year. */
  function span(): [Date, Date] {
    if (view === 'week') { const a = monday(anchor); return [a, addDays(a, 7)]; }
    if (view === 'day') { const a = dayStart(anchor); return [a, addDays(a, 1)]; }
    if (view === 'list') { const a = dayStart(anchor); return [a, addDays(a, listDays)]; }
    if (view === 'year') return [new Date(anchor.getFullYear(), 0, 1), new Date(anchor.getFullYear() + 1, 0, 1)];
    return [first, addDays(first, (WEEKS_BEFORE + WEEKS_AFTER) * 7)];
  }

  function perDay(): Record<string, Json[]> {
    const out: Record<string, Json[]> = {};
    for (const o of events) {
      if (off.has(o.cal)) continue;
      for (const k of daysOf(o)) (out[k] ??= []).push(o);
    }
    return out;
  }

  // ── moving an event: dragged onto a day (and, in the week, a time)
  let dragging: Json | null = null;
  async function drop(o: Json, days: number, minutes?: number): Promise<void> {
    if (!days && minutes === undefined) return;
    if (!days && !o.allday && minutes !== undefined && minutes === minutesOf(fromServer(o.start))) return;
    try { await cal.patch(`/events/${o.id}`, moved(o, days, minutes)); await refresh(); }
    catch (e) { flash('error', message(e)); }
  }
  const dropTarget = (el: HTMLElement, fn: (ev: DragEvent) => void) => {
    el.addEventListener('dragover', ev => { if (dragging) { ev.preventDefault(); el.classList.add('over'); } });
    el.addEventListener('dragleave', () => el.classList.remove('over'));
    el.addEventListener('drop', ev => { el.classList.remove('over'); if (dragging) { ev.preventDefault(); fn(ev); } });
  };
  const dayDelta = (o: Json, k: string) => Math.round((fromServer(k).getTime() - fromServer(dayKey(fromServer(o.start))).getTime()) / DAY_MS);

  const open = async (o: Json) => { if (await editEvent(calendars, selected || today, o).catch(e => { flash('error', message(e)); return false; })) await refresh(); };
  const after = (p: Promise<unknown>) => p.then(refresh);
  const dayLabel = (d: Date) => d.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' });
  let ghost: { k: string; minutes: number } | null = null;   // the slot a quick card is open for, shown in its column
  const ghostBlock = (minutes: number) => h('div', { class: 'wk-ghost', 'aria-hidden': 'true', style: `top: ${(minutes / 60) * HOUR}px; height: ${HOUR - 2}px; width: calc(100% - 3px)` });

  /** An event's actions, at the event (R10). */
  const eventMenu = (o: Json): MenuSection[] => [
    { title: o.summary, items: [
      { label: t('열기'), kbd: 'Enter', run: () => open(o) },
      { label: t('복제'), detail: o.recurring ? t('반복 전체') : undefined, run: () => after(duplicate(o)) } ] },
    { items: [
      { label: t('다른 캘린더로 옮기기…'), disabled: calendars.length < 2, run: () => after(toCalendar(calendars, o, false)) },
      { label: t('다른 캘린더에 복사…'), disabled: calendars.length < 2, run: () => after(toCalendar(calendars, o, true)) } ] },
    { items: [
      { label: t('지우기'), danger: true, detail: o.recurring ? t('반복 전체') : undefined, run: async () => {
        if (await dialog(t('일정 지우기'), h('p', null, o.summary), { ok: t('지우기'), danger: true })) { await cal.del(`/events/${o.id}`); await refresh(); }
      } } ] }];

  function chip(o: Json, full = false): HTMLElement {
    const c = byCal()[o.cal];
    const start = fromServer(o.start);
    const el = h('button', { type: 'button', class: `cal-ev${o.recurring ? ' repeats' : ''}`, style: c?.color ? `--ev: ${c.color}` : null, title: o.summary,
                             draggable: o.recurring ? null : 'true', 'data-event': o.id, onclick: () => peekEvent(o, el) },
      !o.allday && h('span', { class: 'cal-time' }, hm(start)), full ? o.summary : h('span', { class: 'cal-title' }, o.summary),
      full && c && h('span', { class: 'muted small' }, ' · ', c.name));
    onMenu(el, () => eventMenu(o), { label: o.summary });
    if (!o.recurring) {
      el.addEventListener('dragstart', ev => { dragging = o; ev.dataTransfer?.setData('text/plain', o.id); el.classList.add('dragging'); });
      el.addEventListener('dragend', () => { dragging = null; el.classList.remove('dragging'); });
    }
    return el;
  }

  /** A new event made where the press was: a title and Enter — an hour at that time, in the first calendar or
   * the one picked; 자세히 takes the title and the slot to the dialog. The slot shows in its column while the
   * card is open. */
  function quick(k: string, minutes: number, at: { x: number; y: number }, col: HTMLElement): void {
    const start = fromServer(k);
    start.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
    const end = new Date(start.getTime() + 3600_000);
    const summary = h('input', { type: 'text', name: 'summary', required: true, maxlength: 200, placeholder: t('제목'), 'aria-label': t('제목') });
    const which = h('select', { name: 'cal', 'aria-label': t('캘린더'), hidden: calendars.length < 2 || null }, calendars.map(c => h('option', { value: c.id }, c.name)));
    const body = h('form', { class: 'quick', onsubmit: (ev: Event) => {
      ev.preventDefault();
      const text = summary.value.trim();
      if (!text) return;
      card.close();
      void act(null, async () => {
        await cal.post('/events', { cal: which.value, summary: text, allday: false, location: '', description: '', rrule: '', start: toUtc(start), end: toUtc(end) });
        await refresh();
      });
    } },
      summary,
      h('p', { class: 'peek-when' }, `${dayLabel(start)} ${hm(start)} – ${hm(end)}`),
      which,
      h('p', { class: 'actions' }, h('button', { type: 'submit' }, t('저장')),
        button(t('자세히'), async () => {
          const seed = { summary: summary.value.trim(), cal: which.value };
          card.close();
          if (await editEvent(calendars, k, undefined, minutes, false, seed)) await refresh();
        }, 'secondary')));
    ghost = { k, minutes };
    col.appendChild(ghostBlock(minutes));
    const card = peek(at, body, { label: t('새 일정'), onClose: () => { ghost = null; week.querySelector('.wk-ghost')?.remove(); } });
  }

  /** An event at a glance, where it is — its line, this card, its dialog: what, when, whose; then its acts. */
  function peekEvent(o: Json, at: HTMLElement): void {
    const c = byCal()[o.cal];
    const start = fromServer(o.start), end = fromServer(o.end);
    const last = o.allday ? new Date(end.getTime() - 1) : end;   // an all-day end is exclusive
    const oneDay = dayKey(start) === dayKey(last);
    const span = o.allday ? (oneDay ? dayLabel(start) : `${dayLabel(start)} – ${dayLabel(last)}`)
      : oneDay ? `${dayLabel(start)} ${hm(start)} – ${hm(end)}` : `${dayLabel(start)} ${hm(start)} – ${dayLabel(end)} ${hm(end)}`;
    const freq = (o.rrule ?? '').split(';').find((x: string) => x.startsWith('FREQ='));
    const repeats = o.recurring || freq ? REPEATS.find(([v]) => v && v === freq)?.[1] ?? n_('반복') : null;
    const closing = (sections: MenuSection[]): MenuSection[] => sections.map(s => ({ ...s, items: s.items.map(it => ({ ...it, run: () => { card.close(); return it.run(); } })) }));
    const card = peek(at, [
      h('h2', null, o.summary),
      h('p', { class: 'peek-when' }, span, o.allday && h('span', { class: 'muted' }, ' · ', t('종일')), repeats && h('span', { class: 'muted' }, ' · ', t(repeats))),
      c && h('p', null, h('span', { class: 'peek-cal', style: c.color ? `--ev: ${c.color}` : null }, c.name)),
      o.location && h('p', { class: 'peek-where' }, o.location),
      o.description && h('p', { class: 'peek-notes' }, o.description),
      h('p', { class: 'actions' },
        button(t('편집'), () => { card.close(); return open(o); }),
        button(t('지우기'), async () => {
          card.close();
          if (await dialog(t('일정 지우기'), h('p', null, o.summary), { ok: t('지우기'), danger: true })) { await cal.del(`/events/${o.id}`); await refresh(); }
        }, 'danger'),
        menuButton(() => closing(eventMenu(o)))),
    ], { label: o.summary });
  }

  /** A day's actions: a new event on it, the week it is in. */
  const dayMenu = (k: string, minutes?: number): MenuSection[] => [{ title: fromServer(k).toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' }), items: [
    { label: t('새 일정'), run: async () => { if (await editEvent(calendars, k, undefined, minutes).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
    { label: t('종일 일정'), run: async () => { if (await editEvent(calendars, k, undefined, undefined, true).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
    view === 'month' ? { label: t('이 주 보기'), run: () => show('week', k) } : { label: t('이 달 보기'), run: () => show('month', k) } ] }];

  /** A calendar's actions, at its chip: what it shows, its settings, its own address, and its end. */
  const calMenu = (c: Json): MenuSection[] => [
    { title: c.name, items: [
      { label: off.has(c.id) ? t('보이기') : t('숨기기'), detail: t('이 브라우저에서'), run: () => { if (off.has(c.id)) off.delete(c.id); else off.add(c.id); keepHidden(off); drawHead(); draw(); } },
      { label: t('이것만 보기'), run: () => { for (const x of calendars) if (x.id !== c.id) off.add(x.id); off.delete(c.id); keepHidden(off); drawHead(); draw(); } } ] },
    { items: [
      { label: t('이름·색 바꾸기…'), detail: c.kind === 'group' ? t('프로젝트 {g} 의 — 구성원이 함께 봅니다', { g: c.owner }) : undefined,
        run: async () => { if (await editCalendar(projects, c)) { calendars = (await cal.get('/calendars')).calendars; drawHead(); await refresh(); } } },
      { label: t('구독 주소…'), detail: t('이 캘린더만'), run: () => subscription(c) } ] },
    { items: [
      { label: t('지우기'), danger: true, disabled: c.main, detail: c.main ? t('기본 캘린더는 남습니다') : t('일정도 함께'), run: async () => {
        if (await dialog(t('캘린더 지우기'), h('p', null, t('{name} 과 그 일정을 모두 지웁니다.', { name: c.name })), { ok: t('지우기'), danger: true, confirmWith: c.name })) {
          await cal.del(`/calendars/${c.id}`); calendars = (await cal.get('/calendars')).calendars; drawHead(); await refresh();
        } } } ] }];

  const calsMenu = (): MenuSection[] => [{ items: [
    { label: t('새 캘린더…'), run: async () => { if (await editCalendar(projects)) { calendars = (await cal.get('/calendars')).calendars; drawHead(); await refresh(); } } },
    { label: t('모두 보이기'), disabled: off.size === 0, run: () => { off.clear(); keepHidden(off); drawHead(); draw(); } },
    { label: t('폰에 구독'), detail: t('보이는 것 모두'), run: () => subscription() },
    { label: t('기기 연결…'), detail: 'CalDAV', run: () => devices() } ] }];

  function titleOf(): string {
    if (view === 'year') return String(anchor.getFullYear());
    if (view === 'week') { const a = monday(anchor); return `${a.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${addDays(a, 6).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`; }
    if (view === 'day') return anchor.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' });
    if (view === 'list') return t('{d} 부터', { d: anchor.toLocaleDateString(undefined, { month: 'long', day: 'numeric' }) });
    return new Date(shown[0], shown[1] - 1, 1).toLocaleDateString(undefined, { year: 'numeric', month: 'long' });
  }

  /** The title: where one is in time, and the way up one level (the year is the top). */
  function drawTitle(): void {
    const up = UP[view];
    if (!up) { replace(titleBox, titleOf()); return; }
    const b = button(titleOf(), () => show(up), 'link');
    b.title = t('한 단계 위로');
    replace(titleBox, b);
  }

  /** Another level of time, or another day at this one: a day named is the day the view is about. */
  function show(v: View, day?: string): void {
    if (day) { anchor = fromServer(day); selected = day; }
    else if (view === 'month') anchor = fromServer(selected.slice(0, 7) === monthKey() ? selected : monthKey() === today.slice(0, 7) ? today : `${monthKey()}-01`);
    if (v === 'month') toMonth(anchor.getFullYear(), anchor.getMonth() + 1, false);
    view = v;
    remember(); drawHead(); draw();
    void refresh();
  }

  /** The month (y, m) under the weekday names: scrolled to when the scroller holds it well inside, drawn around it otherwise. */
  function toMonth(y: number, m: number, now = true): void {
    shown = [y, m];
    const key = dayKey(monthRow(y, m));
    const all = rows();
    const i = all.findIndex(r => r.dataset.week === key);
    if (now && i >= EDGE_ROWS && i < all.length - EDGE_ROWS - MONTH_ROWS) {
      remember(); drawTitle(); dim();
      weeksBox.scrollTop = all[i].offsetTop - wds.offsetHeight;
      return;
    }
    first = windowFor(y, m);
    pendingTop = key;
    if (now) { remember(); drawTitle(); drawGrid(); void refresh(); }
  }

  /** The scale of the view, where it has one: − shows more of time (weeks, hours), + less of it, larger. */
  function scaleBox(): HTMLElement | false {
    const steps = view === 'month' ? WEEKS_SHOWN : view === 'week' || view === 'day' ? HOURS_SHOWN : null;
    if (!steps) return false;
    const at = steps.indexOf(view === 'month' ? scale.weeks : scale.hours);
    const out = button('−', () => zoom(-1), 'link'), into = button('+', () => zoom(1), 'link');
    out.title = t('축소'); out.setAttribute('aria-label', t('축소')); out.disabled = at <= 0;
    into.title = t('확대'); into.setAttribute('aria-label', t('확대')); into.disabled = at >= steps.length - 1;
    return h('span', { class: 'cal-scale', role: 'group', 'aria-label': t('보기 크기') }, out, into);
  }
  function zoom(by: number): void {
    const month = view === 'month';
    if (!month && view !== 'week' && view !== 'day') return;
    const steps = month ? WEEKS_SHOWN : HOURS_SHOWN;
    const next = steps[steps.indexOf(month ? scale.weeks : scale.hours) + by];
    if (next === undefined) return;
    if (month) scale.weeks = next; else scale.hours = next;
    try { localStorage.setItem(SCALE, JSON.stringify(scale)); } catch { /* storage may be off */ }
    drawHead();
    draw();
  }
  /** The month's weeks take the room there is: as many weeks of it as the scale says. */
  function fitMonth(): void {
    const height = room(grid);
    weeksBox.style.setProperty('--cal-h', `${height}px`);
    weeksBox.style.setProperty('--cal-day', `${Math.max(44, Math.floor((height - (wds.offsetHeight || 30)) / scale.weeks) - 1)}px`);
  }

  function drawHead(): void {
    drawTitle();
    replace(head,
      h('div', { class: 'cal-nav' },
        button('‹', () => move(-1), 'link'), button('›', () => move(1), 'link'),
        link(view !== 'month' ? `/calendar?v=${view}&d=${today}` : `/calendar?d=${today}`, t('오늘')),
        choice([['year', t('연')], ['month', t('월')], ['week', t('주')], ['day', t('일')], ['list', t('목록')]], view, v => show(v as View), { 'aria-label': t('보기') }),
        scaleBox(), titleBox),
      h('div', { class: 'cal-sources-row' },
        h('div', { class: 'chips cal-sources', role: 'group', 'aria-label': t('캘린더') }, calendars.map(c =>
          onMenu(h('button', { type: 'button', class: 'chip', 'aria-pressed': off.has(c.id) ? 'false' : 'true', style: c.color ? `--ev: ${c.color}` : null,
                        'data-cal': c.id, title: c.kind === 'group' ? t('프로젝트 {g}', { g: c.owner }) : undefined,
                        onclick: () => { if (off.has(c.id)) off.delete(c.id); else off.add(c.id); keepHidden(off); draw(); } },
            h('span', { class: 'dot', 'aria-hidden': 'true' }), c.name), () => calMenu(c), { label: c.name }))),
        menuButton(calsMenu, t('캘린더 더 보기'))));
  }

  const rows = () => [...weeksBox.querySelectorAll<HTMLElement>('.cal-week')];
  /** The week under the weekday names: the first whose middle is below them. */
  function topRow(): HTMLElement | undefined {
    const y = weeksBox.scrollTop + wds.offsetHeight;
    return rows().find(r => r.offsetTop + r.offsetHeight / 2 > y);
  }
  /** The days of the month shown are plain and in the tab order, the rest dim. */
  function dim(): void {
    const m = monthKey();
    for (const c of weeksBox.querySelectorAll<HTMLElement>('.cal-day')) {
      const other = c.dataset.day!.slice(0, 7) !== m;
      c.classList.toggle('other', other);
      c.tabIndex = other ? -1 : 0;
    }
  }
  function pick(k: string): void {
    selected = k;
    weeksBox.querySelector('.cal-day.selected')?.classList.remove('selected');
    weeksBox.querySelector(`.cal-day[data-day="${k}"]`)?.classList.add('selected');
    remember(); drawPanel();
  }

  function dayCell(d: Date, days: Record<string, Json[]>, m: string): HTMLElement {
    const k = dayKey(d);
    const evs = days[k] ?? [];
    const other = k.slice(0, 7) !== m;
    const cell = h('div', { class: `cal-day${other ? ' other' : ''}${k === today ? ' today' : ''}${k === selected ? ' selected' : ''}`,
                           role: 'gridcell', tabindex: other ? -1 : 0, 'aria-label': d.toLocaleDateString(), 'data-day': k,
                           onclick: () => pick(k),
                           ondblclick: (ev: MouseEvent) => { if (!(ev.target as HTMLElement).closest('.cal-ev')) menu(cell, dayMenu(k)); },
                           onkeydown: (ev: KeyboardEvent) => { if (ev.target === cell && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); pick(k); } } },
      h('span', { class: `cal-num${d.getDate() === 1 ? ' first' : ''}` }, d.getDate() === 1 ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : String(d.getDate())),
      evs.slice(0, 3).map(o => chip(o)),
      evs.length > 3 && h('span', { class: 'cal-more muted small' }, t('+{n}', { n: evs.length - 3 })));
    onMenu(cell, () => dayMenu(k));
    dropTarget(cell, () => { const o = dragging!; void drop(o, dayDelta(o, k)); });
    return cell;
  }

  /** The month: a column of weeks around the month shown, under the weekday names. A redraw keeps the week under the
   * names where it is; a month newly asked for comes to the top, its picked day in sight. */
  function drawGrid(): void {
    if (view !== 'month') { replace(grid); return; }
    const placed = !grid.contains(weeksBox) || !!pendingTop;
    const top = placed ? undefined : topRow();
    const offset = top ? top.offsetTop - weeksBox.scrollTop : 0;
    fitMonth();  // after the week on top is noted: the rows' height may change with the room, and that week stays on top
    const days = perDay();
    const m = monthKey();
    replace(wds, [...Array(7)].map((_, i) => h('div', { class: 'cal-wd', role: 'columnheader' }, addDays(first, i).toLocaleDateString(undefined, { weekday: 'short' }))));
    replace(weeksBox, [wds, ...[...Array(WEEKS_BEFORE + WEEKS_AFTER)].map((_, w) => {
      const start = addDays(first, w * 7);
      return h('div', { class: 'cal-week', role: 'row', 'data-week': dayKey(start) }, [...Array(7)].map((__, i) => dayCell(addDays(start, i), days, m)));
    })]);
    if (!grid.contains(weeksBox)) replace(grid, weeksBox);
    const row = weeksBox.querySelector<HTMLElement>(`.cal-week[data-week="${top ? top.dataset.week : pendingTop ?? dayKey(monthRow(shown[0], shown[1]))}"]`);
    if (row) weeksBox.scrollTop = top ? row.offsetTop - offset : row.offsetTop - wds.offsetHeight;
    const picked = placed && selected ? weeksBox.querySelector<HTMLElement>(`.cal-day[data-day="${selected}"]`)?.parentElement : null;
    if (picked && picked.offsetTop + picked.offsetHeight > weeksBox.scrollTop + weeksBox.clientHeight) weeksBox.scrollTop = picked.offsetTop + picked.offsetHeight - weeksBox.clientHeight;
    pendingTop = null;
  }

  /** The scroll moved: the title, the dimming and the address follow the month in view (a month's first row is the week its
   * 1st is in); near an end of the weeks held, they are drawn again around that month and its events read. */
  function scrolled(): void {
    if (view !== 'month') return;
    const top = topRow();
    if (!top) return;
    const last = addDays(fromServer(top.dataset.week!), 6);
    if (last.getFullYear() !== shown[0] || last.getMonth() + 1 !== shown[1]) {
      shown = [last.getFullYear(), last.getMonth() + 1];
      remember(); drawTitle(); dim();
    }
    if (rows().indexOf(top) < EDGE_ROWS || weeksBox.scrollTop + weeksBox.clientHeight > weeksBox.scrollHeight - EDGE_ROWS * top.offsetHeight) {
      first = windowFor(shown[0], shown[1]);
      drawGrid();
      void refresh();
    }
  }
  let ticking = false;
  weeksBox.addEventListener('scroll', () => { if (ticking) return; ticking = true; requestAnimationFrame(() => { ticking = false; scrolled(); }); });

  function drawPanel(): void {
    if (view !== 'month' || !selected) { replace(panel); return; }
    const list = (perDay()[selected] ?? []).sort((a, b) => Number(!!b.allday) - Number(!!a.allday) || a.start.localeCompare(b.start));
    const due = h('div', { class: 'day-tasks' });
    const day = selected;
    replace(panel,
      h('div', { class: 'section-head' },
        h('h2', null, Object.assign(button(fromServer(selected).toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'long' }), () => show('day', day), 'link'), { title: t('이 날 보기') })),
        h('span', { class: 'actions' }, button(t('+ 일정'), async () => {
          if (await editEvent(calendars, selected).catch(e => { flash('error', message(e)); return false; })) await refresh();
        }, 'secondary'), menuButton(() => dayMenu(day)))),
      list.length ? h('div', { class: 'day-list' }, list.map(o => h('div', { class: 'day-row' }, chip(o, true), menuButton(() => eventMenu(o))))) : empty(t('일정 없음')),
      h('h3', { class: 'small muted' }, t('이 날까지인 할 일')), due);
    void taskList(due, { filter: x => x.due === day, due: day, compact: true }).catch(e => replace(due, h('p', { class: 'flash error' }, message(e))));
  }

  /** The week: an all-day row, then the hours; a timed event is a block at its minutes, side by side when they overlap. */
  function drawWeek(): void {
    if (view !== 'week' && view !== 'day') { replace(week); return; }
    const [start] = span();
    const days = perDay();
    const n = view === 'day' ? 1 : 7;
    week.style.setProperty('--wk-days', String(n));
    const keys = [...Array(n)].map((_, i) => dayKey(addDays(start, i)));
    const headRow = h('div', { class: 'wk-row wk-head' }, h('div', { class: 'wk-corner' }),
      keys.map((k, i) => { const d = addDays(start, i); return onMenu(h('div', { class: `wk-day${k === today ? ' today' : ''}`, 'data-day': k },
        h('span', { class: 'wk-wd' }, d.toLocaleDateString(undefined, { weekday: 'short' })), ' ', view === 'week' ? h('button', { type: 'button', class: 'wk-num', title: t('이 날 보기'), onclick: () => show('day', k) }, String(d.getDate())) : h('span', { class: 'wk-num' }, String(d.getDate()))), () => dayMenu(k)); }));
    const allRow = h('div', { class: 'wk-row wk-allday' }, h('div', { class: 'wk-corner small muted' }, t('종일')),
      keys.map(k => { const col = h('div', { class: 'wk-allcol', 'data-day': k }, (days[k] ?? []).filter(o => o.allday).map(o => chip(o)));
        dropTarget(col, () => { const o = dragging!; void drop(o, dayDelta(o, k)); });
        return col; }));
    const hours = h('div', { class: 'wk-hours' }, [...Array(24)].map((_, hh) => h('div', { class: 'wk-hour', style: `height: ${HOUR}px` }, `${pad(hh)}:00`)));
    const cols = keys.map(k => {
      const col = h('div', { class: `wk-col${k === today ? ' today' : ''}`, 'data-day': k, style: `height: ${24 * HOUR}px` },
        [...Array(24)].map(() => h('div', { class: 'wk-line', style: `height: ${HOUR}px` })));
      const timed = (days[k] ?? []).filter(o => !o.allday).map(o => {
        const s = fromServer(o.start), e = fromServer(o.end);
        const from = dayKey(s) === k ? minutesOf(s) : 0;
        const to = dayKey(e) === k ? Math.max(minutesOf(e), from + 15) : 24 * 60;
        return { o, from, to, lane: 0, lanes: 1 };
      }).sort((a, b) => a.from - b.from || b.to - a.to);
      // lanes: an event takes the first lane free at its start; a cluster of overlapping events shares the width
      const ends: number[] = [];
      let cluster: typeof timed = [];
      const close = () => { const n = ends.length; for (const x of cluster) x.lanes = n; cluster = []; ends.length = 0; };
      for (const x of timed) {
        if (cluster.length && x.from >= Math.max(...ends)) close();
        let lane = ends.findIndex(end => end <= x.from);
        if (lane < 0) { lane = ends.length; ends.push(x.to); } else ends[lane] = x.to;
        x.lane = lane; cluster.push(x);
      }
      close();
      for (const x of timed) {
        const el = chip(x.o);
        el.classList.add('wk-ev');
        el.style.top = `${(x.from / 60) * HOUR}px`;
        el.style.height = `${Math.max(((x.to - x.from) / 60) * HOUR - 2, 18)}px`;
        el.style.left = `${(x.lane / x.lanes) * 100}%`;
        el.style.width = `calc(${100 / x.lanes}% - 3px)`;
        col.appendChild(el);
      }
      if (k === today) { const now = new Date(); col.appendChild(h('div', { class: 'wk-now', style: `top: ${(minutesOf(now) / 60) * HOUR}px` })); }
      if (ghost?.k === k) col.appendChild(ghostBlock(ghost.minutes));
      const minutesAt = (ev: MouseEvent) => { const r = col.getBoundingClientRect(); const m = ((ev.clientY - r.top) / HOUR) * 60; return Math.max(0, Math.min(24 * 60 - SNAP, Math.floor(m / SNAP) * SNAP)); };
      col.addEventListener('click', ev => {
        if ((ev.target as HTMLElement).closest('.cal-ev')) return;
        quick(k, minutesAt(ev), { x: ev.clientX, y: ev.clientY }, col);
      });
      col.addEventListener('contextmenu', ev => {
        if ((ev.target as HTMLElement).closest('.cal-ev')) return;
        ev.preventDefault(); menu({ x: ev.clientX, y: ev.clientY }, dayMenu(k, minutesAt(ev)));
      });
      dropTarget(col, ev => { const o = dragging!; void drop(o, dayDelta(o, k), o.allday ? undefined : minutesAt(ev)); });
      return col;
    });
    const body = h('div', { class: 'wk-body' }, hours, cols);
    replace(week, headRow, allRow, body);
    // the hours take the room there is: at 24 hours shown the whole day fits and nothing scrolls
    const height = room(body), hour = Math.max(12, (height - 2) / scale.hours);
    if (Math.abs(hour - HOUR) > 0.5) { HOUR = hour; drawWeek(); return; }
    body.style.maxHeight = `${height}px`;
    body.scrollTop = scale.hours < 24 ? 7 * HOUR : 0;  // on a larger scale: the morning first
  }

  const byTime = (a: Json, b: Json) => Number(!!b.allday) - Number(!!a.allday) || a.start.localeCompare(b.start);

  /** The list: the days from the anchor on that have events, each under its date; 더 보기 reads further. */
  function drawList(): void {
    if (view !== 'list') { replace(list); return; }
    const [start] = span();
    const days = perDay();
    const groups = [...Array(listDays)].map((_, i) => addDays(start, i)).filter(d => days[dayKey(d)]?.length).map(d => {
      const k = dayKey(d);
      return h('section', { class: `cal-list-day${k === today ? ' today' : ''}`, 'data-day': k },
        groupHead(button(d.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' }), () => show('day', k), 'link'), k === today ? t('오늘') : undefined),
        h('div', { class: 'day-list' }, days[k].slice().sort(byTime).map(o => h('div', { class: 'day-row' }, chip(o, true), menuButton(() => eventMenu(o))))));
    });
    const more = listDays < LIST_MAX ? [h('p', { class: 'actions' }, button(t('더 보기'), () => { listDays = Math.min(LIST_MAX, listDays + LIST_DAYS); void refresh(); }, 'secondary'))] : [];
    replace(list, [...(groups.length ? groups : [empty(t('일정 없음'))]), ...more]);
  }

  /** The year: its twelve months, each day at the level of its events; a month's name opens the month, a day its day. */
  function drawYear(): void {
    if (view !== 'year') { replace(year); return; }
    const y = anchor.getFullYear();
    const counts = new Map(Object.entries(perDay()).map(([k, v]) => [k, v.length] as [string, number]));
    replace(year, [...Array(12)].map((_, m) => monthGrid({ year: y, month: m, counts, pick: k => show('day', k),
      open: () => { anchor = new Date(y, m, 1); selected = ''; show('month'); } })));
  }

  /** A date named: the view at hand goes there (g). */
  async function goToDate(): Promise<void> {
    const date = h('input', { type: 'date', name: 'date', required: true, value: view === 'month' ? selected || today : dayKey(anchor) });
    if (!await dialog(t('날짜로 가기'), h('div', { class: 'fields' }, h('label', null, t('날짜'), date)), { ok: t('가기') }) || !date.value) return;
    show(view, date.value);
  }

  const draw = () => { drawGrid(); drawPanel(); drawWeek(); drawList(); drawYear(); };

  async function refresh(): Promise<void> {
    const version = ++rangeVersion;
    const [a, b] = span();
    const range = '/events?from=' + toUtc(a) + '&to=' + toUtc(b);
    const same = displayedRange === range;
    if (!same) draw();  // what is at hand stays while the new range is read: a day's events are that day's in any range
    replace(status, t('일정을 불러오는 중…'));
    try {
      const r = await cal.get(range);
      if (version !== rangeVersion || !head.isConnected) return;
      const scroll = week.querySelector('.wk-body')?.scrollTop;
      events = r.events;
      displayedRange = range;
      replace(status);
      draw();
      const body = week.querySelector('.wk-body');
      if (body && same && scroll !== undefined) body.scrollTop = scroll;
    } catch (e) {
      if (version !== rangeVersion || !head.isConnected) return;
      replace(status, message(e), ' ', button(t('다시 시도'), refresh, 'link'));
    }
  }

  /** Along time by one of what the view shows: a month scrolled to, a week, a day, the list's length, a year. */
  async function move(by: number): Promise<void> {
    if (view === 'month') { const d = new Date(shown[0], shown[1] - 1 + by, 1); toMonth(d.getFullYear(), d.getMonth() + 1); return; }
    if (view === 'year') anchor = new Date(anchor.getFullYear() + by, anchor.getMonth(), 1);
    else anchor = addDays(anchor, by * (view === 'week' ? 7 : view === 'day' ? 1 : listDays));
    remember();
    drawHead();
    await refresh();
  }

  const listed = await cal.get('/calendars');
  calendars = listed.calendars;
  projects = listed.projects ?? [];
  keys([
    { key: 't', label: t('오늘'), run: () => go(view !== 'month' ? `/calendar?v=${view}&d=${today}` : `/calendar?d=${today}`) },
    { key: 'ArrowLeft', label: t('이전'), run: () => move(-1) },
    { key: 'ArrowRight', label: t('다음'), run: () => move(1) },
    { key: 'y', label: t('연'), run: () => { if (view !== 'year') show('year'); } },
    { key: 'm', label: t('월'), run: () => { if (view !== 'month') show('month'); } },
    { key: 'w', label: t('주'), run: () => { if (view !== 'week') show('week'); } },
    { key: 'd', label: t('일'), run: () => { if (view !== 'day') show('day'); } },
    { key: 'a', label: t('목록'), run: () => { if (view !== 'list') show('list'); } },
    { key: 'g', label: t('날짜로 가기'), run: goToDate },
    { key: '-', label: t('축소'), run: () => zoom(-1) },
    { key: '+', label: t('확대'), run: () => zoom(1) },
    { key: 'n', label: t('새 일정'), run: async () => { if (await editEvent(calendars, selected || today).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
  ]);
  replace(main(), head, status, grid, week, list, year, panel);
  // the room changes with the window: the grids are fitted again (on another page this stops itself)
  let fitting = false;
  const refit = (): void => {
    if (!head.isConnected) { window.removeEventListener('resize', refit); return; }
    if (fitting) return;
    fitting = true;
    requestAnimationFrame(() => { fitting = false; draw(); });
  };
  window.addEventListener('resize', refit);
  drawHead();
  await refresh();
}
