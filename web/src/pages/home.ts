// The main page (/): the person's widgets — the pieces the apps they added offer (docs/frame.md §4),
// in the order and the sizes they arranged them. The first thing on the page is the grid, handled in place
// (docs/apps-vault-calendar.md §8.1, R10·R15): a widget is moved by dragging its head (a launcher: the cell)
// onto another cell, resized by dragging its corner grip (it snaps to one of the sizes the site declares),
// and every cell's ⋯ (right-click, Shift+F10) offers the sizes, forward, back and taking it off; by keyboard a
// focused cell moves with Alt+←/→ and leaves with Delete. The grid's last cell, "위젯 고르기" (key w), is the
// one tool, with no row of tools above the grid: a sheet of the apps added, a row per widget — a switch, what it shows, its size — with the widget
// itself drawn beside the list as the row is pointed at (the preview is the module, not a picture). With no
// app on, the page is one action — add apps — which goes to the store (/apps); the main page itself is never
// the store. Right after signing in it opens the person's start page.

import { dialog, frame, h, keys, main, menuButton, mount, onApps, onMenu, prefs, primaryLink, replace, savePrefs, sizeOf, spanStyle,
         tag, title, toggle, widgetsOf, LAUNCHER } from '/auth/static/site.js';
import type { Card, MenuSection, Placement, Size, Widget } from '/auth/static/site.js';
import { t } from '../lib/i18n';

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

const sizeWord = (s: Size) => `${s.cols}×${s.rows}`;

