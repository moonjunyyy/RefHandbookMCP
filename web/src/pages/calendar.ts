// The calendar (/calendar): the person's own calendar and one for each of their projects, on one month
// grid or one week (docs/apps-vault-calendar.md §3.3). The head is one row: the month (or week) and its
// arrows, today, the view (month · week), a chip per calendar (off: hidden on this browser), and the
// subscription address. In the month, a day pressed opens below the grid: its events, and "+ 일정". In
// the week, the hours are a grid: a slot pressed is a new event at that time. An event is written in a
// dialog, changed or removed from the same one, and moved by dragging it onto another day (or, in the
// week, another time); a repeating event is not dragged — its series is changed in the dialog. Times are
// kept in UTC by the service (docs/calendar.md) and shown in the browser's own.
// Every object has its menu where it is (docs/apps-vault-calendar.md §7.4, R10): an event (open, copy,
// move or copy to another calendar, delete), a day (new event, the week), a calendar's chip (rename and
// recolour, hide, only this one, its own subscription address, delete), and the chips' ⋯ (new calendar,
// show all, the phone subscription, connecting a device over CalDAV with a device password — §8.3). The day
// panel also lists the to-dos due that day (§7.3).

import { api, button, choice, dialog, empty, flash, form, frame, go, h, keys, link, main, menu, menuButton, message, onMenu, pageHead, primaryLink, replace, title, when } from '/auth/static/site.js';
import type { Json, MenuSection } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { taskList } from '../lib/tasks';

const cal = api('/calendar/api/v1');
const HIDDEN = 'cal.hidden';  // the calendars this browser keeps off the grid
const REPEATS: [string, string][] = [['', n_('반복 없음')], ['FREQ=DAILY', n_('매일')], ['FREQ=WEEKLY', n_('매주')],
                                     ['FREQ=MONTHLY', n_('매달')], ['FREQ=YEARLY', n_('매년')]];
const HOUR = 44;      // px per hour in the week grid
const SNAP = 30;      // minutes a dropped or pressed time snaps to
const DAY_MS = 86400_000;

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

// ── the event dialog ──────────────────────────────────────────────────────

/** Write an event (a new one on `day`, at `minutes` of it when given — all-day when `wholeDay` — or `ev` to
 * change): true when kept. */
