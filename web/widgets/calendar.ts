// The calendar's widgets on the main page (docs/apps-vault-calendar.md §3.4, §7.3): `today` (today's
// events and the to-dos due), `upcoming` (the next seven days) and `tasks` (the to-do list itself: a line is
// written in place and checked off in place). One module for all: the frame says which (ctx.widget.id).
// Built by web/ into dist/widgets/calendar.js and declared in the site file as an absolute module path.

import { api, h, replace, widgetList } from '/auth/static/site.js';
import type { WidgetContext } from '/auth/static/site.js';
import { t } from '../src/lib/i18n';
import { dueWord, taskList, Task } from '../src/lib/tasks';

const cal = api('/calendar/api/v1');
const pad = (n: number) => String(n).padStart(2, '0');
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
function fromServer(s: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
  return new Date(s);
}
const utc = (d: Date) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');

export default async function widget(host: HTMLElement, ctx: WidgetContext): Promise<void> {
  if (ctx.widget.id === 'tasks') { await taskList(host); return; }
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = ctx.widget.id === 'upcoming' ? 7 : 1;
  const end = new Date(start); end.setDate(start.getDate() + days);
  replace(host, h('p', { class: 'muted small' }, '…'));
  const r = await cal.get(`/events?from=${utc(start)}&to=${utc(end)}`);
  const items = (r.events as { summary: string; start: string; allday: boolean; cal: string }[]).map(o => {
    const s = fromServer(o.start);
    const day = dayKey(s);
    const when = o.allday ? (days > 1 ? s.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }) : t('종일'))
      : `${days > 1 ? s.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }) + ' ' : ''}${s.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
    return { href: `/calendar?d=${day}`, text: o.summary, aside: when };
  });
  const dueToday = h('div', { class: 'due-today' });
  replace(host, widgetList(items, days > 1 ? t('앞으로 7일 동안 일정이 없습니다.') : t('오늘은 일정이 없습니다.')),
    days === 1 && dueToday,
    h('p', { class: 'small' }, h('a', { href: `/calendar?d=${dayKey(now)}` }, now.toLocaleDateString(undefined, { month: 'long', day: 'numeric', weekday: 'short' }))));
  if (days === 1) {  // today's widget: the to-dos due by today, under the events (R11: the day with its next action)
    const today = dayKey(now);
    const r2 = await cal.get('/tasks');
    const due = (r2.tasks as Task[]).filter(x => !x.done && x.due && x.due <= today);
    if (due.length) replace(dueToday, h('p', { class: 'small muted' }, t('마감인 할 일')),
      h('ul', { class: 'tasks compact' }, due.map(x => h('li', null, h('span', { class: 'text' }, x.text), ' ', h('span', { class: `tag small ${dueWord(x.due).kind}`.trim() }, dueWord(x.due).text)))));
  }
}