/** The declared size nearest to a wanted (cols, rows) — what a dragged corner snaps to. */
function nearest(cols: number, rows: number): Size {
  return frame.sizes.reduce((best, s) => Math.abs(s.cols - cols) + Math.abs(s.rows - rows) < Math.abs(best.cols - cols) + Math.abs(best.rows - rows) ? s : best, frame.sizes[0]);
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
  if (!frame.uid) {
    replace(main(),
      h('div', { class: 'page-head' }, h('h1', null, frame.title)),
      h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/`, t('로그인'))),
      frame.cards.length > 0 && h('div', { class: 'widgets' }, frame.cards.map(c => cell(c, widgetsOf(c)[0]))));
    keys([]);
    return;
  }
  if (!onApps().length) {  // nothing on yet: the one thing to do, which is in the store
    replace(main(), h('div', { class: 'empty-home' }, primaryLink('/apps', t('앱 추가'))));
    keys([]);
    return;
  }
  const grid = h('div', { class: 'widgets' });

  function cell(c: Card, w: Widget, i = -1, p?: Placement): HTMLElement {
    const size = sizeOf(p?.size ?? w.size);
    const el = h('article', { class: 'widget card', style: spanStyle(size.id), 'data-app': c.id, 'data-widget': w.id, 'data-size': size.id,
                              tabindex: i >= 0 ? 0 : null, 'aria-label': `${c.title} · ${w.title}` });
    void mount(el, c, w);
    if (i < 0) return el;
    const sections = (): MenuSection[] => [
      { title: `${c.title} · ${w.title}`, items: frame.sizes.map(s => ({ label: sizeWord(s), detail: s.id === size.id ? t('지금') : undefined, disabled: s.id === size.id,
                                                                      run: () => resize(i, s) })) },
      { items: [
        { label: t('앞으로'), kbd: 'Alt+←', run: () => move(i, i - 1), disabled: i === 0 },
        { label: t('뒤로'), kbd: 'Alt+→', run: () => move(i, i + 1), disabled: i >= placements().length - 1 },
        { label: t('빼기'), kbd: 'Del', run: () => remove(i), danger: true } ] }];
    // the handle: the head of a widget, the whole cell of a launcher
    const handle = w.id === LAUNCHER ? el : (el.querySelector('.widget-head') as HTMLElement | null) ?? el;
    handle.setAttribute('draggable', 'true');
    handle.classList.add('handle');
    handle.addEventListener('dragstart', ev => { ev.dataTransfer?.setData('text/plain', String(i)); ev.dataTransfer!.effectAllowed = 'move'; el.classList.add('dragging'); });
    handle.addEventListener('dragend', () => el.classList.remove('dragging'));
    el.addEventListener('dragover', ev => { ev.preventDefault(); el.classList.add('over'); });
    el.addEventListener('dragleave', () => el.classList.remove('over'));
    el.addEventListener('drop', ev => {
      ev.preventDefault();
      el.classList.remove('over');
      const from = Number(ev.dataTransfer?.getData('text/plain'));
      if (!Number.isNaN(from) && from !== i) void move(from, i);
    });
    el.addEventListener('keydown', ev => {
      if (ev.target !== el) return;  // a key inside the widget's own content is its own
      if (ev.altKey && ev.key === 'ArrowLeft') { ev.preventDefault(); void move(i, i - 1); }
      if (ev.altKey && ev.key === 'ArrowRight') { ev.preventDefault(); void move(i, i + 1); }
      if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); void remove(i); }
    });
    onMenu(el, sections);
    el.appendChild(h('div', { class: 'widget-tools' }, menuButton(sections)));
    // the grip: dragged, the cell takes the nearest declared size; let go, it is kept
    const grip = h('div', { class: 'widget-grip', title: t('크기'), 'aria-hidden': 'true' });
    grip.addEventListener('pointerdown', ev => {
      ev.preventDefault();
      grip.setPointerCapture(ev.pointerId);
      const r0 = el.getBoundingClientRect();
      const gap = parseFloat(getComputedStyle(grid).gap) || 0;
      const unitW = (r0.width - gap * (size.cols - 1)) / size.cols;
      const unitH = Math.max(80, (r0.height - gap * (size.rows - 1)) / size.rows);
      const maxCols = Math.max(1, Math.round((grid.clientWidth + gap) / (unitW + gap)));
      let want: Size = size;
      const at = (e: PointerEvent) => {
        const cols = Math.min(maxCols, Math.max(1, Math.round((e.clientX - r0.left + gap / 2) / (unitW + gap))));
        const rows = Math.max(1, Math.round((e.clientY - r0.top + gap / 2) / (unitH + gap)));
        return nearest(Math.min(cols, Math.max(...frame.sizes.map(s => s.cols))), Math.min(rows, Math.max(...frame.sizes.map(s => s.rows))));
      };
      const onMove = (e: PointerEvent) => { want = at(e); el.setAttribute('style', spanStyle(want.id)); el.dataset.size = want.id; el.classList.add('resizing'); };
      const onUp = () => {
        grip.removeEventListener('pointermove', onMove); grip.removeEventListener('pointerup', onUp); grip.removeEventListener('pointercancel', onUp);
        el.classList.remove('resizing');
        if (want.id !== size.id) void resize(i, want); else el.setAttribute('style', spanStyle(size.id));
      };
      grip.addEventListener('pointermove', onMove); grip.addEventListener('pointerup', onUp); grip.addEventListener('pointercancel', onUp);
    });
    el.appendChild(grip);
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
  const resize = (i: number, s: Size) => keep(placements().map((p, k) => (k === i ? { ...p, size: s.id } : p)), i);

  /** The sheet of widgets (R12): by app, each a row — a switch, the title, what it shows, its size — kept as
   * it is switched; a widget switched on goes to the end of the grid. The row pointed at (hover, focus) is
   * drawn beside the list, by its own module (R16). */
  async function pick(): Promise<void> {
    const isOn = (c: Card, w: Widget) => placements().some(p => p.app === c.id && p.widget === w.id);
    const preview = h('div', { class: 'pick-preview', 'aria-live': 'polite' });
    let timer = 0;
    let shown = '';
    const show = (c: Card, w: Widget) => {
      const key = `${c.id}/${w.id}`;
      if (key === shown) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        shown = key;
        const s = sizeOf(w.size);
        replace(preview, h('p', { class: 'pick-preview-title small muted' }, w.id === LAUNCHER ? c.title : `${c.title} · ${w.title}`, ' ', sizeWord(s)),
          cell(c, w));
        (preview.lastElementChild as HTMLElement).style.minHeight = `${s.rows * 120}px`;
        (preview.lastElementChild as HTMLElement).classList.add(s.cols > 1 ? 'wide' : 'narrow');
      }, 150);
    };
    const rows = onApps().map(c => h('div', { class: 'pick-group' },
      h('h3', null, c.icon && h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon), c.title),
      widgetsOf(c).map(w => {
        const row = h('div', { class: 'pick-row', 'data-app': c.id, 'data-widget': w.id,
                               onmouseenter: () => show(c, w), onfocusin: () => show(c, w) },
          toggle('', isOn(c, w), on => keep(on ? [...placements(), { app: c.id, widget: w.id }]
            : placements().filter(p => !(p.app === c.id && p.widget === w.id))), { 'aria-label': `${c.title} · ${w.title}` }),
          h('div', { class: 'pick-text' },
            h('span', { class: 'pick-title' }, w.id === LAUNCHER ? t('바로가기') : w.title),
            h('span', { class: 'pick-desc muted small' }, w.id === LAUNCHER ? t('앱의 이름과 링크') : w.description)),
          tag(sizeWord(sizeOf(w.size)), 'size'));
        return row;
      })));
    await dialog(t('위젯 고르기'), h('div', { class: 'pick-wrap' }, h('div', { class: 'pick-list' }, rows), preview), { justClose: true });
  }

  // the grid's last cell is the way to more widgets: no row of tools above the grid (what the cells do is in their ⋯)
  const more = h('button', { type: 'button', class: 'add-widget', 'aria-keyshortcuts': 'w', onclick: () => void pick() },
    h('span', { class: 'add-mark', 'aria-hidden': 'true' }, '+'), t('위젯 고르기'));

  function draw(): void {
    const list = placements();
    replace(grid, list.map((p, i) => { const r = resolve(p); return r && cell(r[0], r[1], i, p); }), more);
  }

  keys([{ key: 'w', label: t('위젯 고르기'), run: pick }]);
  replace(main(), grid);
  draw();
}

export { placements };