async function editEvent(calendars: Json[], day: string, ev?: Json, minutes?: number, wholeDay = false): Promise<boolean> {
  const start0 = ev ? fromServer(ev.start) : (() => {
    const d = fromServer(day);
    if (minutes !== undefined) d.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
    else d.setHours(new Date().getHours() + 1, 0, 0, 0);
    return d;
  })();
  const end0 = ev ? fromServer(ev.end) : new Date(start0.getTime() + 3600_000);
  const allday = h('input', { type: 'checkbox', checked: ev ? !!ev.allday : wholeDay });
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
      button(t('복사'), async () => { await navigator.clipboard?.writeText(f.url); flash('ok', t('복사했습니다.')); }, 'secondary'),
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
  const copy = (value: string) => button(t('복사'), async () => { await navigator.clipboard?.writeText(value); flash('ok', t('복사했습니다.')); }, 'secondary');
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

type View = 'month' | 'week';

export async function calendar(): Promise<void> {
  title(t('캘린더'));
  keys([]);
  if (!frame.uid) {
    replace(main(), pageHead(t('캘린더')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/calendar`, t('로그인'))));
    return;
  }
  const params = new URLSearchParams(location.search);
  const today = dayKey(new Date());
  let view: View = params.get('v') === 'week' ? 'week' : 'month';
  let selected = params.get('d') || '';
  let shown = (params.get('m') || (selected || today).slice(0, 7)).split('-').map(Number);  // [year, month]
  let anchor = fromServer(selected || today);  // the week shown holds this day
  const off = hidden();
  let calendars: Json[] = [];
  let projects: string[] = [];
  let events: Json[] = [];
  const head = h('div', { class: 'cal-head' });
  const grid = h('div', { class: 'cal-grid', role: 'grid' });
  const week = h('div', { class: 'wk' });
  const panel = h('div', { class: 'cal-day-panel' });
  const byCal = () => Object.fromEntries(calendars.map(c => [c.id, c]));

  function remember(): void {
    const q = new URLSearchParams();
    if (view === 'week') { q.set('v', 'week'); q.set('d', dayKey(anchor)); }
    else {
      const m = `${shown[0]}-${pad(shown[1])}`;
      if (m !== today.slice(0, 7)) q.set('m', m);
      if (selected) q.set('d', selected);
    }
    history.replaceState(null, '', q.toString() ? `/calendar?${q}` : '/calendar');
  }

  /** Monday of the week that holds `d`. */
  const monday = (d: Date) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };

  /** The grid's span: whole weeks (Monday first) around the month, or the one week. */
  function span(): [Date, Date] {
    if (view === 'week') { const a = monday(anchor); return [a, addDays(a, 7)]; }
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
                             draggable: o.recurring ? null : 'true', 'data-event': o.id, onclick: () => open(o) },
      !o.allday && h('span', { class: 'cal-time' }, hm(start)), full ? o.summary : h('span', { class: 'cal-title' }, o.summary),
      full && c && h('span', { class: 'muted small' }, ' · ', c.name));
    onMenu(el, () => eventMenu(o), { label: o.summary });
    if (!o.recurring) {
      el.addEventListener('dragstart', ev => { dragging = o; ev.dataTransfer?.setData('text/plain', o.id); el.classList.add('dragging'); });
      el.addEventListener('dragend', () => { dragging = null; el.classList.remove('dragging'); });
    }
    return el;
  }

  /** A day's actions: a new event on it, the week it is in. */
  const dayMenu = (k: string, minutes?: number): MenuSection[] => [{ title: fromServer(k).toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' }), items: [
    { label: t('새 일정'), run: async () => { if (await editEvent(calendars, k, undefined, minutes).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
    { label: t('종일 일정'), run: async () => { if (await editEvent(calendars, k, undefined, undefined, true).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
    view === 'month' ? { label: t('이 주 보기'), run: () => { view = 'week'; anchor = fromServer(k); selected = k; remember(); drawHead(); void refresh(); } }
      : { label: t('이 달 보기'), run: () => { view = 'month'; selected = k; shown = k.split('-').slice(0, 2).map(Number); remember(); drawHead(); void refresh(); } } ] }];

  /** A calendar's actions, at its chip: what it shows, its settings, its own address, and its end. */
  const calMenu = (c: Json): MenuSection[] => [
    { title: c.name, items: [
      { label: off.has(c.id) ? t('보이기') : t('숨기기'), detail: t('이 브라우저에서'), run: () => { if (off.has(c.id)) off.delete(c.id); else off.add(c.id); keepHidden(off); drawHead(); drawGrid(); drawPanel(); drawWeek(); } },
      { label: t('이것만 보기'), run: () => { for (const x of calendars) if (x.id !== c.id) off.add(x.id); off.delete(c.id); keepHidden(off); drawHead(); drawGrid(); drawPanel(); drawWeek(); } } ] },
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
    { label: t('모두 보이기'), disabled: off.size === 0, run: () => { off.clear(); keepHidden(off); drawHead(); drawGrid(); drawPanel(); drawWeek(); } },
    { label: t('폰에 구독'), detail: t('보이는 것 모두'), run: () => subscription() },
    { label: t('기기 연결…'), detail: 'CalDAV', run: () => devices() } ] }];

  function drawHead(): void {
    const name = view === 'week'
      ? `${monday(anchor).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${addDays(monday(anchor), 6).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
      : new Date(shown[0], shown[1] - 1, 1).toLocaleDateString(undefined, { year: 'numeric', month: 'long' });
    replace(head,
      h('div', { class: 'cal-nav' },
        button('‹', () => move(-1), 'link'), h('h1', null, name), button('›', () => move(1), 'link'),
        link(view === 'week' ? `/calendar?v=week&d=${today}` : `/calendar?d=${today}`, t('오늘')),
        choice([['month', t('월')], ['week', t('주')]], view, v => { view = v as View; if (view === 'week') anchor = fromServer(selected || today); remember(); drawHead(); void refresh(); }, { 'aria-label': t('보기') })),
      h('div', { class: 'cal-sources-row' },
        h('div', { class: 'chips cal-sources', role: 'group', 'aria-label': t('캘린더') }, calendars.map(c =>
          onMenu(h('button', { type: 'button', class: 'chip', 'aria-pressed': off.has(c.id) ? 'false' : 'true', style: c.color ? `--ev: ${c.color}` : null,
                        'data-cal': c.id, title: c.kind === 'group' ? t('프로젝트 {g}', { g: c.owner }) : undefined,
                        onclick: () => { if (off.has(c.id)) off.delete(c.id); else off.add(c.id); keepHidden(off); drawGrid(); drawPanel(); drawWeek(); } },
            h('span', { class: 'dot', 'aria-hidden': 'true' }), c.name), () => calMenu(c), { label: c.name }))),
        menuButton(calsMenu, t('캘린더 더 보기'))));
  }

  function drawGrid(): void {
    if (view !== 'month') { replace(grid); return; }
    const [start] = span();
    const days = perDay();
    const names = [...Array(7)].map((_, i) => addDays(start, i).toLocaleDateString(undefined, { weekday: 'short' }));
    const cells: HTMLElement[] = names.map(n => h('div', { class: 'cal-wd', role: 'columnheader' }, n));
    for (let i = 0; i < 42; i++) {
      const d = addDays(start, i);
      const k = dayKey(d);
      const list = days[k] ?? [];
      const cell = h('div', { class: `cal-day${d.getMonth() !== shown[1] - 1 ? ' other' : ''}${k === today ? ' today' : ''}${k === selected ? ' selected' : ''}`,
                             role: 'gridcell', tabindex: 0, 'aria-label': d.toLocaleDateString(), 'data-day': k,
                             onclick: () => { selected = k; remember(); drawGrid(); drawPanel(); },
                             ondblclick: (ev: MouseEvent) => { if (!(ev.target as HTMLElement).closest('.cal-ev')) menu(cell, dayMenu(k)); },
                             onkeydown: (ev: KeyboardEvent) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); selected = k; remember(); drawGrid(); drawPanel(); } } },
        h('span', { class: 'cal-num' }, String(d.getDate())),
        list.slice(0, 3).map(o => chip(o)),
        list.length > 3 && h('span', { class: 'cal-more muted small' }, t('+{n}', { n: list.length - 3 })));
      onMenu(cell, () => dayMenu(k));
      dropTarget(cell, () => { const o = dragging!; void drop(o, dayDelta(o, k)); });
      cells.push(cell);
    }
    replace(grid, cells);
  }

  function drawPanel(): void {
    if (view !== 'month' || !selected) { replace(panel); return; }
    const list = (perDay()[selected] ?? []).sort((a, b) => Number(!!b.allday) - Number(!!a.allday) || a.start.localeCompare(b.start));
    const due = h('div', { class: 'day-tasks' });
    const day = selected;
    replace(panel,
      h('div', { class: 'section-head' },
        h('h2', null, fromServer(selected).toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'long' })),
        h('span', { class: 'actions' }, button(t('+ 일정'), async () => {
          if (await editEvent(calendars, selected).catch(e => { flash('error', message(e)); return false; })) await refresh();
        }, 'secondary'), menuButton(() => dayMenu(day)))),
      list.length ? h('div', { class: 'day-list' }, list.map(o => h('div', { class: 'day-row' }, chip(o, true), menuButton(() => eventMenu(o))))) : empty(t('일정 없음')),
      h('h3', { class: 'small muted' }, t('이 날까지인 할 일')), due);
    void taskList(due, { filter: x => x.due === day, due: day, compact: true }).catch(e => replace(due, h('p', { class: 'flash error' }, message(e))));
  }

  /** The week: an all-day row, then the hours; a timed event is a block at its minutes, side by side when they overlap. */
  function drawWeek(): void {
    if (view !== 'week') { replace(week); return; }
    const [start] = span();
    const days = perDay();
    const keys = [...Array(7)].map((_, i) => dayKey(addDays(start, i)));
    const headRow = h('div', { class: 'wk-row wk-head' }, h('div', { class: 'wk-corner' }),
      keys.map((k, i) => { const d = addDays(start, i); return onMenu(h('div', { class: `wk-day${k === today ? ' today' : ''}`, 'data-day': k },
        h('span', { class: 'wk-wd' }, d.toLocaleDateString(undefined, { weekday: 'short' })), ' ', h('span', { class: 'wk-num' }, String(d.getDate()))), () => dayMenu(k)); }));
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
      const minutesAt = (ev: MouseEvent) => { const r = col.getBoundingClientRect(); const m = ((ev.clientY - r.top) / HOUR) * 60; return Math.max(0, Math.min(24 * 60 - SNAP, Math.floor(m / SNAP) * SNAP)); };
      col.addEventListener('click', async ev => {
        if ((ev.target as HTMLElement).closest('.cal-ev')) return;
        if (await editEvent(calendars, k, undefined, minutesAt(ev)).catch(e => { flash('error', message(e)); return false; })) await refresh();
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
    body.scrollTop = 7 * HOUR;  // the morning first
  }

  async function refresh(): Promise<void> {
    await load();
    drawGrid();
    drawPanel();
    drawWeek();
  }

  async function move(by: number): Promise<void> {
    if (view === 'week') anchor = addDays(anchor, 7 * by);
    else { const d = new Date(shown[0], shown[1] - 1 + by, 1); shown = [d.getFullYear(), d.getMonth() + 1]; }
    remember();
    drawHead();
    await refresh();
  }

  const listed = await cal.get('/calendars');
  calendars = listed.calendars;
  projects = listed.projects ?? [];
  await load();
  keys([
    { key: 't', label: t('오늘'), run: () => go(view === 'week' ? `/calendar?v=week&d=${today}` : `/calendar?d=${today}`) },
    { key: 'ArrowLeft', label: t('이전'), run: () => move(-1) },
    { key: 'ArrowRight', label: t('다음'), run: () => move(1) },
    { key: 'm', label: t('월'), run: () => { if (view !== 'month') { view = 'month'; remember(); drawHead(); void refresh(); } } },
    { key: 'w', label: t('주'), run: () => { if (view !== 'week') { view = 'week'; anchor = fromServer(selected || today); remember(); drawHead(); void refresh(); } } },
    { key: 'n', label: t('새 일정'), run: async () => { if (await editEvent(calendars, selected || today).catch(e => { flash('error', message(e)); return false; })) await refresh(); } },
  ]);
  replace(main(), head, grid, week, panel);
  drawHead();
  drawGrid();
  drawPanel();
  drawWeek();
}
