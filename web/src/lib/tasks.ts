// The to-do list (docs/apps-vault-calendar.md §7.3): the person's own lines, kept by the calendar service
// (/calendar/api/v1/tasks). Drawn by the main page's `tasks` widget and by the calendar's day panel (the
// ones due that day): a line is written in place (Enter), checked off in place, and the rest — a due day,
// the text, taking it out — is on its menu (⋯ or right-click: R10).

import { api, button, dialog, h, menuButton, onMenu, replace } from '/auth/static/site.js';
import type { MenuSection } from '/auth/static/site.js';
import { t } from './i18n';

const cal = api('/calendar/api/v1');
const pad = (n: number) => String(n).padStart(2, '0');
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromDay = (s: string) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };

export interface Task { id: string; text: string; done: boolean; due: string; rank: number }

/** How a due day reads next to the line: today, tomorrow, overdue (by how much), or the date. */
export function dueWord(due: string, today = dayKey(new Date())): { text: string; kind: '' | 'warn' | 'bad' } {
  if (!due) return { text: '', kind: '' };
  if (due === today) return { text: t('오늘'), kind: 'warn' };
  const d = fromDay(due);
  const late = Math.round((fromDay(today).getTime() - d.getTime()) / 86400000);
  if (late === -1) return { text: t('내일'), kind: '' };
  if (late > 0) return { text: t('{n}일 지남', { n: late }), kind: 'bad' };
  return { text: d.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }), kind: '' };
}

/** The to-do list, drawn into `host`; `filter` keeps only some (the day panel shows the ones due that day). */
export async function taskList(host: HTMLElement, opts: { filter?: (x: Task) => boolean; compact?: boolean; due?: string } = {}): Promise<() => Promise<void>> {
  const list = h('ul', { class: 'tasks' });
  const input = h('input', { type: 'text', name: 'task', maxlength: 200, autocomplete: 'off',
                             placeholder: t('할 일을 적고 Enter'), 'aria-label': t('새 할 일') });
  const foot = h('div', { class: 'tasks-foot small muted' });
  const add = h('form', { class: 'tasks-add' }, input);
  add.addEventListener('submit', ev => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    cal.post('/tasks', opts.due ? { text, due: opts.due } : { text }).then(() => { input.value = ''; return load(); })
      .catch((e: Error) => { foot.textContent = e.message; }).finally(() => { input.disabled = false; input.focus(); });
  });
  async function load(): Promise<void> {
    const r = await cal.get('/tasks');
    draw((r.tasks as Task[]).filter(opts.filter ?? (() => true)));
  }
  async function change(x: Task, body: Partial<Task>): Promise<void> {
    await cal.patch(`/tasks/${x.id}`, body);
    await load();
  }
  function dateOf(x: Task): Promise<void> {
    const d = h('input', { type: 'date', name: 'due', value: x.due });
    return dialog(t('기한일'), h('label', null, t('날짜'), d), { ok: t('적용') }).then(async ok => { if (ok && d.value) await change(x, { due: d.value }); });
  }
  function textOf(x: Task): Promise<void> {
    const i = h('input', { type: 'text', name: 'text', value: x.text, maxlength: 200 });
    return dialog(t('할 일 고치기'), h('label', null, t('할 일'), i), { ok: t('적용') }).then(async ok => {
      if (ok && i.value.trim() && i.value.trim() !== x.text) await change(x, { text: i.value.trim() });
    });
  }
  const today = dayKey(new Date());
  const tomorrow = dayKey(new Date(Date.now() + 86400000));
  const sections = (x: Task): MenuSection[] => [
    { title: t('기한일'), items: [
      { label: t('오늘까지'), run: () => change(x, { due: today }), disabled: x.due === today },
      { label: t('내일까지'), run: () => change(x, { due: tomorrow }), disabled: x.due === tomorrow },
      { label: t('날짜 고르기…'), run: () => dateOf(x) },
      { label: t('기한 없애기'), run: () => change(x, { due: '' }), disabled: !x.due } ] },
    { items: [
      { label: t('고치기…'), run: () => textOf(x) },
      { label: x.done ? t('다시 할 일로') : t('끝남'), run: () => change(x, { done: !x.done }) },
      { label: t('지우기'), danger: true, run: async () => { await cal.del(`/tasks/${x.id}`); await load(); } } ] }];
  function row(x: Task): HTMLElement {
    const box = h('input', { type: 'checkbox', checked: x.done, 'aria-label': x.text });
    box.addEventListener('change', () => { box.disabled = true; void change(x, { done: box.checked }).catch(() => { box.checked = !box.checked; box.disabled = false; }); });
    const due = dueWord(x.due);
    const li = h('li', { class: x.done ? 'done' : null, 'data-task': x.id },
      h('label', { class: 'check inline' }, box, h('span', { class: 'text' }, x.text)),
      due.text && h('span', { class: `tag small ${due.kind}`.trim() }, due.text),
      menuButton(() => sections(x)));
    onMenu(li, () => sections(x));
    return li;
  }
  function draw(items: Task[]): void {
    const open = items.filter(x => !x.done);
    replace(list, items.map(row));
    replace(foot,
      items.length === 0 ? (opts.filter ? t('이 날까지인 할 일이 없습니다.') : t('할 일이 없습니다. 위에 적으세요.'))
        : open.length ? t('{n}개 남음', { n: open.length }) : t('다 끝났습니다.'),
      items.some(x => x.done) && button(t('끝난 것 치우기'), async () => { await cal.post('/tasks/clear-done'); await load(); }, 'link'));
  }
  replace(host, h('div', { class: `tasks-widget${opts.compact ? ' compact' : ''}` }, add, list, foot));
  await load();
  return load;
}


export { dayKey as taskDayKey };
