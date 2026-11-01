// The main page (/): the person's widgets — the pieces the apps they turned on offer (docs/frame.md §4),
// in the order they arranged them. The first thing on the page is the grid; its one tool is "edit",
// in which cells are dragged into order (or moved with Alt+←/→), taken off (× or Delete) and added
// ("+ widget", from the apps that are on). With no app on, the page is the catalog: the thing to do.
// Right after signing in it opens the person's start page.

import { button, dialog, frame, h, help, main, mount, onApps, prefs, primaryLink, replace, savePrefs, title, widgetsOf, LAUNCHER } from '/auth/static/site.js';
import type { Card, Placement, Widget } from '/auth/static/site.js';
import { t } from '../lib/i18n';
import { catalog } from './apps';

/** The cells as the person has them: their own arrangement, else each app's launcher as turned on. */
function placements(): Placement[] {
  const on = onApps();
  const own = prefs.home.filter(p => on.some(c => c.id === p.app) && widgetsOf(on.find(c => c.id === p.app)!).some(w => w.id === p.widget));
  return own.length ? own : on.map(c => ({ app: c.id, widget: LAUNCHER }));
}

function resolve(p: Placement): [Card, Widget] | null {
  const c = frame.cards.find(x => x.id === p.app);
  const w = c && widgetsOf(c).find(x => x.id === p.widget);
  return c && w ? [c, w] : null;
}

export async function home(): Promise<void> {
  const params = new URLSearchParams(location.search);
  if (params.has('start')) {  // just signed in: their start page, if they chose one of the site's
    history.replaceState(null, '', '/');
    if (frame.uid && prefs.start.startsWith('/') && !prefs.start.startsWith('//') && prefs.start !== '/') {
      location.replace(prefs.start);
      return;
    }
  }
  title('');
  let editing = false;
  if (!frame.uid) {
    replace(main(),
      h('div', { class: 'page-head' }, h('h1', null, frame.title)),
      h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/`, t('로그인'))),
      frame.cards.length > 0 && h('div', { class: 'widgets' }, frame.cards.map(c => cell(c, widgetsOf(c)[0]))));
    return;
  }
  if (!onApps().length) {  // nothing on yet: the catalog is the page
    replace(main(), h('div', { class: 'page-head' }, h('h1', null, t('앱 켜기'))), catalog());
    return;
  }
  const grid = h('div', { class: 'widgets' });
  const head = h('div', { class: 'section-head' }, h('span'), h('span'));

  function cell(c: Card, w: Widget, i = -1): HTMLElement {
    const el = h('article', { class: `widget card${w.size.startsWith('2') ? ' w2' : ''}${w.size.endsWith('2') ? ' h2' : ''}`,
                              'data-app': c.id, 'data-widget': w.id, tabindex: editing ? 0 : null, draggable: editing ? 'true' : null,
                              'aria-label': `${c.title} · ${w.title}` });
    void mount(el, c, w);
    if (editing && i >= 0) {
      el.appendChild(h('div', { class: 'widget-tools' }, button('×', () => remove(i), 'secondary')));
      el.addEventListener('keydown', ev => {
        if (ev.altKey && ev.key === 'ArrowLeft') { ev.preventDefault(); void move(i, i - 1); }
        if (ev.altKey && ev.key === 'ArrowRight') { ev.preventDefault(); void move(i, i + 1); }
        if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); void remove(i); }
      });
      el.addEventListener('dragstart', ev => { ev.dataTransfer?.setData('text/plain', String(i)); el.classList.add('dragging'); });
      el.addEventListener('dragend', () => el.classList.remove('dragging'));
      el.addEventListener('dragover', ev => { ev.preventDefault(); el.classList.add('over'); });
      el.addEventListener('dragleave', () => el.classList.remove('over'));
      el.addEventListener('drop', ev => {
        ev.preventDefault();
        el.classList.remove('over');
        const from = Number(ev.dataTransfer?.getData('text/plain'));
        if (!Number.isNaN(from) && from !== i) void move(from, i);
      });
    }
    return el;
  }

  async function keep(next: Placement[], focus?: number): Promise<void> {
    await savePrefs({ home: next });
    draw();
    if (focus !== undefined) (grid.children[Math.min(focus, grid.children.length - 1)] as HTMLElement | undefined)?.focus();
  }
  const move = (from: number, to: number) => {
    const list = placements();
    if (to < 0 || to >= list.length) return Promise.resolve();
    const [p] = list.splice(from, 1);
    list.splice(to, 0, p);
    return keep(list, to);
  };
  const remove = (i: number) => keep(placements().filter((_, k) => k !== i), i);

  async function add(): Promise<void> {
    const have = placements();
    const choices = onApps().flatMap(c => widgetsOf(c).map(w => ({ c, w, on: have.some(p => p.app === c.id && p.widget === w.id) })));
    const boxes = choices.map(x => h('input', { type: 'checkbox', checked: x.on, name: `${x.c.id}/${x.w.id}` }));
    const ok = await dialog(t('위젯'), h('div', { class: 'fields' }, choices.map((x, k) =>
      h('label', { class: 'check' }, boxes[k], `${x.c.title} · ${x.w.title}`))), { ok: t('적용') });
    if (!ok) return;
    const next = choices.filter((_, k) => boxes[k].checked).map(x => ({ app: x.c.id, widget: x.w.id }));
    await keep([...have.filter(p => next.some(n => n.app === p.app && n.widget === p.widget)),
                ...next.filter(n => !have.some(p => n.app === p.app && n.widget === p.widget))]);
  }

  function draw(): void {
    const list = placements();
    grid.className = `widgets${editing ? ' editing' : ''}`;
    replace(grid, list.map((p, i) => { const r = resolve(p); return r && cell(r[0], r[1], i); }));
    replace(head,
      h('span'),
      h('span', { class: 'actions' },
        editing && [button(t('+ 위젯'), add, 'secondary'), help(t('칸을 끌어 순서를 바꾸고(Alt+←→), × 나 Delete 로 뺍니다.'))],
        button(editing ? t('완료') : t('편집'), () => { editing = !editing; draw(); }, 'link')));
  }

  replace(main(), head, grid);
  draw();
}

export { placements };
